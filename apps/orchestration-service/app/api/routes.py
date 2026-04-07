from pathlib import Path
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.audit import AnalysisCitation, Audit, AuditAnalysisItem, Finding, Report
from app.schemas.audit import (
    AuditCreate,
    AnalysisCitationOut,
    AnalysisItemOut,
    AuditOut,
    CitationOut,
    FindingOut,
    ReportOut,
    ReportTriggerOut,
    ReviewItemOut,
)
from app.services.audit_runner import run_audit
from app.services.reports import generate_report_text


router = APIRouter()
GENERIC_NOT_ASSESSABLE_GAP = "Not assessable from provided excerpt; additional documentary context is required."
GENERIC_NOT_ASSESSABLE_REMEDIATION = "Provide complete notice excerpts and rerun legal qualification."
FAMILY_FALLBACK_COPY: dict[str, tuple[str, str]] = {
    "missing_transfer_notice": (
        "Transfer-related processing language is visible, but the reviewed material does not show whether third-country transfer safeguards or mechanisms are disclosed.",
        "Provide the transfer/safeguards section or confirm whether adequacy, SCCs, or other transfer mechanisms are disclosed.",
    ),
    "profiling_disclosure_gap": (
        "Profiling or behavioral-analysis signals are visible, but the reviewed material does not show whether profiling logic, significance, or effects are disclosed.",
        "Provide profiling/automated-decision wording sufficient to assess Articles 13(2)(f), 14(2)(g), and where relevant Article 22.",
    ),
    "controller_processor_role_ambiguity": (
        "Customer-data/service-allocation language is visible, but the reviewed material does not clearly allocate controller/processor roles.",
        "Provide role-allocation or DPA wording showing when the company acts as controller, processor, or joint controller.",
    ),
    "article_14_indirect_collection_gap": (
        "Indirect/source-of-data signals are visible, but the reviewed material does not show source-category disclosure sufficient for Article 14 assessment.",
        "Provide source-of-data and indirect-collection notice language.",
    ),
    "missing_rights_notice": (
        "The reviewed material does not show the full rights disclosure set.",
        "Provide the rights section or confirm where rights are disclosed.",
    ),
}


def _deserialize_json_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return None


def _deserialize_bool_flag(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.lower() == "true"


def _issue_from_finding_section(section_id: str) -> str | None:
    if section_id.startswith("systemic:"):
        return section_id.split("systemic:", 1)[1]
    if section_id.startswith("ledger:"):
        return "completeness_or_suppression_ledger"
    return None


def _apply_family_fallback(issue_type: str | None, gap_note: str | None, remediation_note: str | None) -> tuple[str | None, str | None]:
    if not issue_type:
        return gap_note, remediation_note
    if (gap_note or "").strip() != GENERIC_NOT_ASSESSABLE_GAP and (remediation_note or "").strip() != GENERIC_NOT_ASSESSABLE_REMEDIATION:
        return gap_note, remediation_note
    replacement = FAMILY_FALLBACK_COPY.get(issue_type)
    if not replacement:
        return gap_note, remediation_note
    return replacement


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
        .where(Finding.publication_state == "publishable")
        .where(Finding.finding_type.in_(["local", "systemic"]))
        .where(Finding.classification.in_(["clear_non_compliance", "probable_gap", "not_assessable", "systemic_violation", "referenced_but_unseen"]))
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
                finding_type=row.finding_type,
                publish_flag=row.publish_flag,
                artifact_role=row.artifact_role,
                finding_level=row.finding_level,
                publication_state=row.publication_state,
                confidence=row.confidence,
                confidence_evidence=row.confidence_evidence,
                confidence_applicability=row.confidence_applicability,
                confidence_article_fit=row.confidence_article_fit,
                confidence_synthesis=row.confidence_synthesis,
                confidence_overall=row.confidence_overall,
                missing_from_section=row.missing_from_section,
                missing_from_document=row.missing_from_document,
                not_visible_in_excerpt=row.not_visible_in_excerpt,
                obligation_under_review=row.obligation_under_review,
                collection_mode=row.collection_mode,
                applicability_status=row.applicability_status,
                visibility_status=row.visibility_status,
                section_vs_document_scope=row.section_vs_document_scope,
                missing_fact_if_unresolved=row.missing_fact_if_unresolved,
                policy_evidence_excerpt=row.policy_evidence_excerpt,
                legal_requirement=row.legal_requirement,
                gap_reasoning=row.gap_reasoning,
                confidence_level=row.confidence_level,
                assessment_type=row.assessment_type,
                severity_rationale=row.severity_rationale,
                primary_legal_anchor=_deserialize_json_list(row.primary_legal_anchor),
                secondary_legal_anchors=_deserialize_json_list(row.secondary_legal_anchors),
                document_evidence_refs=_deserialize_json_list(row.document_evidence_refs),
                citation_summary_text=row.citation_summary_text,
                support_complete=_deserialize_bool_flag(row.support_complete),
                omission_basis=_deserialize_bool_flag(row.omission_basis),
                source_scope=row.source_scope,
                source_scope_confidence=row.source_scope_confidence,
                referenced_unseen_sections=_deserialize_json_list(row.referenced_unseen_sections),
                assertion_level=row.assertion_level,
                gap_note=_apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[0],
                remediation_note=_apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[1],
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


@router.get("/audits/{audit_id}/analysis", response_model=list[AnalysisItemOut])
def get_analysis(
    audit_id: str,
    status: str | None = Query(default=None, alias="status"),
    issue_type: str | None = Query(default=None),
    artifact_role: str | None = Query(default=None),
    section_id: str | None = Query(default=None),
    analysis_stage: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AnalysisItemOut]:
    query = (
        select(AuditAnalysisItem)
        .options(selectinload(AuditAnalysisItem.citations))
        .where(AuditAnalysisItem.audit_id == audit_id)
    )
    if status:
        query = query.where(AuditAnalysisItem.status_candidate == status)
    if issue_type:
        query = query.where(AuditAnalysisItem.issue_type == issue_type)
    if artifact_role:
        query = query.where(AuditAnalysisItem.artifact_role == artifact_role)
    if section_id:
        query = query.where(AuditAnalysisItem.section_id == section_id)
    if analysis_stage:
        query = query.where(AuditAnalysisItem.analysis_stage == analysis_stage)
    rows = db.scalars(query.order_by(AuditAnalysisItem.section_id.asc(), AuditAnalysisItem.id.asc())).all()
    if not rows:
        audit = db.get(Audit, audit_id)
        if not audit:
            raise HTTPException(status_code=404, detail="Audit not found")
    return [
        AnalysisItemOut(
            id=row.id,
            section_id=row.section_id,
            analysis_stage=row.analysis_stage,
            analysis_type=row.analysis_type,
            issue_type=row.issue_type,
            status_candidate=row.status_candidate,
            classification_candidate=row.classification_candidate,
            artifact_role=row.artifact_role,
            finding_level_candidate=row.finding_level_candidate,
            publication_state_candidate=row.publication_state_candidate,
            analysis_outcome=row.analysis_outcome,
            candidate_issue=row.candidate_issue,
            policy_evidence_excerpt=row.policy_evidence_excerpt,
            legal_requirement_candidate=row.legal_requirement_candidate,
            article_candidates=_deserialize_json_list(row.article_candidates),
            retrieval_summary=row.retrieval_summary,
            qualification_summary=row.qualification_summary,
            evidence_sufficiency=row.evidence_sufficiency,
            applicability=row.applicability,
            citation_fit_status=row.citation_fit_status,
            applicability_status=row.applicability_status,
            contradiction_status=row.contradiction_status,
            citation_fit=row.citation_fit,
            support_role=row.support_role,
            source_scope=row.source_scope,
            excerpt_scope_facts=row.excerpt_scope_facts,
            referenced_unseen_sections=_deserialize_json_list(row.referenced_unseen_sections),
            suppression_reason=row.suppression_reason,
            publishability_candidate=row.publishability_candidate,
            confidence=row.confidence,
            confidence_evidence=row.confidence_evidence,
            confidence_applicability=row.confidence_applicability,
            confidence_article_fit=row.confidence_article_fit,
            confidence_overall=row.confidence_overall,
            finding_status=row.finding_status,
            finding_classification=row.finding_classification,
            finding_severity=row.finding_severity,
            gap_note=_apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[0],
            remediation_note=_apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[1],
            citations=[
                AnalysisCitationOut(
                    chunk_id=c.chunk_id,
                    article_number=c.article_number,
                    paragraph_ref=c.paragraph_ref,
                    article_title=c.article_title,
                    excerpt=c.excerpt,
                )
                for c in row.citations
            ],
        )
        for row in rows
    ]


@router.get("/audits/{audit_id}/review", response_model=list[ReviewItemOut])
def get_review(audit_id: str, db: Session = Depends(get_db)) -> list[ReviewItemOut]:
    findings = db.scalars(
        select(Finding)
        .where(Finding.audit_id == audit_id)
        .where(
            (Finding.publication_state == "publishable")
            | (
                (Finding.publication_state.in_(["blocked", "internal_only"]))
                & (Finding.legal_requirement.is_not(None))
            )
        )
        .order_by(Finding.section_id.asc(), Finding.id.asc())
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
    if not findings and not analysis_rows:
        audit = db.get(Audit, audit_id)
        if not audit:
            raise HTTPException(status_code=404, detail="Audit not found")
    out: list[ReviewItemOut] = []
    out.extend(
        ReviewItemOut(
            item_kind="finding",
            id=row.id,
            section_id=row.section_id,
            issue_type=_issue_from_finding_section(row.section_id),
            status=row.status,
            classification=row.classification,
            artifact_role=row.artifact_role,
            finding_level=row.finding_level,
            publication_state=row.publication_state,
            suppression_reason=row.gap_note if row.publication_state in {"blocked", "internal_only"} else None,
            completeness_map=row.legal_requirement if row.legal_requirement and "completeness" in row.legal_requirement else None,
            gap_note=_apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[0],
            remediation_note=_apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[1],
        )
        for row in findings
    )
    out.extend(
        ReviewItemOut(
            item_kind="analysis",
            id=row.id,
            section_id=row.section_id,
            issue_type=row.issue_type,
            status=row.status_candidate,
            classification=row.classification_candidate,
            artifact_role=row.artifact_role,
            finding_level=row.finding_level_candidate,
            publication_state=row.publication_state_candidate,
            suppression_reason=row.suppression_reason,
            completeness_map=row.retrieval_summary if row.analysis_type == "completeness_outcome" else None,
            gap_note=_apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[0],
            remediation_note=_apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[1],
        )
        for row in analysis_rows
    )
    disposition_ledger = (
        db.query(Finding)
        .filter(Finding.audit_id == audit_id)
        .filter(Finding.legal_requirement == "suppression_validator=final_disposition_map")
        .order_by(Finding.id.desc())
        .first()
    )
    if disposition_ledger and disposition_ledger.gap_reasoning:
        try:
            disposition = json.loads(disposition_ledger.gap_reasoning)
        except json.JSONDecodeError:
            disposition = {}
        for duty in ["controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right"]:
            item = disposition.get(duty, {})
            out.append(
                ReviewItemOut(
                    item_kind="review_block",
                    id=f"core:{duty}",
                    section_id="review:core_duties",
                    status=None,
                    review_group="core_duties",
                    duty=duty,
                    final_disposition=item.get("status"),
                    reason=item.get("reasoning"),
                )
            )
        specialist_triggers = {
            "transfer": ("transfer", "transfer"),
            "profiling": ("profiling", "profiling"),
            "role_ambiguity": ("role_ambiguity", "role_ambiguity"),
            "article14_source": ("article14_source", "article14"),
            "special_category": ("special_category", "special_category"),
        }
        for family, (lookup_key, label) in specialist_triggers.items():
            item = disposition.get(lookup_key, {})
            out.append(
                ReviewItemOut(
                    item_kind="review_block",
                    id=f"family:{family}",
                    section_id="review:specialist_families",
                    review_group="specialist_families",
                    family=label,
                    triggered=item.get("status") != "satisfied",
                    final_disposition=item.get("status"),
                    reason=item.get("reasoning"),
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
