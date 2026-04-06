from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.audit import Audit, Finding, Report
from app.schemas.audit import (
    AuditCreate,
    AuditOut,
    CitationOut,
    FindingOut,
    ReportOut,
    ReportTriggerOut,
)
from app.services.audit_runner import run_audit
from app.services.reports import generate_report_text


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/audits", response_model=AuditOut)
def create_audit(payload: AuditCreate, db: Session = Depends(get_db)) -> AuditOut:
    audit = Audit(document_id=payload.document_id, status="pending")
    db.add(audit)
    db.commit()
    db.refresh(audit)

    try:
        audit = run_audit(db, audit)
    except Exception as exc:
        db.rollback()
        audit.status = "failed"
        db.add(audit)
        db.commit()
        raise HTTPException(status_code=502, detail=f"Audit failed: {exc}")

    return AuditOut.model_validate(audit, from_attributes=True)


@router.get("/audits/{audit_id}", response_model=AuditOut)
def get_audit(audit_id: str, db: Session = Depends(get_db)) -> AuditOut:
    audit = db.get(Audit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return AuditOut.model_validate(audit, from_attributes=True)


@router.get("/audits/{audit_id}/findings", response_model=list[FindingOut])
def get_findings(audit_id: str, db: Session = Depends(get_db)) -> list[FindingOut]:
    rows = db.scalars(
        select(Finding)
        .options(selectinload(Finding.citations))
        .where(Finding.audit_id == audit_id)
        .order_by(Finding.section_id.asc(), Finding.id.asc())
    ).all()
    if not rows:
        audit = db.get(Audit, audit_id)
        if not audit:
            raise HTTPException(status_code=404, detail="Audit not found")

    out: list[FindingOut] = []
    seen: set[str] = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        out.append(
            FindingOut(
                id=row.id,
                section_id=row.section_id,
                status=row.status,
                severity=row.severity,
                classification=row.classification,
                confidence=row.confidence,
                gap_note=row.gap_note,
                remediation_note=row.remediation_note,
                citations=[
                    CitationOut(
                        chunk_id=c.chunk_id,
                        article_number=c.article_number,
                        paragraph_ref=c.paragraph_ref,
                        article_title=c.article_title,
                        excerpt=c.excerpt,
                    )
                    for c in row.citations
                ],
            )
        )
    return out


@router.post("/audits/{audit_id}/report", response_model=ReportTriggerOut)
def create_report(audit_id: str, db: Session = Depends(get_db)) -> ReportTriggerOut:
    audit = db.get(Audit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    if audit.status != "complete":
        raise HTTPException(status_code=409, detail="Audit is not complete")

    try:
        report, _ = generate_report_text(db, audit_id)
    except Exception as exc:
        failed = Report(audit_id=audit_id, status="failed")
        db.add(failed)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    return ReportTriggerOut(report_id=report.id, status=report.status)


@router.get("/audits/{audit_id}/report", response_model=ReportOut)
def get_report(audit_id: str, db: Session = Depends(get_db)) -> ReportOut:
    report = db.scalars(select(Report).where(Report.audit_id == audit_id).order_by(Report.created_at.desc())).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportOut.model_validate(report, from_attributes=True)


@router.get("/audits/{audit_id}/report/download")
def download_report(audit_id: str, db: Session = Depends(get_db)) -> FileResponse:
    report = db.scalars(select(Report).where(Report.audit_id == audit_id).order_by(Report.created_at.desc())).first()
    if not report or not report.pdf_path:
        raise HTTPException(status_code=404, detail="Report not found")

    path = Path(report.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report file missing")

    return FileResponse(path=str(path), media_type="application/pdf", filename=path.name)
