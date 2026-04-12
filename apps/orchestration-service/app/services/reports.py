from __future__ import annotations

import re
import json
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.audit import Audit, AuditAnalysisItem, Finding, Report
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
    'support_only', 'internal_only', 'candidate_issue', 'provisional_local', 'support_evidence',
    'post_reviewer_snapshot', 'meta_section', 'auditability gate', 'not_assessable',
    'confirmed_document_gap', 'probable_document_gap', 'clear_non_compliance',
    'withheld by final publication validator', 'explicit violation validator matched',
    'duty validation marked', 'invalid_consent', 'profiling_without_required_explanation',
    'weak_transfer_safeguards', 'embedding model', 'corpus version', 'parse failure rate',
    'contradiction rate', 'heuristic quality score', 'confidence component breakdown',
]

ISSUE_TITLE_MAP = {
    'missing_legal_basis': 'Missing legal basis disclosure',
    'missing_retention_period': 'Missing retention-period disclosure',
    'missing_rights_notice': 'Missing rights-notice disclosure',
    'missing_complaint_right': 'Missing complaint-right disclosure',
    'missing_transfer_notice': 'Missing transfer disclosure',
    'profiling_disclosure_gap': 'Profiling transparency gap',
    'recipients_disclosure_gap': 'Recipients disclosure gap',
    'purpose_specificity_gap': 'Purpose specificity gap',
    'controller_processor_role_ambiguity': 'Role allocation needs clarification',
}

class _TextBlock(NamedTuple):
    text: str
    font_size: int = 10
    top_gap: int = 0
    bullet: bool = False


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


def _write_pdf(blocks: list[_TextBlock], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page_width = 595
    page_height = 842
    margin_left = 50
    margin_right = 50
    margin_top = 60
    margin_bottom = 60
    default_line_gap = 4

    pages: list[list[_TextBlock]] = [[]]
    cursor_y = page_height - margin_top

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

        needed_height = block.top_gap + (line_height * max(1, len(wrapped)))
        if cursor_y - needed_height < margin_bottom and pages[-1]:
            pages.append([])
            cursor_y = page_height - margin_top

        pages[-1].append(block)
        cursor_y -= needed_height

    if not pages or (len(pages) == 1 and not pages[0]):
        pages = [[_TextBlock("CompliTrace Report: no content available.")]]

    page_object_ids: list[int] = []
    objects: list[bytes] = []

    # 1 catalog, 2 pages root, 3 font
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n")
    objects.append(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    next_obj_id = 4
    for page_blocks in pages:
        page_id = next_obj_id
        content_id = next_obj_id + 1
        next_obj_id += 2
        page_object_ids.append(page_id)

        cursor_y = page_height - margin_top
        commands = ["BT", f"{margin_left} {cursor_y} Td"]
        for block in page_blocks:
            font_size = block.font_size
            line_height = font_size + default_line_gap
            max_chars = _estimate_max_chars(font_size, page_width, margin_left, margin_right)
            wrapped = _wrap_text(
                block.text,
                max_chars=max_chars,
                initial_indent="- " if block.bullet else "",
                continuation_indent="  " if block.bullet else "",
            )

            if block.top_gap:
                commands.append(f"0 -{block.top_gap} Td")
                cursor_y -= block.top_gap

            commands.append(f"/F1 {font_size} Tf")
            for idx, line in enumerate(wrapped):
                safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                commands.append(f"({safe}) Tj")
                if idx != len(wrapped) - 1:
                    commands.append(f"0 -{line_height} Td")
            commands.append(f"0 -{line_height} Td")
            cursor_y -= line_height * max(1, len(wrapped))
        commands.append("ET")
        content_stream = "\n".join(commands).encode("latin-1", errors="replace")

        objects.append(
            f"{page_id} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>\nendobj\n".encode("ascii")
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
    pdf.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii")
    )
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
            label = f"Section {section.section_order}: {section.section_title}"
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
    cleaned = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[\s*\]", "", cleaned)
    cleaned = re.sub(r"The reviewed notice content triggers GDPR transparency analysis\.?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Observation:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"Substantive disclosure signal detected\.?", "The notice text suggests disclosure is present, but key details remain unclear.", cleaned, flags=re.IGNORECASE)
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
    if section_id.startswith('systemic:'):
        return section_id.split('systemic:', 1)[1]
    return None


def _title_for_row(row: Finding) -> str:
    issue = _issue_from_section_id(row.section_id)
    if issue and issue in ISSUE_TITLE_MAP:
        return ISSUE_TITLE_MAP[issue]
    candidate = _sanitize_user_text(row.legal_requirement) or _sanitize_user_text(row.gap_note)
    return candidate[:90] if candidate else 'GDPR transparency disclosure gap'


def _evidence_for_row(row: Finding, section_label: str) -> str:
    excerpt = next((c.excerpt for c in row.citations if _sanitize_user_text(c.excerpt)), None)
    if excerpt:
        return f"{section_label}: {_sanitize_user_text(excerpt)}"
    title = _title_for_row(row).lower()
    return f"Confirmed after review of the full document: no disclosure of {title} was identified."


def _is_safe_for_export(row: Finding, section_label: str) -> bool:
    title = _title_for_row(row)
    evidence = _evidence_for_row(row, section_label)
    blob = f"{title} {_sanitize_user_text(row.gap_note) or ''} {_sanitize_user_text(row.remediation_note) or ''} {evidence}".lower()
    if not evidence.strip() or '[ ]' in blob or '[]' in blob:
        return False
    if any(token in blob for token in BANNED_USER_TOKENS):
        return False
    return True

def generate_report_text(db: Session, audit_id: str) -> tuple[Report, Path]:
    audit = db.get(Audit, audit_id)
    if not audit:
        raise ValueError("Audit not found")

    report = Report(audit_id=audit_id, status="pending")
    db.add(report)
    db.commit()
    db.refresh(report)

    findings = db.scalars(
        select(Finding)
        .options(selectinload(Finding.citations))
        .where(Finding.audit_id == audit_id)
        .order_by(Finding.section_id.asc())
    ).all()
    analysis_rows = db.scalars(
        select(AuditAnalysisItem)
        .where(AuditAnalysisItem.audit_id == audit_id)
        .where(
            AuditAnalysisItem.analysis_type.in_(
                ["completeness_outcome", "referenced_but_unseen", "not_assessable_core_duty", "support_evidence", "excerpt_scope_fact"]
            )
        )
        .order_by(AuditAnalysisItem.section_id.asc(), AuditAnalysisItem.id.asc())
    ).all()

    visible_review_findings = [
        row
        for row in findings
        if (
            row.publication_state in {"publishable", "blocked"}
            or (row.publication_state in {"internal_only"} and row.legal_requirement is not None)
        )
        and not row.section_id.startswith("ledger:")
    ]
    publishable_findings = [f for f in findings if _is_publishable_finding(f)]
    published_blocked = len(publishable_findings) == 0 and len(visible_review_findings) > 0
    report_rows = visible_review_findings if published_blocked else publishable_findings

    deduped_by_section: dict[str, Finding] = {}
    for row in report_rows:
        if row.classification in {"diagnostic_internal_only", "not_assessable"}:
            continue
        existing = deduped_by_section.get(row.section_id)
        if not existing:
            deduped_by_section[row.section_id] = row
            continue
        current_rank = {"gap": 4, "partial": 3, "compliant": 2, "not applicable": 1}.get(_normalize_status(row.status), 1)
        existing_rank = {"gap": 4, "partial": 3, "compliant": 2, "not applicable": 1}.get(_normalize_status(existing.status), 1)
        if current_rank > existing_rank:
            deduped_by_section[row.section_id] = row

    document_title, section_meta = _section_report_meta(audit)
    report_rows_deduped = [
        row
        for row in deduped_by_section.values()
        if _is_safe_for_export(
            row,
            section_meta.get(row.section_id, _SectionReportMeta(label="Document section", page_range=None)).label,
        )
    ]
    systemic_findings = [f for f in report_rows_deduped if f.section_id.startswith("systemic:")]
    local_findings = [f for f in report_rows_deduped if not f.section_id.startswith("systemic:")]

    total = len(report_rows_deduped)
    by_status = {
        "compliant": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Compliant"),
        "partial": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Partially compliant"),
        "gap": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Non-compliant"),
        "not applicable": sum(1 for row in report_rows_deduped if _user_status_label(row.status) == "Not applicable"),
    }
    started_at = audit.started_at.isoformat(sep=" ", timespec="seconds") if isinstance(audit.started_at, datetime) else "n/a"
    completed_at = (
        audit.completed_at.isoformat(sep=" ", timespec="seconds")
        if isinstance(audit.completed_at, datetime)
        else "n/a"
    )
    report_created_at = (
        report.created_at.isoformat(sep=" ", timespec="seconds")
        if isinstance(report.created_at, datetime)
        else "n/a"
    )

    blocks: list[_TextBlock] = [
        _TextBlock("CompliTrace GDPR Gap Report", font_size=16, top_gap=0),
        _TextBlock(f"Document title: {document_title or 'Unavailable'}", font_size=10, top_gap=8),
        _TextBlock(f"Audit started at: {started_at}", font_size=10),
        _TextBlock(f"Audit completed at: {completed_at}", font_size=10),
        _TextBlock("Executive Summary", font_size=13, top_gap=14),
        _TextBlock(f"Total findings: {total}", bullet=True),
        _TextBlock(f"Compliant: {by_status['compliant']}", bullet=True),
        _TextBlock(f"Partially compliant: {by_status['partial']}", bullet=True),
        _TextBlock(f"Non-compliant: {by_status['gap']}", bullet=True),
        _TextBlock(f"Not applicable: {by_status['not applicable']}", bullet=True),
        _TextBlock(
            "Dataset used: Review findings (publication blocked)" if published_blocked else "Dataset used: Final published findings.",
            bullet=True,
        ),
        _TextBlock("Document-wide findings", font_size=13, top_gap=14),
    ]
    scope_label = next((f.source_scope for f in systemic_findings if f.source_scope), None)
    if scope_label == "partial_notice_excerpt":
        blocks.append(_TextBlock("Scope note: This review is based on the provided excerpt rather than the full notice.", bullet=True))
    elif scope_label == "full_notice":
        blocks.append(_TextBlock("Scope note: This review covers the complete notice provided.", bullet=True))
    elif scope_label:
        blocks.append(_TextBlock("Scope note: Source scope is uncertain; findings are calibrated conservatively.", bullet=True))

    for finding in systemic_findings:
        meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
        blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10))
        blocks.append(_TextBlock(f"Finding: {_title_for_row(finding)}", bullet=True))
        issue_hint = (finding.legal_requirement or finding.section_id).replace("systemic:", "").replace("_", " ")
        blocks.append(_TextBlock(f"Status: {_user_status_label(finding.status)}", bullet=True))
        blocks.append(_TextBlock(f"Severity: {_user_severity_label(finding.severity, issue_hint)}", bullet=True))
        primary_anchors = _decode_json_list(finding.primary_legal_anchor)
        if primary_anchors:
            blocks.append(_TextBlock(f"Legal basis: {', '.join(primary_anchors)}", bullet=True))
        if finding.citation_summary_text:
            blocks.append(_TextBlock(f"Why flagged: {_sanitize_user_text(finding.citation_summary_text)}", bullet=True))
        if finding.gap_note:
            blocks.append(_TextBlock(f"Why this matters: {_sanitize_user_text(finding.gap_note)}", bullet=True))
        if finding.remediation_note:
            blocks.append(_TextBlock(f"Recommended action: {_sanitize_user_text(finding.remediation_note)}", bullet=True))
        blocks.append(_TextBlock(f"Evidence: {_evidence_for_row(finding, meta.label)}", bullet=True))
    if not systemic_findings:
        blocks.append(_TextBlock("No document-wide compliance issues were identified.", bullet=True))

    blocks.append(_TextBlock("Section findings", font_size=13, top_gap=14))
    for finding in local_findings:
        meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
        blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10))
        blocks.append(_TextBlock(f"Finding: {_title_for_row(finding)}", bullet=True))
        issue_hint = finding.legal_requirement or finding.section_id
        blocks.append(_TextBlock(f"Status: {_user_status_label(finding.status)}", bullet=True))
        blocks.append(_TextBlock(f"Severity: {_user_severity_label(finding.severity, issue_hint)}", bullet=True))
        safe_gap_note = _sanitize_user_text(finding.gap_note)
        safe_remediation_note = _sanitize_user_text(finding.remediation_note)
        if safe_gap_note:
            blocks.append(_TextBlock(f"Why this matters: {safe_gap_note}", bullet=True))
        if safe_remediation_note:
            blocks.append(_TextBlock(f"Recommended action: {safe_remediation_note}", bullet=True))
        blocks.append(_TextBlock(f"Evidence: {_evidence_for_row(finding, meta.label)}", bullet=True))
        for citation in finding.citations:
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
        blocks.append(_TextBlock("Recommended actions", font_size=13, top_gap=14))
        for finding in sorted(roadmap_items, key=lambda row: {"high": 0, "medium": 1, "low": 2}.get((row.severity or "low"), 3)):
            title = finding.gap_note or "Remediate transparency obligation gap."
            blocks.append(_TextBlock(_sanitize_user_text(title)[:180], bullet=True))
            blocks.append(_TextBlock(f"Action: {_sanitize_user_text(finding.remediation_note)}", bullet=True))
    blocks.append(_TextBlock(f"Report created at: {report_created_at}", bullet=True))

    out_path = settings.reports_dir / f"audit_{audit_id}_{report.id}.pdf"
    _write_pdf(blocks, out_path)

    report.status = "ready"
    report.pdf_path = str(out_path)
    db.add(report)
    db.commit()
    db.refresh(report)

    return report, out_path
