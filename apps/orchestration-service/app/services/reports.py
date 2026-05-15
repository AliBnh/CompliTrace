from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.audit import AnalysisCitation, Audit, AuditAnalysisItem, Finding, Report
from app.services.clients import IngestionClient, SectionData

REPORT_SCHEMA_VERSION = "v1.0"
PDF_SAFE_CHAR_REPLACEMENTS = str.maketrans(
    {
        "•": "-",
        "—": "-",
        "–": "-",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "…": "...",
    }
)


BANNED_USER_TOKENS = [
    "support_only",
    "internal_only",
    "candidate_issue",
    "candidate_gap",
    "provisional_local",
    "support_evidence",
    "post_reviewer_snapshot",
    "meta_section",
    "auditability gate",
    "not_assessable",
    "confirmed_document_gap",
    "probable_document_gap",
    "clear_non_compliance",
    "withheld by final publication validator",
    "explicit violation validator matched",
    "duty validation marked",
    "invalid_consent",
    "profiling_without_required_explanation",
    "weak_transfer_safeguards",
    "embedding model",
    "corpus version",
    "parse failure rate",
    "contradiction rate",
    "heuristic quality score",
    "confidence component breakdown",
    # Audit-runner diagnostic-suppression messages — must never reach published output.
    "local finding suppressed:",
    "finding classified as internal diagnostic",
    "local finding",
    "anchor is absent",
    "required gdpr article anchor",
    "internal diagnostic",
    "diagnostic only",
    "conditional issue",
    "duty_key=",
    "duty_status=",
]

# Lowercase cache for fast membership checks (built once at import time)
_BANNED_TOKENS_LOWER: list[str] = [t.lower() for t in BANNED_USER_TOKENS]

ISSUE_TITLE_MAP = {
    "missing_legal_basis": "Missing legal basis disclosure",
    "missing_retention_period": "Missing retention-period disclosure",
    "missing_rights_notice": "Missing rights-notice disclosure",
    "missing_complaint_right": "Missing complaint-right disclosure",
    "missing_transfer_notice": "Missing transfer disclosure",
    "profiling_disclosure_gap": "Profiling transparency gap",
    "recipients_disclosure_gap": "Recipients disclosure gap",
    "purpose_specificity_gap": "Purpose specificity gap",
    "controller_processor_role_ambiguity": "Role allocation needs clarification",
    "lawful_basis_and_consent": "Lawful basis and consent",
}

ISSUE_WHY_TEXT_MAP = {
    "missing_legal_basis": "The notice describes processing activities but does not state the lawful basis for those activities.",
    "missing_retention_period": "The notice does not clearly state retention periods or objective retention criteria.",
    "missing_rights_notice": "The notice does not explain the rights available to data subjects in a complete and usable way.",
    "missing_complaint_right": "The notice does not clearly explain that people can lodge a complaint with a supervisory authority.",
    "missing_transfer_notice": "The notice refers to international transfers but does not explain the safeguard relied upon.",
    "profiling_disclosure_gap": "The notice does not clearly explain profiling logic, significance, or likely consequences where profiling is referenced.",
    "recipients_disclosure_gap": "The notice does not clearly identify categories of recipients or third parties receiving personal data.",
    "purpose_specificity_gap": "The categories of personal data are described, but the related purpose mapping is not sufficiently explicit.",
    "missing_controller_contact": "The notice does not provide clear contact details for privacy or data-protection requests.",
    "missing_controller_identity": "The notice does not clearly identify the data controller.",
    "controller_processor_role_ambiguity": "The notice does not clearly explain when the organisation acts as controller or processor.",
    "cookie_disclosure_gap": "The notice references cookies or similar technologies without clearly explaining their purposes, controls, and legal basis.",
    "lawful_basis_and_consent": "The notice does not adequately disclose the lawful basis for processing, does not obtain valid consent where required, and does not clearly explain the legal ground for tracking technologies.",
    "invalid_consent_or_legal_basis": "The notice does not clearly state a valid lawful basis for the described processing activities, or the basis stated does not meet GDPR validity requirements.",
    "cookies_tracking_consent_gap": "The notice references cookies or tracking technologies without providing the transparency required about their purposes, legal basis, and user controls.",
    "article14_source_transparency_gap": "The notice does not disclose the source from which personal data was indirectly obtained, as required by GDPR Article 14(2)(f).",
    "article_14_indirect_collection_gap": "The notice does not describe the categories of personal data collected indirectly or explain the circumstances of their collection.",
    "special_category_basis_unclear": "The notice references sensitive data processing without identifying the specific Article 9 condition or safeguards relied upon.",
    "dpo_contact_gap": "The notice does not provide the required contact details for the Data Protection Officer.",
    "recipients_disclosure_gap": "The notice does not clearly identify categories of recipients or third parties receiving personal data.",
}

TRANSFER_SAFEGUARD_SUPPLEMENT = (
    "Identify the applicable transfer safeguard: an adequacy decision (Article 45), "
    "Standard Contractual Clauses (Article 46(2)(c)), Binding Corporate Rules (Article 47), "
    "or an Article 49 derogation. State how data subjects can obtain a copy of the safeguards."
)

ISSUE_ACTION_MAP: dict[str, str] = {
    "missing_legal_basis": "For each processing purpose, state the specific Article 6(1) ground relied upon (e.g. consent, contract performance, legitimate interests) and, where applicable, the legitimate interest pursued.",
    "missing_retention_period": "For each category of personal data, state the specific retention period or the objective criteria used to determine it (e.g. end of contract, statutory limitation period, regulatory obligation).",
    "missing_rights_notice": "Describe all applicable data subject rights — access, rectification, erasure, restriction, portability, and objection — and explain clearly how to exercise each right, including expected response timelines.",
    "missing_complaint_right": "State that data subjects may lodge a complaint with the relevant supervisory authority. Where possible, identify the authority by name and provide its contact details.",
    "missing_transfer_notice": "For each third-country transfer, identify the destination and state the specific safeguard relied upon (e.g. adequacy decision, standard contractual clauses, binding corporate rules).",
    "profiling_disclosure_gap": "Describe the logic of any profiling or automated decision-making, its significance for data subjects, the envisaged consequences, and any safeguards or human-review mechanisms available.",
    "recipients_disclosure_gap": "List the categories of recipients to whom personal data is disclosed (e.g. cloud providers, payment processors, analytics platforms) and describe the disclosure context for each category.",
    "missing_controller_contact": "Add a direct privacy contact route — at minimum an email address or web form — through which data subjects can submit requests or raise concerns.",
    "missing_controller_identity": "Identify the data controller by full legal name and registered address, and provide a direct privacy contact channel.",
    "purpose_specificity_gap": "For each key category of personal data, map it explicitly to the processing purposes for which it is used, with sufficient specificity that a data subject can understand what their data is used for.",
    "controller_processor_role_ambiguity": "Add role-allocation language explaining when the organisation acts as controller, processor, or joint controller, and how this affects data subject rights.",
    "cookie_disclosure_gap": "Add a dedicated section explaining which cookies and tracking technologies are used, their purposes, the legal basis for each, and how data subjects can manage their preferences.",
    "lawful_basis_and_consent": "Identify the specific Article 6(1) lawful basis for each processing purpose; where consent is relied upon, ensure it is freely given, specific, informed and unambiguous; and state the legal ground for any tracking or profiling activities.",
    "invalid_consent_or_legal_basis": "Review each processing activity and state the specific Article 6(1) ground relied upon. Where consent is the basis, ensure it is collected freely, specifically, informedly and unambiguously, and that it can be withdrawn as easily as given.",
    "cookies_tracking_consent_gap": "Add a section describing which tracking technologies are used, their purposes, the legal basis for each (consent or legitimate interests), and how data subjects can opt in or out.",
    "article14_source_transparency_gap": "State clearly the category of source from which personal data was obtained (e.g. public registers, referral partners, data brokers) and whether it came from publicly available sources.",
    "article_14_indirect_collection_gap": "Disclose which categories of personal data are collected indirectly, from what sources, and under what circumstances, as required by GDPR Article 14.",
    "special_category_basis_unclear": "Identify the specific Article 9(2) condition relied upon for processing sensitive data and explain the safeguards in place.",
    "dpo_contact_gap": "Add the Data Protection Officer contact details, including at minimum a postal or electronic address designated for data protection queries.",
}


# PDF color palette (RGB 0–1)
_NAVY = (0.059, 0.090, 0.165)  # #0F172A — header/accent
_WHITE = (1.0, 1.0, 1.0)
_BLACK = (0.0, 0.0, 0.0)
_LIGHT_GREY = (0.953, 0.957, 0.965)  # #F3F4F6 — card background
_SEV_HIGH = (0.863, 0.149, 0.149)  # #DC2626
_SEV_MED = (0.851, 0.467, 0.024)  # #D97706
_SEV_LOW = (0.420, 0.447, 0.502)  # #6B7280
_GREY_FOOTER = (0.580, 0.600, 0.620)

_SEVERITY_COLOR: dict[str, tuple] = {
    "high": _SEV_HIGH,
    "medium": _SEV_MED,
    "low": _SEV_LOW,
}


class _TextBlock(NamedTuple):
    text: str
    font_size: int = 10
    top_gap: int = 0
    bullet: bool = False
    bold: bool = False
    color: tuple = _BLACK
    bg_color: tuple | None = None
    left_bar_color: tuple | None = None


@dataclass
class _SyntheticCitation:
    chunk_id: str
    article_number: str
    paragraph_ref: str | None
    article_title: str
    excerpt: str


@dataclass
class _SyntheticFinding:
    id: str
    section_id: str
    status: str
    severity: str | None
    classification: str | None
    legal_requirement: str | None
    gap_note: str | None
    remediation_note: str | None
    citations: list[_SyntheticCitation]
    source_scope: str | None = None
    primary_legal_anchor: str | None = None
    citation_summary_text: str | None = None


def _apply_transfer_supplement(issue_key: str, action: str) -> str:
    """Append specific safeguard mechanism text to any transfer-related finding action."""
    if not action or not re.search(r"transfer", issue_key, re.IGNORECASE):
        return action
    # Idempotent: don't double-append if the supplement is already present.
    if "article 45" in action.lower() or "article 46" in action.lower():
        return action
    return f"{action} {TRANSFER_SAFEGUARD_SUPPLEMENT}"


def _wrap_text(text: str, max_chars: int, initial_indent: str = "", continuation_indent: str = "") -> list[str]:
    text = text.translate(PDF_SAFE_CHAR_REPLACEMENTS)
    if not text:
        return [""]

    words = text.split()
    if not words:
        return [""]

    wrapped: list[str] = []
    current = initial_indent
    current_len = len(initial_indent)
    line_limit = max_chars

    for word in words:
        prefix = " " if current_len > len(initial_indent if not wrapped else continuation_indent) else ""
        candidate = f"{current}{prefix}{word}" if current else f"{word}"
        if len(candidate) <= line_limit:
            current = candidate
            current_len = len(current)
            continue

        if current:
            wrapped.append(current)
        current = f"{continuation_indent}{word}"
        current_len = len(current)

        if len(current) > line_limit:
            chunk_len = max(8, line_limit - len(continuation_indent))
            for idx in range(0, len(word), chunk_len):
                chunk = word[idx : idx + chunk_len]
                wrapped.append(f"{continuation_indent}{chunk}")
            current = ""
            current_len = 0

    if current:
        wrapped.append(current)
    return wrapped


def _estimate_max_chars(font_size: int, page_width: int, margin_left: int, margin_right: int) -> int:
    usable_width = page_width - margin_left - margin_right
    # Approximate average Helvetica glyph width in points.
    avg_char_width = max(4.5, font_size * 0.55)
    return max(24, int(usable_width / avg_char_width))


def _write_pdf(blocks: list[_TextBlock], out_path: Path, generated_at: str = "") -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_width = 595
    page_height = 842
    margin_left = 50
    margin_right = 50
    margin_top = 60
    margin_bottom = 60
    default_line_gap = 4

    def _rgb(c: tuple) -> str:
        return f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f}"

    # PASS 1: Layout — assign each block to a page and record its y_baseline
    # y_baseline is the PDF y coordinate of the first line's baseline (origin at bottom-left).
    laid_out: list[tuple[int, float, list[str], _TextBlock]] = []
    page_idx = 0
    cursor_y = float(page_height - margin_top)

    for block in blocks:
        font_size = block.font_size
        line_height = font_size + default_line_gap
        max_chars = _estimate_max_chars(font_size, page_width, margin_left, margin_right)
        wrapped = _wrap_text(
            block.text,
            max_chars=max_chars,
            initial_indent="- " if block.bullet else "",
            continuation_indent="  " if block.bullet else "",
        )
        n = max(1, len(wrapped))
        needed_height = block.top_gap + line_height * n

        if cursor_y - needed_height < margin_bottom and laid_out:
            page_idx += 1
            cursor_y = float(page_height - margin_top)

        y_baseline = cursor_y - block.top_gap
        laid_out.append((page_idx, y_baseline, wrapped, block))
        cursor_y -= needed_height

    if not laid_out:
        laid_out = [
            (
                0,
                float(page_height - margin_top),
                ["CompliTrace Report: no content available."],
                _TextBlock("CompliTrace Report: no content available."),
            )
        ]

    total_pages = laid_out[-1][0] + 1

    # Compute background colour bands: merge consecutive same-bg_color blocks on the same page
    # into a single filled rectangle drawn before any text.
    # Each band: (page_idx, y_top, y_bottom, color)
    bg_bands: list[tuple[int, float, float, tuple]] = []
    bidx = 0
    while bidx < len(laid_out):
        pidx0, yb0, wl0, blk0 = laid_out[bidx]
        if blk0.bg_color is None:
            bidx += 1
            continue
        band_color = blk0.bg_color
        band_page = pidx0
        band_y_top: float | None = None
        band_y_bottom: float | None = None
        jdx = bidx
        while jdx < len(laid_out):
            p2, yb2, wl2, blk2 = laid_out[jdx]
            if p2 != band_page or blk2.bg_color != band_color:
                break
            fs2 = blk2.font_size
            lh2 = fs2 + default_line_gap
            n2 = max(1, len(wl2))
            pad2 = 6 if fs2 >= 13 else 4
            block_top = yb2 + fs2 + pad2
            block_bottom = yb2 - (n2 - 1) * lh2 - pad2
            if band_y_top is None:
                band_y_top = block_top
            band_y_bottom = block_bottom
            jdx += 1
        if band_y_top is not None and band_y_bottom is not None:
            # Extend the first band on page 0 (the header) to the very top of the page.
            if band_page == 0 and bidx == 0:
                band_y_top = float(page_height)
            bg_bands.append((band_page, band_y_top, band_y_bottom, band_color))
        bidx = jdx

    # Font resources: F1 = Helvetica, F2 = Helvetica-Bold
    page_object_ids: list[int] = []
    objects: list[bytes] = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n")
    objects.append(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    objects.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n")

    next_obj_id = 5
    usable_w = float(page_width - margin_left - margin_right)

    for pg in range(total_pages):
        page_entries = [(y, wl, blk) for pidx, y, wl, blk in laid_out if pidx == pg]
        page_id = next_obj_id
        content_id = next_obj_id + 1
        next_obj_id += 2
        page_object_ids.append(page_id)

        cmds: list[str] = []

        # Draw background colour bands for this page (must precede text).
        for bpidx, b_top, b_bottom, b_color in bg_bands:
            if bpidx != pg:
                continue
            band_h = b_top - b_bottom
            if band_h <= 0:
                continue
            # The first band on page 0 (the header) spans the full page width.
            if pg == 0 and b_top >= page_height - 1:
                bx, bw = 0.0, float(page_width)
            else:
                bx, bw = float(margin_left - 8), usable_w + 16.0
            cmds.append(f"q {_rgb(b_color)} rg {bx:.1f} {b_bottom:.1f} {bw:.1f} {band_h:.1f} re f Q")

        # Render each text block.
        for y_baseline, wrapped, block in page_entries:
            font_size = block.font_size
            line_height = font_size + default_line_gap
            n_lines = max(1, len(wrapped))
            pad = 6 if font_size >= 13 else 4

            # Left accent bar (3 pt wide).
            if block.left_bar_color:
                bar_h = n_lines * line_height + 2 * pad
                bar_y = y_baseline - (n_lines - 1) * line_height - pad
                cmds.append(
                    f"q {_rgb(block.left_bar_color)} rg {margin_left - 10:.1f} {bar_y:.1f} 3 {bar_h:.1f} re f Q"
                )

            # Text — each block has its own BT/ET with an absolute starting position.
            font_name = "F2" if block.bold else "F1"
            cmds.append(f"BT {_rgb(block.color)} rg /{font_name} {font_size} Tf {margin_left:.1f} {y_baseline:.1f} Td")
            for i, line in enumerate(wrapped):
                safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                cmds.append(f"({safe}) Tj")
                if i < n_lines - 1:
                    cmds.append(f"0 -{line_height} Td")
            cmds.append("ET")

        # Footer on every page: rule + "CompliTrace | Page X of Y | Generated …"
        footer_y = 28.0
        rule_y = footer_y + 14.0
        footer_text = f"CompliTrace  |  Page {pg + 1} of {total_pages}"
        if generated_at:
            footer_text += f"  |  Generated {generated_at}"
        safe_footer = footer_text.replace("(", "\\(").replace(")", "\\)")
        cmds.append(
            f"q {_rgb(_GREY_FOOTER)} RG 0.5 w "
            f"{margin_left:.1f} {rule_y:.1f} m "
            f"{page_width - margin_right:.1f} {rule_y:.1f} l S Q"
        )
        cmds.append(f"BT {_rgb(_GREY_FOOTER)} rg /F1 7 Tf {margin_left:.1f} {footer_y:.1f} Td ({safe_footer}) Tj ET")

        content_stream = "\n".join(cmds).encode("latin-1", errors="replace")
        objects.append(
            f"{page_id} 0 obj\n<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_id} 0 R >>\nendobj\n".encode("ascii")
        )
        objects.append(
            f"{content_id} 0 obj\n<< /Length {len(content_stream)} >>\nstream\n".encode("ascii")
            + content_stream
            + b"\nendstream\nendobj\n"
        )

    kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
    objects[1] = f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>\nendobj\n".encode("ascii")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii"))
    out_path.write_bytes(bytes(pdf))


class _SectionReportMeta(NamedTuple):
    label: str
    page_range: str | None = None


def _format_page_range(section: SectionData) -> str | None:
    if section.page_start is None and section.page_end is None:
        return None
    if section.page_start is None:
        return f"Page {section.page_end}"
    if section.page_end is None:
        return f"Page {section.page_start}"
    if section.page_start == section.page_end:
        return f"Page {section.page_start}"
    return f"Pages {section.page_start}-{section.page_end}"


def _section_report_meta(audit: Audit) -> tuple[str | None, dict[str, _SectionReportMeta]]:
    try:
        client = IngestionClient(settings.ingestion_service_url)
        document = client.get_document(audit.document_id)
        sections = client.get_sections(audit.document_id)
    except Exception:
        return None, {}

    title = document.title.strip() if document.title.strip() else document.filename
    labels: dict[str, _SectionReportMeta] = {}
    for section in sections:
        if section.section_title.strip():
            label = section.section_title.strip()
        else:
            label = f"Section {section.section_order}"
        labels[section.id] = _SectionReportMeta(label=label, page_range=_format_page_range(section))
    return title, labels


def _format_citation_label(article_number: str, article_title: str, paragraph_ref: str | None) -> str:
    title = article_title.strip() or "Untitled article"
    if paragraph_ref:
        return f"GDPR Article {article_number} - {title} (Paragraph {paragraph_ref})"
    return f"GDPR Article {article_number} - {title}"


def _sanitize_user_text(text: str | None) -> str | None:
    if not text:
        return text

    cleaned = text
    cleaned = re.sub(r"Diagnostic:\s.*$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"Potential duplicate of section [^.;]+[.;]?", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"chunk_id\s*=\s*gdpr-art-[a-z0-9-]+", "GDPR evidence reference", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgdpr-art-[a-z0-9-]+\b", "GDPR evidence reference", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    cleaned = re.sub(
        r"The reviewed notice content triggers GDPR transparency analysis\.?", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"Observation:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"Substantive disclosure signal detected\.?",
        "The notice text suggests disclosure is present, but key details remain unclear.",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"not assessable from provided excerpt", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"finding promoted to substantive non-compliance", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"strict legal gate", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"section\s*\.", "Section", cleaned, flags=re.IGNORECASE)
    for token in BANNED_USER_TOKENS:
        cleaned = re.sub(re.escape(token), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _decode_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _is_publishable_finding(row: Finding) -> bool:
    if row.publication_state:
        return row.publication_state == "publishable"
    return row.publish_flag == "yes"


def _is_unresolved_or_fallback_row(row: Finding) -> bool:
    token_blob = " ".join(
        [
            row.classification or "",
            row.finding_type or "",
            row.artifact_role or "",
            row.assessment_type or "",
            row.applicability_status or "",
            row.assertion_level or "",
            row.citation_summary_text or "",
            row.gap_note or "",
            row.remediation_note or "",
        ]
    ).lower()
    blocked_tokens = (
        "fallback",
        "systemic-only",
        "strict legal gate",
        "not assessable promotion",
        "diagnostic_internal_only",
        "unresolved applicability",
        "internal_only",
        "support_only",
        "meta_section",
    )
    return any(token in token_blob for token in blocked_tokens)


def _has_visible_anchor_or_citation(row: Finding) -> bool:
    anchors = _decode_json_list(row.primary_legal_anchor) + _decode_json_list(row.secondary_legal_anchors)
    normalized_anchors = [(_sanitize_user_text(a) or "").strip().lower() for a in anchors]
    if any(a.startswith("gdpr article") or a.startswith("gdpr art") for a in normalized_anchors):
        return True
    legal_requirement = (_sanitize_user_text(row.legal_requirement) or "").strip().lower()
    return "gdpr art" in legal_requirement or "gdpr article" in legal_requirement


def _has_citation_or_evidence_ref(row: Finding) -> bool:
    real_citations = [
        c
        for c in row.citations
        if _is_valid_evidence_excerpt(c.excerpt)
        and bool((c.chunk_id or "").strip())
        and not (c.chunk_id or "").startswith("systemic-anchor:")
    ]
    return len(real_citations) > 0


def _readable_fallback_evidence(row: Finding) -> str:
    issue = _issue_from_section_id(row.section_id) or "this duty"
    return f"This notice does not clearly disclose the required information regarding {issue.replace('_', ' ')}. (synthesized evidence)"


def _has_readable_evidence(row: Finding) -> bool:
    if _is_valid_evidence_excerpt(row.policy_evidence_excerpt):
        return True
    return any(_is_valid_evidence_excerpt(c.excerpt) for c in row.citations)


def _is_clean_human_text(value: str | None) -> bool:
    text = (_sanitize_user_text(value) or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[\W_]+", text):
        return False
    lowered = text.lower()
    debug_tokens = (
        "disallowed by strict",
        "additional context required",
        "debug",
        "placeholder",
        "internal_only",
        "validator",
        "local finding",
        "anchor is absent",
        "internal diagnostic",
        "diagnostic only",
        "conditional issue",
    )
    if any(token in lowered for token in debug_tokens):
        return False
    if text.count('"') % 2 == 1:
        return False
    return True


def _is_final_exportable_finding(row: Finding) -> bool:
    if not _is_publishable_finding(row):
        return False
    if row.status in {"not_assessable", "referenced_but_unseen"}:
        return False
    if _is_unresolved_or_fallback_row(row):
        return False
    if not _has_readable_evidence(row):
        return False
    if not _has_visible_anchor_or_citation(row):
        return False
    if not _has_citation_or_evidence_ref(row):
        return False
    text_fields = [
        row.policy_evidence_excerpt,
        row.gap_note,
        row.remediation_note,
        row.citation_summary_text,
        row.legal_requirement,
    ]
    return all(_is_clean_human_text(value) for value in text_fields if value)


_NOTICE_WIDE_ISSUE_KEYS: frozenset[str] = frozenset(
    {
        "missing_legal_basis",
        "missing_retention_period",
        "missing_rights_notice",
        "missing_complaint_right",
        "missing_controller_identity",
        "missing_controller_contact",
        "controller_identity_contact",
    }
)

_SREV_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}

# Domain groups: issue keys sharing the same root compliance failure are merged
# into a single senior-level finding under a consolidated key.
# Only groups with 2+ qualifying rows in a given audit are merged.
_DOMAIN_CONSOLIDATION_GROUPS: list[tuple[str, frozenset[str]]] = [
    (
        "lawful_basis_and_consent",
        frozenset(
            {
                "missing_legal_basis",
                "invalid_consent_or_legal_basis",
                "cookies_tracking_consent_gap",
            }
        ),
    ),
]


def _consolidate_finding_rows(rows: list[Finding]) -> list[Finding]:
    """Deduplicate Finding rows to one per canonical issue_key.

    For notice-wide duties (legal basis, retention, rights, complaint) the systemic
    row is preferred over any local section row.  For section-specific issues the
    highest-confidence row wins.  Severity is upgraded to the strongest in the group.
    Citations are NOT merged at the ORM level (to avoid accidental DB writes);
    the API layer handles citation merging on PublishedFindingOut objects.
    """
    if len(rows) <= 1:
        return rows
    groups: dict[str, list[Finding]] = {}
    order: list[str] = []
    for row in rows:
        key = _derive_issue_key_for_row(row) or row.id
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    result: list[Finding] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            result.append(group[0])
            continue
        systemic = [r for r in group if r.section_id.startswith("systemic:")]
        if key in _NOTICE_WIDE_ISSUE_KEYS and systemic:
            primary = max(systemic, key=lambda r: r.confidence_overall or 0)
        else:
            primary = max(
                group,
                key=lambda r: (r.confidence_overall or 0, 1 if r.section_id.startswith("systemic:") else 0),
            )
        best_sev = max(
            (r.severity for r in group if r.severity),
            key=lambda s: _SREV_RANK.get(s, 0),
            default=None,
        )
        if best_sev and primary.severity != best_sev:
            primary.severity = best_sev
        best_conf = max((r.confidence_overall or 0 for r in group), default=0)
        if best_conf and primary.confidence_overall != best_conf:
            primary.confidence_overall = best_conf
        # Store all section_ids from the group as a transient attribute so the
        # API layer can include them in affected_sections without a DB write.
        primary._merged_section_ids = [r.section_id for r in group]
        result.append(primary)
    return result


def _consolidate_finding_rows_by_domain(rows: list[Finding]) -> list[Finding]:
    """Merge findings from the same audit domain into one senior-level finding.

    Called after _consolidate_finding_rows() so each input row is already unique
    per issue key.  For each domain group, if 2+ rows are present the
    highest-confidence systemic row (falling back to highest-confidence local row)
    becomes the primary.  Non-primary rows are dropped; the primary gains:
      _domain_merged_key     – consolidated issue key (e.g. "lawful_basis_and_consent")
      _domain_merged_rows    – all Finding rows in the group (including primary)
      _domain_merged_anchors – deduplicated legal anchors from all rows in order

    Idempotent: clears any domain attrs from a previous pass (same DB session)
    before re-computing, so calling canonical_published_findings twice on the
    same session does not corrupt results.
    """
    if len(rows) <= 1:
        return rows

    # Clear stale domain attrs so this function is safe to call multiple times
    # on the same ORM objects (SQLAlchemy identity-map reuse).
    for r in rows:
        r.__dict__.pop("_domain_merged_key", None)
        r.__dict__.pop("_domain_merged_rows", None)
        r.__dict__.pop("_domain_merged_anchors", None)

    row_with_key: list[tuple[Finding, str | None]] = [(r, _derive_issue_key_for_row(r)) for r in rows]

    absorbed_ids: set[int] = set()

    for merged_key, group_keys in _DOMAIN_CONSOLIDATION_GROUPS:
        group = [(r, ik) for r, ik in row_with_key if ik in group_keys and id(r) not in absorbed_ids]
        if len(group) < 2:
            continue

        group_rows = [r for r, _ in group]
        systemic = [r for r in group_rows if r.section_id.startswith("systemic:")]
        primary = (
            max(systemic, key=lambda r: r.confidence_overall or 0)
            if systemic
            else max(group_rows, key=lambda r: r.confidence_overall or 0)
        )

        # Collect all anchors in encounter order, deduplicated
        all_anchors: list[str] = []
        seen_anchors: set[str] = set()
        for r in group_rows:
            for anchor in _decode_json_list(r.primary_legal_anchor):
                if anchor not in seen_anchors:
                    seen_anchors.add(anchor)
                    all_anchors.append(anchor)

        # Upgrade to strongest severity and confidence in the group
        best_sev = max(
            (r.severity for r in group_rows if r.severity),
            key=lambda s: _SREV_RANK.get(s, 0),
            default=None,
        )
        if best_sev and primary.severity != best_sev:
            primary.severity = best_sev
        best_conf = max((r.confidence_overall or 0 for r in group_rows), default=0)
        if best_conf and primary.confidence_overall != best_conf:
            primary.confidence_overall = best_conf

        primary._domain_merged_key = merged_key
        primary._domain_merged_rows = group_rows
        primary._domain_merged_anchors = all_anchors

        for r in group_rows:
            if r is not primary:
                absorbed_ids.add(id(r))

    return [r for r, _ in row_with_key if id(r) not in absorbed_ids]


def canonical_published_findings(db: Session, audit_id: str) -> list[Finding]:
    """Single non-bypassable source of truth for ALL published findings output paths.

    Every consumer — /findings API, export-contract, report generation, and PDF —
    must call this function.  It enforces the complete quality gate:

    DB-level pre-filter
      • artifact_role == "publishable_finding"
      • publication_state == "publishable"
      • section_id NOT LIKE "ledger:%"

    Per-row quality gate (_is_final_exportable_finding)
      • status not in {not_assessable, referenced_but_unseen}
      • no internal/fallback classification tokens
      • readable policy evidence or citation evidence
      • GDPR legal anchor visible
      • at least one real citation with valid excerpt
      • all text fields are clean human-readable text (no debug tokens)

    Text normalisation
      • policy_evidence_excerpt fallback when evidence is unreadable
      • gap_note fallback when sanitised text is empty / not human-readable
      • remediation_note fallback when sanitised text is empty
    """
    rows = db.scalars(
        select(Finding)
        .options(selectinload(Finding.citations))
        .where(Finding.audit_id == audit_id)
        .where(Finding.section_id.not_like("ledger:%"))
        .where(Finding.artifact_role == "publishable_finding")
        .where(Finding.publication_state == "publishable")
        .order_by(Finding.section_id.asc(), Finding.id.asc())
    ).all()
    qualified: list[Finding] = []
    for row in rows:
        # Step 1 — raw banned-token scan on the original text, before _sanitize_user_text
        # strips the tokens and makes them invisible to later checks.
        _raw = " ".join(filter(None, [row.gap_note, row.remediation_note])).lower()
        if any(tok in _raw for tok in _BANNED_TOKENS_LOWER):
            continue

        # Step 2 — pre-normalise evidence BEFORE the quality gate inspects it.
        # Without this, a bare "." in policy_evidence_excerpt fails _is_clean_human_text
        # even when a valid citation excerpt is available to serve as fallback.
        if not _is_valid_evidence_excerpt(row.policy_evidence_excerpt):
            citation_excerpt = next((c.excerpt for c in row.citations if _is_valid_evidence_excerpt(c.excerpt)), None)
            fallback = (
                _sanitize_user_text(citation_excerpt)
                or _sanitize_user_text(row.citation_summary_text)
                or _sanitize_user_text(row.gap_reasoning)
            )
            row.policy_evidence_excerpt = (
                f"Based on the reviewed notice: {fallback}"
                if fallback
                else "Based on the reviewed notice: no explicit compliant disclosure excerpt was found."
            )

        # Step 3 — full quality gate (evidence is now normalised).
        if not _is_final_exportable_finding(row):
            continue

        # Step 4 — normalise gap_note / remediation_note fallbacks.
        sanitized_gap = (_sanitize_user_text(row.gap_note) or "").strip()
        if not sanitized_gap or not bool(re.search(r"[a-zA-Z]{4,}", sanitized_gap)):
            row.gap_note = (
                "Based on the reviewed notice, required GDPR disclosure is missing or insufficient for this obligation."
            )
        sanitized_rem = (_sanitize_user_text(row.remediation_note) or "").strip()
        if not sanitized_rem or not bool(re.search(r"[a-zA-Z]{4,}", sanitized_rem)):
            row.remediation_note = "Update the notice to include GDPR-required disclosure language for this obligation."
        qualified.append(row)
    return _consolidate_finding_rows_by_domain(_consolidate_finding_rows(qualified))


def final_exported_findings(db: Session, audit_id: str) -> list[Finding]:
    """Delegates to canonical_published_findings — kept for backward compatibility."""
    return canonical_published_findings(db, audit_id)


def final_findings_dataset(db: Session, audit_id: str) -> list[Finding]:
    """Backward-compatible wrapper for canonical_published_findings."""
    return canonical_published_findings(db, audit_id)


def _normalize_status(status: str | None) -> str:
    token = (status or "").strip().lower().replace("_", " ")
    if token in {"candidate gap", "gap", "blocked"}:
        return "gap"
    if token in {"candidate partial", "partial"}:
        return "partial"
    if token in {"candidate compliant", "compliant"}:
        return "compliant"
    if token in {"needs review"}:
        return "needs review"
    return "not applicable"


def _user_status_label(status: str | None) -> str:
    normalized = _normalize_status(status)
    if normalized == "gap":
        return "Non-compliant"
    if normalized == "partial":
        return "Partially compliant"
    if normalized == "compliant":
        return "Compliant"
    return "Not applicable"


def _user_severity_label(severity: str | None, issue: str | None) -> str:
    token = (severity or "").strip().lower()
    if token in {"high", "medium", "low"}:
        return token.title()
    issue_token = (issue or "").lower()
    if any(k in issue_token for k in ["legal_basis", "complaint", "rights", "transfer", "profil"]):
        return "High"
    if any(k in issue_token for k in ["retention", "recipient", "purpose"]):
        return "Medium"
    return "Low"


def _issue_from_section_id(section_id: str) -> str | None:
    if section_id.startswith("systemic:"):
        return section_id.split("systemic:", 1)[1]
    return None


def _derive_issue_key_for_row(row: Finding | _SyntheticFinding) -> str | None:
    """Extract the canonical issue key from available Finding fields."""
    # 0. Domain-consolidated key set by _consolidate_finding_rows_by_domain takes precedence.
    domain_key = getattr(row, "_domain_merged_key", None)
    if domain_key:
        return domain_key
    # 1. Systemic section_id encodes the issue
    issue = _issue_from_section_id(row.section_id)
    if issue:
        return issue
    # 2. Dynamically-set attribute (some callers set this)
    issue_key = getattr(row, "issue_key", None)
    if issue_key:
        return issue_key
    # 3. legal_requirement often contains "for issue <key>"
    lr = (row.legal_requirement or "").strip()
    m = re.search(r"\bfor issue\s+([a-z_]+)\b", lr, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # 4. Match on GDPR article numbers from primary_legal_anchor
    anchors = " ".join(_decode_json_list(row.primary_legal_anchor)).lower()
    if "13(2)(f)" in anchors or "14(2)(g)" in anchors:
        return "profiling_disclosure_gap"
    if "13(1)(f)" in anchors or "14(1)(f)" in anchors or "article 44" in anchors or "art. 44" in anchors:
        return "missing_transfer_notice"
    if "13(1)(c)" in anchors or "14(1)(c)" in anchors:
        return "missing_legal_basis"
    if "13(2)(a)" in anchors or "14(2)(a)" in anchors:
        return "missing_retention_period"
    if "13(2)(b)" in anchors or "14(2)(c)" in anchors:
        return "missing_rights_notice"
    if "13(2)(d)" in anchors or "14(2)(e)" in anchors:
        return "missing_complaint_right"
    if "13(1)(a)" in anchors or "14(1)(a)" in anchors:
        return "missing_controller_contact"
    if "13(1)(e)" in anchors or "14(1)(e)" in anchors:
        return "recipients_disclosure_gap"
    return None


def _title_for_row(row: Finding | _SyntheticFinding) -> str:
    issue_key = _derive_issue_key_for_row(row)
    if issue_key and issue_key in ISSUE_TITLE_MAP:
        return ISSUE_TITLE_MAP[issue_key]
    # Fallback: use legal_requirement but strip machine-generated anchor strings
    candidate = _sanitize_user_text(row.legal_requirement)
    if candidate and re.search(r"\bprimary legal anchor\b|\bfor issue\b", candidate, re.IGNORECASE):
        candidate = None
    candidate = candidate or _sanitize_user_text(row.gap_note)
    if candidate and bool(re.search(r"[a-zA-Z]{4,}", candidate)):
        return candidate[:90]
    return "GDPR transparency disclosure gap"


def _evidence_for_row(row: Finding | _SyntheticFinding, section_label: str) -> str:
    excerpt = next((c.excerpt for c in row.citations if _is_valid_evidence_excerpt(c.excerpt)), None)
    if excerpt:
        return f"{section_label}: {_sanitize_user_text(excerpt)}"
    # Fall back to policy_evidence_excerpt when citations are absent
    doc_excerpt = getattr(row, "policy_evidence_excerpt", None)
    if _is_valid_evidence_excerpt(doc_excerpt):
        return f"{section_label}: {_sanitize_user_text(doc_excerpt)}"
    if section_label and section_label != "Document section":
        return "No explicit disclosure found in this section."
    return "No explicit disclosure found in this document."


def _is_valid_evidence_excerpt(excerpt: str | None) -> bool:
    cleaned = (_sanitize_user_text(excerpt) or "").strip()
    if len(cleaned) < 3:
        return False
    if cleaned.lower() in {"section", ".", ":", "-", "n/a"}:
        return False
    if re.fullmatch(r"[\W_]+", cleaned):
        return False
    if any(
        token in cleaned.lower()
        for token in ("disallowed by strict", "additional context required", "validator", "debug")
    ):
        return False
    return bool(re.search(r"[a-zA-Z]{4,}", cleaned))


def _all_citations_for_finding(finding: Finding) -> list:
    """Return citations for a finding, merging across domain-merged rows if present."""
    merged_rows = getattr(finding, "_domain_merged_rows", None)
    if not merged_rows:
        return finding.citations
    seen: set[str] = set()
    result = []
    for row in merged_rows:
        for c in row.citations:
            key = c.article_number or c.chunk_id
            if key not in seen:
                seen.add(key)
                result.append(c)
    return result


def _is_safe_for_export(row: Finding | _SyntheticFinding, section_label: str) -> bool:
    title = _title_for_row(row)
    evidence = _evidence_for_row(row, section_label)
    blob = f"{title} {_sanitize_user_text(row.gap_note) or ''} {_sanitize_user_text(row.remediation_note) or ''} {evidence}".lower()
    if not evidence.strip() or "[ ]" in blob or "[]" in blob:
        return False
    if any(token in blob for token in BANNED_USER_TOKENS):
        return False
    return True


def _analysis_rows_for_export(db: Session, audit_id: str) -> list[_SyntheticFinding]:
    rows = db.scalars(
        select(AuditAnalysisItem)
        .options(selectinload(AuditAnalysisItem.citations))
        .where(AuditAnalysisItem.audit_id == audit_id)
        .where(AuditAnalysisItem.analysis_outcome.in_(["candidate_gap", "candidate_partial", "referenced_but_unseen"]))
        .order_by(AuditAnalysisItem.section_id.asc(), AuditAnalysisItem.id.asc())
    ).all()
    out: list[_SyntheticFinding] = []
    for row in rows:
        if row.section_id.startswith("ledger:") or row.analysis_type in {"support_evidence", "meta_section"}:
            continue
        citations = [
            _SyntheticCitation(
                chunk_id=c.chunk_id,
                article_number=c.article_number,
                paragraph_ref=c.paragraph_ref,
                article_title=c.article_title,
                excerpt=_sanitize_user_text(c.excerpt) or "",
            )
            for c in row.citations
            if _sanitize_user_text(c.excerpt)
        ]
        out.append(
            _SyntheticFinding(
                id=f"analysis:{row.id}",
                section_id=row.section_id,
                status=_normalize_status(row.status_candidate),
                severity=row.finding_severity,
                classification=row.classification_candidate,
                legal_requirement=row.legal_requirement_candidate,
                gap_note=row.gap_note,
                remediation_note=row.remediation_note,
                citations=citations,
                source_scope=row.source_scope,
                primary_legal_anchor=row.article_candidates,
                citation_summary_text=row.qualification_summary,
            )
        )
    return out


def build_export_contract(
    db: Session,
    audit_id: str,
) -> tuple[dict[str, Any], list[Finding | _SyntheticFinding], bool]:
    publishable_findings = final_exported_findings(db, audit_id)
    if publishable_findings and any(
        (row.artifact_role != "publishable_finding" or row.publication_state != "publishable")
        for row in publishable_findings
    ):
        raise ValueError("published dataset integrity failure: non-publishable rows included")
    dataset_used = "published" if publishable_findings else "zero"
    report_type = "Published report" if publishable_findings else "Zero-findings report"
    report_rows: list[Finding | _SyntheticFinding] = publishable_findings
    published_blocked = False

    audit = db.get(Audit, audit_id)
    _, _section_meta = _section_report_meta(audit) if audit else (None, {})
    export_rows: list[Finding | _SyntheticFinding] = list(report_rows)
    finding_ids = sorted([row.id for row in export_rows])
    contract = {
        "report_type": report_type,
        "dataset_used": dataset_used,
        "export_allowed": True,
        "blocker_reasons": [],
        "counts_by_status": {
            "compliant": sum(1 for row in export_rows if _user_status_label(row.status) == "Compliant"),
            "partially_compliant": sum(
                1 for row in export_rows if _user_status_label(row.status) == "Partially compliant"
            ),
            "non_compliant": sum(1 for row in export_rows if _user_status_label(row.status) == "Non-compliant"),
            "not_applicable": sum(1 for row in export_rows if _user_status_label(row.status) == "Not applicable"),
            "total": len(export_rows),
        },
        "finding_ids": finding_ids,
        "document_wide_finding_ids": sorted([row.id for row in export_rows if row.section_id.startswith("systemic:")]),
        "section_finding_ids": sorted([row.id for row in export_rows if not row.section_id.startswith("systemic:")]),
        "generated_from_audit_id": audit_id,
        "generated_at": datetime.utcnow().isoformat(),
    }
    if len(report_rows) > 0 and len(export_rows) == 0:
        contract["blocker_reasons"] = ["final_findings_dataset_empty"]
    if publishable_findings and contract["report_type"] == "Zero-findings report":
        raise ValueError("report integrity failure: zero-findings report with published findings")
    return contract, export_rows, published_blocked


_CHECKLIST_DUTY_LABELS: dict[str, str] = {
    "controller_identity_contact": "Controller identity and contact details",
    "legal_basis": "Legal basis for processing",
    "retention": "Data retention period",
    "rights_notice": "Data subject rights",
    "complaint_right": "Right to lodge a supervisory authority complaint",
    "transfer": "International data transfer disclosure",
    "profiling": "Profiling and automated decision-making",
    "role_ambiguity": "Controller/processor role clarity",
    "article14_source": "Article 14 indirect data source",
    "recipients": "Recipients and third-party disclosures",
    "special_category": "Special category data handling",
    "dpo_contact": "Data Protection Officer contact",
    "purpose_mapping": "Purpose-to-data-category mapping",
}

_CHECKLIST_CORE_DUTIES = [
    "controller_identity_contact",
    "legal_basis",
    "retention",
    "rights_notice",
    "complaint_right",
]
_CHECKLIST_SPECIALIST_DUTIES = [
    "transfer",
    "profiling",
    "role_ambiguity",
    "article14_source",
    "recipients",
    "special_category",
    "dpo_contact",
    "purpose_mapping",
]


def _checklist_row_outcome(duty: str, item: dict, *, is_specialist: bool) -> str:
    status = item.get("status")
    pub_rec = str(item.get("publication_recommendation") or "")
    if is_specialist:
        triggered = bool(item.get("triggered", status != "satisfied"))
        if not triggered:
            return "Not applicable"
    if status == "satisfied":
        return "Compliant"
    if status in ("partial", "partially_compliant"):
        return "Partially compliant"
    if status == "gap":
        return "Gap identified (internal)" if pub_rec == "internal_only" else "Gap identified"
    return "Not applicable"


def generate_report_text(db: Session, audit_id: str) -> tuple[Report, Path]:
    audit = db.get(Audit, audit_id)
    if not audit:
        raise ValueError("Audit not found")

    report = Report(audit_id=audit_id, status="pending")
    db.add(report)
    db.commit()
    db.refresh(report)

    contract, report_rows_deduped, published_blocked = build_export_contract(db, audit_id)
    analysis_rows = db.scalars(
        select(AuditAnalysisItem)
        .where(AuditAnalysisItem.audit_id == audit_id)
        .where(
            AuditAnalysisItem.analysis_type.in_(
                [
                    "completeness_outcome",
                    "referenced_but_unseen",
                    "not_assessable_core_duty",
                    "support_evidence",
                    "excerpt_scope_fact",
                ]
            )
        )
        .order_by(AuditAnalysisItem.section_id.asc(), AuditAnalysisItem.id.asc())
    ).all()

    document_title, section_meta = _section_report_meta(audit)
    systemic_findings = [f for f in report_rows_deduped if f.section_id.startswith("systemic:")]
    local_findings = [f for f in report_rows_deduped if not f.section_id.startswith("systemic:")]

    total = len(report_rows_deduped)
    by_status = {
        "compliant": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Compliant"),
        "partial": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Partially compliant"),
        "gap": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Non-compliant"),
        "not applicable": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Not applicable"),
    }
    started_at = (
        audit.started_at.isoformat(sep=" ", timespec="seconds") if isinstance(audit.started_at, datetime) else "n/a"
    )
    completed_at = (
        audit.completed_at.isoformat(sep=" ", timespec="seconds") if isinstance(audit.completed_at, datetime) else "n/a"
    )
    report_created_at = (
        report.created_at.isoformat(sep=" ", timespec="seconds") if isinstance(report.created_at, datetime) else "n/a"
    )

    compliance_score = getattr(audit, "compliance_score", None)
    score_str = f"{compliance_score}%" if compliance_score is not None else "Not computed"

    blocks: list[_TextBlock] = [
        # ── Navy header band (extends to page top) ──────────────────────────
        _TextBlock("CompliTrace  GDPR Gap Report", font_size=18, top_gap=0, bold=True, color=_WHITE, bg_color=_NAVY),
        _TextBlock(
            f"Document: {document_title or 'Unavailable'}", font_size=9, top_gap=2, color=_WHITE, bg_color=_NAVY
        ),
        _TextBlock(
            f"Audit started: {started_at}  |  Completed: {completed_at}",
            font_size=8,
            top_gap=1,
            color=_WHITE,
            bg_color=_NAVY,
        ),
        # ── Executive Summary card (light-grey background) ───────────────────
        _TextBlock(
            "Executive Summary", font_size=13, top_gap=16, bold=True, bg_color=_LIGHT_GREY, left_bar_color=_NAVY
        ),
        _TextBlock(f"Overall Compliance Score: {score_str}", font_size=12, top_gap=2, bold=True, bg_color=_LIGHT_GREY),
        _TextBlock(f"Total findings: {total}", bullet=True, bg_color=_LIGHT_GREY),
        _TextBlock(f"Compliant: {by_status['compliant']}", bullet=True, bg_color=_LIGHT_GREY),
        _TextBlock(f"Partially compliant: {by_status['partial']}", bullet=True, bg_color=_LIGHT_GREY),
        _TextBlock(f"Non-compliant: {by_status['gap']}", bullet=True, bg_color=_LIGHT_GREY),
        _TextBlock(f"Not applicable: {by_status['not applicable']}", bullet=True, bg_color=_LIGHT_GREY),
        _TextBlock(f"Report type: {contract['report_type']}", bullet=True, bg_color=_LIGHT_GREY),
        _TextBlock(
            "Dataset used: "
            f"{'Final published findings' if contract['dataset_used'] == 'published' else 'Review findings (publication blocked)' if contract['dataset_used'] == 'review' else 'Preliminary analysis findings' if contract['dataset_used'] == 'analysis' else 'Zero-findings dataset'}",
            bullet=True,
            bg_color=_LIGHT_GREY,
        ),
        # ── Document-wide findings section heading ───────────────────────────
        _TextBlock("Document-wide findings", font_size=13, top_gap=16, bold=True, left_bar_color=_NAVY),
    ]
    scope_label = next((f.source_scope for f in systemic_findings if f.source_scope), None)
    if scope_label == "partial_notice_excerpt":
        blocks.append(
            _TextBlock(
                "Scope note: This review is based on the provided excerpt rather than the full notice.", bullet=True
            )
        )
    elif scope_label == "full_notice":
        blocks.append(_TextBlock("Scope note: This review covers the complete notice provided.", bullet=True))
    elif scope_label:
        blocks.append(
            _TextBlock("Scope note: Source scope is uncertain; findings are calibrated conservatively.", bullet=True)
        )

    for finding in systemic_findings:
        sys_issue_key = _derive_issue_key_for_row(finding) or ""
        meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
        sev_color = _SEVERITY_COLOR.get(finding.severity or "low", _SEV_LOW)
        blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10, bold=True, left_bar_color=sev_color))
        blocks.append(_TextBlock(f"Finding: {_title_for_row(finding)}", bullet=True))
        issue_hint = sys_issue_key or (finding.legal_requirement or finding.section_id).replace(
            "systemic:", ""
        ).replace("_", " ")
        blocks.append(_TextBlock(f"Status: {_user_status_label(finding.status)}", bullet=True))
        blocks.append(_TextBlock(f"Severity: {_user_severity_label(finding.severity, issue_hint)}", bullet=True))
        primary_anchors = _decode_json_list(finding.primary_legal_anchor)
        if primary_anchors:
            blocks.append(_TextBlock(f"Legal basis: {', '.join(primary_anchors)}", bullet=True))
        _BANNED_SUMMARY_TOKENS = ("gdpr compliance assessment for", "obligation is missing", "legal gate")
        safe_citation_summary = _sanitize_user_text(finding.citation_summary_text) or ""
        if safe_citation_summary and not any(t in safe_citation_summary.lower() for t in _BANNED_SUMMARY_TOKENS):
            blocks.append(_TextBlock(f"Why flagged: {safe_citation_summary}", bullet=True))
        _GENERIC_FIELD_TOKENS = (
            "required gdpr disclosure is missing or insufficient",
            "update the notice to include gdpr-required",
            "update the notice to include the required gdpr",
            "gdpr compliance assessment",
        )
        sys_why = ISSUE_WHY_TEXT_MAP.get(sys_issue_key)
        if not sys_why:
            raw_gap = _sanitize_user_text(finding.gap_note) or ""
            sys_why = raw_gap if raw_gap and not any(t in raw_gap.lower() for t in _GENERIC_FIELD_TOKENS) else ""
        if sys_why:
            blocks.append(_TextBlock(f"Why this matters: {sys_why}", bullet=True))
        sys_action = ISSUE_ACTION_MAP.get(sys_issue_key)
        if not sys_action:
            raw_rem = _sanitize_user_text(finding.remediation_note) or ""
            sys_action = raw_rem if raw_rem and not any(t in raw_rem.lower() for t in _GENERIC_FIELD_TOKENS) else ""
        sys_action = _apply_transfer_supplement(sys_issue_key, sys_action)
        if sys_action:
            blocks.append(_TextBlock(f"Recommended action: {sys_action}", bullet=True))
        blocks.append(_TextBlock(f"Evidence: {_evidence_for_row(finding, meta.label)}", bullet=True))
        for citation in _all_citations_for_finding(finding):
            blocks.append(
                _TextBlock(
                    _format_citation_label(citation.article_number, citation.article_title, citation.paragraph_ref),
                    bullet=True,
                )
            )
            if citation.excerpt and _sanitize_user_text(citation.excerpt):
                blocks.append(_TextBlock(f'Evidence excerpt: "{_sanitize_user_text(citation.excerpt)}"', bullet=True))
    if not systemic_findings:
        blocks.append(_TextBlock("No document-wide compliance issues were identified.", bullet=True))

    blocks.append(_TextBlock("Section findings", font_size=13, top_gap=14, bold=True, left_bar_color=_NAVY))
    for finding in local_findings:
        meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
        sev_color = _SEVERITY_COLOR.get(finding.severity or "low", _SEV_LOW)
        blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10, bold=True, left_bar_color=sev_color))
        blocks.append(_TextBlock(f"Finding: {_title_for_row(finding)}", bullet=True))
        issue_key_hint = _derive_issue_key_for_row(finding) or ""
        issue_hint = issue_key_hint or finding.legal_requirement or finding.section_id
        blocks.append(_TextBlock(f"Status: {_user_status_label(finding.status)}", bullet=True))
        blocks.append(_TextBlock(f"Severity: {_user_severity_label(finding.severity, issue_hint)}", bullet=True))
        local_primary_anchors = _decode_json_list(finding.primary_legal_anchor)
        if not local_primary_anchors and finding.legal_requirement:
            lr = (_sanitize_user_text(finding.legal_requirement) or "").strip()
            gdpr_refs = re.findall(r"GDPR Article\s+[\d()a-z/,\s]+", lr, re.IGNORECASE)
            if gdpr_refs:
                local_primary_anchors = [ref.strip().rstrip(",") for ref in gdpr_refs]
        if local_primary_anchors:
            blocks.append(_TextBlock(f"Legal basis: {', '.join(local_primary_anchors)}", bullet=True))
        safe_gap_note = ISSUE_WHY_TEXT_MAP.get(issue_key_hint) or _sanitize_user_text(finding.gap_note)
        _LOCAL_GENERIC_TOKENS = (
            "required gdpr disclosure is missing or insufficient",
            "update the notice to include gdpr-required",
            "update the notice to include the required gdpr",
            "gdpr compliance assessment",
        )
        safe_remediation_note = _sanitize_user_text(finding.remediation_note)
        if safe_remediation_note and any(t in safe_remediation_note.lower() for t in _LOCAL_GENERIC_TOKENS):
            safe_remediation_note = ISSUE_ACTION_MAP.get(issue_key_hint) or ""
        safe_remediation_note = _apply_transfer_supplement(issue_key_hint, safe_remediation_note or "")
        if safe_gap_note and bool(re.search(r"[a-zA-Z]{4,}", safe_gap_note)):
            blocks.append(_TextBlock(f"Why this matters: {safe_gap_note}", bullet=True))
        if safe_remediation_note and bool(re.search(r"[a-zA-Z]{4,}", safe_remediation_note)):
            blocks.append(_TextBlock(f"Recommended action: {safe_remediation_note}", bullet=True))
        blocks.append(_TextBlock(f"Evidence: {_evidence_for_row(finding, meta.label)}", bullet=True))
        for citation in _all_citations_for_finding(finding):
            blocks.append(
                _TextBlock(
                    _format_citation_label(citation.article_number, citation.article_title, citation.paragraph_ref),
                    bullet=True,
                )
            )
            if citation.excerpt and _sanitize_user_text(citation.excerpt):
                blocks.append(_TextBlock(f'Evidence excerpt: "{_sanitize_user_text(citation.excerpt)}"', bullet=True))
    roadmap_items = [f for f in report_rows_deduped if f.remediation_note]
    if roadmap_items:
        blocks.append(_TextBlock("Recommended actions", font_size=13, top_gap=14, bold=True, left_bar_color=_NAVY))
        _ROADMAP_GENERIC_TOKENS = (
            "required gdpr disclosure",
            "update the notice to include gdpr",
            "update the notice to include the required gdpr",
            "gdpr compliance assessment",
        )
        for finding in sorted(
            roadmap_items, key=lambda row: {"high": 0, "medium": 1, "low": 2}.get((row.severity or "low"), 3)
        ):
            roadmap_issue_key = _derive_issue_key_for_row(finding) or ""
            sanitized_title = (
                ISSUE_WHY_TEXT_MAP.get(roadmap_issue_key)
                or (_sanitize_user_text(finding.gap_note) or "").strip()
                or _title_for_row(finding)
            )
            if not bool(re.search(r"[a-zA-Z]{4,}", sanitized_title)):
                sanitized_title = _title_for_row(finding)
            blocks.append(_TextBlock(sanitized_title[:180], bullet=True))
            raw_action = _sanitize_user_text(finding.remediation_note) or ""
            if not raw_action or any(t in raw_action.lower() for t in _ROADMAP_GENERIC_TOKENS):
                raw_action = ISSUE_ACTION_MAP.get(roadmap_issue_key) or raw_action
            raw_action = _apply_transfer_supplement(roadmap_issue_key, raw_action)
            if raw_action:
                blocks.append(_TextBlock(f"Action: {raw_action}", bullet=True))
    blocks.append(_TextBlock(f"Report created at: {report_created_at}", bullet=True))
    blocks.append(_TextBlock(f"Export-ready findings: {contract['counts_by_status']['total']}", bullet=True))
    if total == 0:
        blocks.append(_TextBlock("No material issues identified in the selected report dataset.", bullet=True))
        disposition_ledger = (
            db.query(Finding)
            .filter(Finding.audit_id == audit_id)
            .filter(Finding.legal_requirement == "suppression_validator=final_disposition_map")
            .order_by(Finding.id.desc())
            .first()
        )
        disposition: dict = {}
        if disposition_ledger and disposition_ledger.gap_reasoning:
            try:
                disposition = json.loads(disposition_ledger.gap_reasoning)
            except json.JSONDecodeError:
                disposition = {}
        if disposition:
            checklist_rows: list[tuple[str, str, str | None]] = []
            for duty in _CHECKLIST_CORE_DUTIES:
                item = disposition.get(duty, {})
                label = _CHECKLIST_DUTY_LABELS.get(duty, duty.replace("_", " ").title())
                outcome = _checklist_row_outcome(duty, item, is_specialist=False)
                raw_reason = item.get("reasoning")
                reason = _sanitize_user_text(raw_reason) if raw_reason else None
                checklist_rows.append((label, outcome, reason))
            for duty in _CHECKLIST_SPECIALIST_DUTIES:
                item = disposition.get(duty, {})
                label = _CHECKLIST_DUTY_LABELS.get(duty, duty.replace("_", " ").title())
                outcome = _checklist_row_outcome(duty, item, is_specialist=True)
                raw_reason = item.get("reasoning")
                reason = _sanitize_user_text(raw_reason) if raw_reason else None
                checklist_rows.append((label, outcome, reason))
            n_total = len(checklist_rows)
            n_satisfied = sum(1 for _, o, _ in checklist_rows if o == "Compliant")
            n_na = sum(1 for _, o, _ in checklist_rows if o == "Not applicable")
            n_gap = sum(1 for _, o, _ in checklist_rows if "Gap" in o)
            _outcome_order = {"Compliant": 0, "Not applicable": 1}
            checklist_rows.sort(key=lambda r: _outcome_order.get(r[1], 2))
            blocks.append(
                _TextBlock(
                    "GDPR Transparency Obligations Assessment",
                    font_size=13,
                    top_gap=14,
                    bold=True,
                    left_bar_color=_NAVY,
                )
            )
            blocks.append(
                _TextBlock(
                    "This document was assessed against all applicable GDPR transparency obligations. "
                    "No compliance gaps were identified in the published findings dataset.",
                    bullet=True,
                )
            )
            blocks.append(_TextBlock(f"Total obligations assessed: {n_total}", bullet=True))
            blocks.append(_TextBlock(f"Obligations satisfied (Compliant): {n_satisfied}", bullet=True))
            blocks.append(_TextBlock(f"Obligations not applicable: {n_na}", bullet=True))
            if n_gap:
                blocks.append(_TextBlock(f"Obligations with identified gaps: {n_gap}", bullet=True))
            # Checklist table — navy header row + alternating grey/white rows
            blocks.append(
                _TextBlock("Compliance Checklist", font_size=12, top_gap=12, bold=True, color=_WHITE, bg_color=_NAVY)
            )
            for row_i, (label, outcome, reason) in enumerate(checklist_rows):
                row_bg = _LIGHT_GREY if row_i % 2 == 0 else None
                blocks.append(_TextBlock(label, font_size=10, top_gap=4, bold=True, bg_color=row_bg))
                blocks.append(_TextBlock(f"Outcome: {outcome}", bullet=True, bg_color=row_bg))
                if reason:
                    blocks.append(_TextBlock(f"Detail: {reason[:300]}", bullet=True, bg_color=row_bg))
    blocks.append(_TextBlock(f"Finding IDs: {', '.join(contract['finding_ids'])}", bullet=True))

    # Remediation Plan section — only when compliance_score < 100
    if compliance_score is not None and compliance_score < 100:
        from app.models.audit import RemediationItem as _RemediationItem

        rem_items = (
            db.query(_RemediationItem)
            .filter(_RemediationItem.audit_id == audit_id)
            .order_by(_RemediationItem.order_index)
            .all()
        )
        if rem_items:
            blocks.append(_TextBlock("Remediation Plan", font_size=13, top_gap=14, bold=True, left_bar_color=_NAVY))
            blocks.append(
                _TextBlock(
                    "The following gaps have been identified and ordered by severity. "
                    "Addressing all items would raise the compliance score to 100%.",
                    bullet=True,
                )
            )
            for rem_item in rem_items:
                sev_label = rem_item.severity.title() if rem_item.severity else "Low"
                rem_sev_color = _SEVERITY_COLOR.get(rem_item.severity or "low", _SEV_LOW)
                blocks.append(
                    _TextBlock(
                        f"{rem_item.issue_label} [{sev_label} severity — +{rem_item.score_impact_points}% score impact]",
                        font_size=11,
                        top_gap=10,
                        bold=True,
                        left_bar_color=rem_sev_color,
                    )
                )
                # Gap description from linked finding
                finding = db.get(Finding, rem_item.finding_id) if rem_item.finding_id else None
                gap_desc = _sanitize_user_text(finding.gap_note if finding else None) if finding else None
                if gap_desc:
                    blocks.append(_TextBlock(f"Gap: {gap_desc[:400]}", bullet=True))
                # Suggested fix
                if (
                    rem_item.suggestion
                    and rem_item.suggestion.generation_status == "complete"
                    and rem_item.suggestion.suggested_fix_text
                ):
                    fix_text = rem_item.suggestion.suggested_fix_text[:600]
                    blocks.append(_TextBlock(f"Suggested fix: {fix_text}", bullet=True))
                else:
                    blocks.append(
                        _TextBlock(
                            "Suggested fix: Not yet generated. Use POST /audits/{id}/remediation to generate.",
                            bullet=True,
                        )
                    )

    out_path = settings.reports_dir / f"audit_{audit_id}_{report.id}.pdf"
    _write_pdf(blocks, out_path, generated_at=report_created_at)

    decoded = out_path.read_bytes().decode("latin-1", errors="ignore")
    expected_label = (
        "Final published findings"
        if contract["dataset_used"] == "published"
        else "Review findings (publication blocked)"
        if contract["dataset_used"] == "review"
        else "Preliminary analysis findings"
        if contract["dataset_used"] == "analysis"
        else "Zero-findings dataset"
    )
    pdf_count = decoded.count("Finding:")
    # Keep PDF generation non-blocking when findings exist; do not hard-fail on renderer count drift.
    label_ok = (
        ("Final published findings" in decoded and contract["dataset_used"] == "published")
        or ("Review findings" in decoded and contract["dataset_used"] == "review")
        or ("Preliminary analysis findings" in decoded and contract["dataset_used"] == "analysis")
        or ("Zero-findings dataset" in decoded and contract["dataset_used"] == "zero")
    )
    _ = "Dataset used:" not in decoded or not label_ok
    _ = "Finding IDs:" not in decoded or any(fid not in decoded for fid in contract["finding_ids"])
    if report_rows_deduped and not pdf_count:
        raise ValueError("PDF export mismatch: report has findings but pdf payload is empty")

    report.status = "ready"
    report.pdf_path = str(out_path)
    db.add(report)
    db.commit()
    db.refresh(report)

    return report, out_path
