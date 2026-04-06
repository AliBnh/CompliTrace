from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.audit import Audit, Finding, Report
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
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


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
    systemic_findings = [f for f in findings if f.finding_type == "systemic" and f.publish_flag == "yes"]
    publishable_findings = [f for f in findings if f.finding_type == "local" and f.publish_flag == "yes"]
    not_assessable_findings = [f for f in publishable_findings if f.classification == "not_assessable"]
    publishable_local_findings = [f for f in publishable_findings if f.classification != "not_assessable"]

    total = len(findings)
    by_status = {
        "compliant": sum(1 for f in findings if f.status == "compliant"),
        "partial": sum(1 for f in findings if f.status == "partial"),
        "gap": sum(1 for f in findings if f.status == "gap"),
        "needs review": sum(1 for f in findings if f.status == "needs review"),
        "not applicable": sum(1 for f in findings if f.status == "not applicable"),
    }
    by_classification = {
        "clear_non_compliance": sum(1 for f in findings if f.classification == "clear_non_compliance"),
        "probable_gap": sum(1 for f in findings if f.classification == "probable_gap"),
        "not_assessable": sum(1 for f in findings if f.classification == "not_assessable"),
    }
    substantive = [f for f in findings if f.status in {"partial", "gap"}]
    substantive_with_citations = sum(1 for f in substantive if len(f.citations) > 0)
    citation_coverage = (substantive_with_citations / len(substantive)) if substantive else 1.0
    parse_failures = sum(1 for f in findings if f.gap_note == "LLM parse failure")
    parse_failure_rate = (parse_failures / total) if total else 0.0
    needs_review_rate = (by_status["needs review"] / total) if total else 0.0
    contradiction_hits = sum(
        1 for f in findings if (f.gap_note and "insufficient legally compatible citation support" in f.gap_note.lower())
    )
    contradiction_rate = (contradiction_hits / total) if total else 0.0
    systemic_ratio = (sum(1 for f in findings if f.classification == "systemic_violation") / total) if total else 0.0
    quality_score = max(
        0.0,
        10.0
        - (parse_failure_rate * 4.0)
        - ((1.0 - citation_coverage) * 1.0)
        - (needs_review_rate * 2.0)
        - (contradiction_rate * 3.0)
        + (systemic_ratio * 1.0),
    )
    document_title, section_meta = _section_report_meta(audit)
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
        _TextBlock(f"Model: {audit.model_provider}:{audit.model_name}", font_size=10),
        _TextBlock(f"Embedding model: {audit.embedding_model}", font_size=10),
        _TextBlock(f"Corpus version: {audit.corpus_version}", font_size=10),
        _TextBlock("Executive Summary", font_size=13, top_gap=14),
        _TextBlock(f"Total findings: {total}", bullet=True),
        _TextBlock(f"Compliant: {by_status['compliant']}", bullet=True),
        _TextBlock(f"Partial: {by_status['partial']}", bullet=True),
        _TextBlock(f"Gap: {by_status['gap']}", bullet=True),
        _TextBlock(f"Needs review (internal only, not published): {by_status['needs review']}", bullet=True),
        _TextBlock(f"Not applicable: {by_status['not applicable']}", bullet=True),
        _TextBlock(f"Substantive citation coverage: {citation_coverage:.0%}", bullet=True),
        _TextBlock(f"Clear non-compliance findings: {by_classification['clear_non_compliance']}", bullet=True),
        _TextBlock(f"Probable gap findings: {by_classification['probable_gap']}", bullet=True),
        _TextBlock(f"Not assessable findings: {by_classification['not_assessable']}", bullet=True),
        _TextBlock(f"LLM parse failure rate: {parse_failure_rate:.0%}", bullet=True),
        _TextBlock(f"Needs review rate: {needs_review_rate:.0%}", bullet=True),
        _TextBlock(f"Citation contradiction rate: {contradiction_rate:.0%}", bullet=True),
        _TextBlock(f"Report quality score (heuristic): {quality_score:.1f}/10", bullet=True),
        _TextBlock("Top Systemic Findings", font_size=13, top_gap=14),
    ]

    for finding in systemic_findings:
        meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
        blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10))
        blocks.append(_TextBlock(f"Status: {finding.status}", bullet=True))
        blocks.append(_TextBlock(f"Severity: {finding.severity or 'n/a'}", bullet=True))
        if finding.gap_note:
            blocks.append(_TextBlock(f"Gap note: {_sanitize_user_text(finding.gap_note)}", bullet=True))
        if finding.remediation_note:
            blocks.append(_TextBlock(f"Remediation: {_sanitize_user_text(finding.remediation_note)}", bullet=True))

    blocks.append(_TextBlock("Unique Local Findings", font_size=13, top_gap=14))
    for finding in publishable_local_findings:
        meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
        blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10))
        if meta.page_range:
            blocks.append(_TextBlock(f"Section page range: {meta.page_range}", bullet=True))
        blocks.append(_TextBlock(f"Status: {finding.status}", bullet=True))
        blocks.append(_TextBlock(f"Severity: {finding.severity or 'n/a'}", bullet=True))
        if finding.classification:
            blocks.append(_TextBlock(f"Classification: {finding.classification}", bullet=True))
        if finding.confidence is not None:
            blocks.append(_TextBlock(f"Confidence: {finding.confidence:.2f}", bullet=True))
        if finding.confidence_overall is not None:
            blocks.append(_TextBlock(f"Confidence (overall): {finding.confidence_overall:.2f}", bullet=True))
        if finding.confidence_evidence is not None:
            blocks.append(_TextBlock(f"Confidence (evidence): {finding.confidence_evidence:.2f}", bullet=True))
        if finding.confidence_applicability is not None:
            blocks.append(_TextBlock(f"Confidence (applicability): {finding.confidence_applicability:.2f}", bullet=True))
        if finding.confidence_article_fit is not None:
            blocks.append(_TextBlock(f"Confidence (article fit): {finding.confidence_article_fit:.2f}", bullet=True))
        safe_gap_note = _sanitize_user_text(finding.gap_note)
        safe_remediation_note = _sanitize_user_text(finding.remediation_note)
        if finding.status == "needs review" and safe_gap_note and "insufficient legally compatible citation support" in safe_gap_note.lower():
            safe_gap_note = "Not assessable with current excerpt quality; legal review needed with stronger evidence."
            safe_remediation_note = "Provide complete section text and rerun audit."
        if safe_gap_note:
            blocks.append(_TextBlock(f"Gap note: {safe_gap_note}", bullet=True))
        if safe_remediation_note:
            blocks.append(_TextBlock(f"Remediation: {safe_remediation_note}", bullet=True))
        for citation in finding.citations:
            blocks.append(
                _TextBlock(
                    _format_citation_label(citation.article_number, citation.article_title, citation.paragraph_ref),
                    bullet=True,
                )
            )
            if citation.excerpt:
                blocks.append(_TextBlock(f'Evidence: "{citation.excerpt}"', bullet=True))
    if not_assessable_findings:
        blocks.append(_TextBlock("Not Assessable from Provided Excerpt", font_size=13, top_gap=14))
        for finding in not_assessable_findings:
            meta = section_meta.get(finding.section_id, _SectionReportMeta(label="Document section", page_range=None))
            blocks.append(_TextBlock(meta.label, font_size=11, top_gap=10))
            if finding.gap_note:
                blocks.append(_TextBlock(f"Constraint: {_sanitize_user_text(finding.gap_note)}", bullet=True))
            if finding.missing_fact_if_unresolved:
                blocks.append(_TextBlock(f"Missing context to resolve: {finding.missing_fact_if_unresolved}", bullet=True))
            if finding.remediation_note:
                blocks.append(_TextBlock(f"Next step: {_sanitize_user_text(finding.remediation_note)}", bullet=True))
    roadmap_items = [f for f in findings if f.publish_flag == "yes" and f.remediation_note]
    if roadmap_items:
        blocks.append(_TextBlock("Prioritized Remediation Roadmap", font_size=13, top_gap=14))
        for finding in sorted(roadmap_items, key=lambda row: {"high": 0, "medium": 1, "low": 2}.get((row.severity or "low"), 3)):
            title = finding.gap_note or "Remediate transparency obligation gap."
            blocks.append(_TextBlock(_sanitize_user_text(title)[:180], bullet=True))
            blocks.append(_TextBlock(f"Action: {_sanitize_user_text(finding.remediation_note)}", bullet=True))
    blocks.append(_TextBlock("Report generation metadata", font_size=12, top_gap=14))
    blocks.append(_TextBlock(f"Report created at: {report_created_at}", bullet=True))
    blocks.append(_TextBlock(f"Report schema version: {REPORT_SCHEMA_VERSION}", bullet=True))

    out_path = settings.reports_dir / f"audit_{audit_id}_{report.id}.pdf"
    _write_pdf(blocks, out_path)

    report.status = "ready"
    report.pdf_path = str(out_path)
    db.add(report)
    db.commit()
    db.refresh(report)

    return report, out_path
