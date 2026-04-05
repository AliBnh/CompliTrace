from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.audit import Audit, Finding, Report


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

    total = len(findings)
    by_status = {
        "compliant": sum(1 for f in findings if f.status == "compliant"),
        "partial": sum(1 for f in findings if f.status == "partial"),
        "gap": sum(1 for f in findings if f.status == "gap"),
        "needs review": sum(1 for f in findings if f.status == "needs review"),
        "not applicable": sum(1 for f in findings if f.status == "not applicable"),
    }
    substantive = [f for f in findings if f.status in {"partial", "gap"}]
    substantive_with_citations = sum(1 for f in substantive if len(f.citations) > 0)
    citation_coverage = (substantive_with_citations / len(substantive)) if substantive else 1.0
    parse_failures = sum(1 for f in findings if f.gap_note == "LLM parse failure")
    parse_failure_rate = (parse_failures / total) if total else 0.0
    quality_score = max(0.0, 10.0 - (parse_failure_rate * 6.0) - ((1.0 - citation_coverage) * 4.0))

    lines = [
        "CompliTrace GDPR Gap Report",
        f"Audit ID: {audit.id}",
        f"Document ID: {audit.document_id}",
        f"Model: {audit.model_provider}:{audit.model_name}",
        f"Embedding model: {audit.embedding_model}",
        f"Corpus version: {audit.corpus_version}",
        "",
        "Executive summary",
        f"- Total findings: {total}",
        f"- Compliant: {by_status['compliant']}",
        f"- Partial: {by_status['partial']}",
        f"- Gap: {by_status['gap']}",
        f"- Needs review: {by_status['needs review']}",
        f"- Not applicable: {by_status['not applicable']}",
        f"- Substantive citation coverage: {citation_coverage:.0%}",
        f"- LLM parse failure rate: {parse_failure_rate:.0%}",
        f"- Report quality score (heuristic): {quality_score:.1f}/10",
        "",
    ]

    for f in findings:
        lines.append(f"Section {f.section_id}")
        lines.append(f"Status: {f.status}")
        lines.append(f"Severity: {f.severity}")
        if f.gap_note:
            lines.append(f"Gap note: {f.gap_note}")
        if f.remediation_note:
            lines.append(f"Remediation: {f.remediation_note}")
        for c in f.citations:
            lines.append(f"- Citation {c.article_number} ({c.paragraph_ref}) [{c.chunk_id}]")
        lines.append("")

    out_path = settings.reports_dir / f"audit_{audit_id}_{report.id}.pdf"
    out_path.write_text("\n".join(lines), encoding="utf-8")

    report.status = "ready"
    report.pdf_path = str(out_path)
    db.add(report)
    db.commit()
    db.refresh(report)

    return report, out_path
