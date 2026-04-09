from pathlib import Path
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models.audit import AnalysisCitation, Audit, AuditAnalysisItem, EvidenceRecord, Finding, FindingCitation, Report
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


INTERNAL_MARKER_RE = re.compile(
    r"(?:\s*\[withheld by final publication validator\]\s*|suppression_validator=\S+|state_invariant_violation:[^\s,;]+|post-review invariant rewrite|diagnostic_internal_only|\[[^\]]*internal[^\]]*\])",
    flags=re.IGNORECASE,
)


def _sanitize_published_text(text: str | None) -> str | None:
    if not text:
        return text
    cleaned = INTERNAL_MARKER_RE.sub(" ", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _sanitize_review_text(text: str | None, *, debug: bool) -> str | None:
    if debug or not text:
        return text
    cleaned = _sanitize_published_text(text)
    if not cleaned:
        return cleaned
    cleaned = cleaned.replace(
        "Systemic finding withheld from publication pending complete legal/document support package",
        "This issue was identified internally but is not yet finalized for publication because the current evidence package is incomplete.",
    )
    return cleaned


def _normalize_internal_state(
    classification: str | None,
    status: str | None,
    artifact_role: str | None,
    finding_level: str | None,
    publication_state: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if classification != "diagnostic_internal_only":
        return status, artifact_role, finding_level, publication_state
    return "not_applicable", "support_only", "none", "internal_only"


def _load_final_decision_map(db: Session, audit_id: str) -> dict[str, dict[str, str | bool | list[str] | float]] | None:
    disposition_ledger = (
        db.query(Finding)
        .filter(Finding.audit_id == audit_id)
        .filter(Finding.legal_requirement == "suppression_validator=final_disposition_map")
        .order_by(Finding.id.desc())
        .first()
    )
    if not disposition_ledger or not disposition_ledger.gap_reasoning:
        return None
    try:
        parsed = json.loads(disposition_ledger.gap_reasoning)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _publication_allowed_from_map(decision_map: dict[str, dict[str, str | bool | list[str] | float]]) -> bool:
    controls = decision_map.get("_controls", {})
    publication_allowed = controls.get("publication_allowed")
    if isinstance(publication_allowed, bool):
        return publication_allowed
    core_families = ("controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right")
    for family in core_families:
        status = str((decision_map.get(family, {}) or {}).get("status") or "")
        if status in {"unresolved_internal_error", "blocked"}:
            return False
    return True


def _project_published_findings_from_map(
    audit_id: str,
    decision_map: dict[str, dict[str, str | bool | list[str] | float]],
    backing_rows: list[Finding] | None = None,
    known_evidence_ids: set[str] | None = None,
    evidence_by_chunk: dict[str, EvidenceRecord] | None = None,
    evidence_by_id: dict[str, EvidenceRecord] | None = None,
) -> list[FindingOut]:
    family_to_issue = {
        "controller_identity_contact": "missing_controller_identity",
        "legal_basis": "missing_legal_basis",
        "retention": "missing_retention_period",
        "rights_notice": "missing_rights_notice",
        "complaint_right": "missing_complaint_right",
        "transfer": "missing_transfer_notice",
        "profiling": "profiling_disclosure_gap",
        "role_ambiguity": "controller_processor_role_ambiguity",
        "article14_source": "article_14_indirect_collection_gap",
        "recipients": "recipients_disclosure_gap",
        "special_category": "special_category_basis_unclear",
        "dpo_contact": "dpo_contact_gap",
    }
    severity_defaults = {
        "controller_identity_contact": "high",
        "legal_basis": "high",
        "transfer": "high",
        "profiling": "high",
        "retention": "medium",
        "rights_notice": "medium",
        "complaint_right": "medium",
        "role_ambiguity": "high",
        "article14_source": "medium",
        "recipients": "medium",
        "special_category": "high",
        "dpo_contact": "medium",
    }
    out: list[FindingOut] = []
    remediation_defaults = {
        "missing_transfer_notice": "State whether personal data are transferred internationally and identify the safeguard or transfer mechanism relied upon, such as adequacy decisions or appropriate safeguards, and how data subjects can obtain further information.",
        "profiling_disclosure_gap": "If profiling or comparable evaluation occurs, explain the logic involved and, where required, the significance and envisaged consequences for individuals.",
        "controller_processor_role_ambiguity": "Clarify when the organization acts as controller, processor, or similar role across the different processing contexts described in the notice.",
    }
    row_by_issue: dict[str, Finding] = {}
    for row in backing_rows or []:
        issue = _issue_from_finding_section(row.section_id)
        if issue and issue not in row_by_issue:
            row_by_issue[issue] = row
    for family, issue in family_to_issue.items():
        item = decision_map.get(family, {}) or {}
        status = str(item.get("status") or "")
        publish_rec = str(item.get("publication_recommendation") or "internal_only")
        if status not in {"gap", "referenced_but_unseen"} or publish_rec != "publish":
            continue
        reason = str(item.get("reasoning") or "")
        projected_evidence_ids = [str(v) for v in (item.get("positive_evidence_ids") or []) if isinstance(v, str) and str(v).startswith("evi:")]
        backing = row_by_issue.get(issue)
        if backing is not None:
            projected_evidence_ids.extend(_deserialize_json_list(backing.document_evidence_refs) or [])
            projected_evidence_ids.append(f"evi:policy:{backing.section_id}")
        projected_evidence_ids = list(dict.fromkeys(e for e in projected_evidence_ids if isinstance(e, str) and e.startswith("evi:")))
        primary_anchor = _deserialize_json_list(backing.primary_legal_anchor) if backing and backing.primary_legal_anchor else ["GDPR Article 13(1)(a)"]
        fallback_summary = (
            f"Evidence-linked projection for {issue}: "
            + (", ".join(projected_evidence_ids[:4]) if projected_evidence_ids else "no explicit evidence refs from final map")
        )
        projected_chunk_citations = [
            _citation_out(
                c,
                (evidence_by_chunk or {}).get(c.chunk_id)
                or EvidenceRecord(
                    evidence_id=f"evi:chunk:{c.chunk_id}",
                    audit_id=audit_id,
                    evidence_type="retrieval_chunk",
                    source_ref=c.chunk_id,
                    text_excerpt=c.excerpt,
                    derived_from_evidence_ids=None,
                    article_number=c.article_number,
                    paragraph_ref=c.paragraph_ref,
                ),
            )
            for c in (backing.citations if backing else [])
            if _is_real_evidence_ref(c.chunk_id)
        ]
        projected = FindingOut(
                id=f"projected:{audit_id}:{family}",
                section_id=f"systemic:{issue}",
                status="gap",
                severity=severity_defaults.get(family, "medium"),
                classification="probable_gap",
                finding_type="systemic",
                publish_flag="yes",
                artifact_role="publishable_finding",
                finding_level="systemic",
                publication_state="publishable",
                confidence=backing.confidence if backing and backing.confidence is not None else 0.66,
                confidence_evidence=backing.confidence_evidence if backing and backing.confidence_evidence is not None else 0.72,
                confidence_applicability=backing.confidence_applicability if backing and backing.confidence_applicability is not None else 0.74,
                confidence_article_fit=backing.confidence_article_fit if backing and backing.confidence_article_fit is not None else 0.72,
                confidence_synthesis=backing.confidence_synthesis if backing and backing.confidence_synthesis is not None else 0.7,
                confidence_overall=backing.confidence_overall if backing and backing.confidence_overall is not None else 0.66,
                source_scope=backing.source_scope if backing and backing.source_scope is not None else "full_notice",
                source_scope_confidence=backing.source_scope_confidence if backing and backing.source_scope_confidence is not None else 0.75,
                assertion_level=backing.assertion_level if backing and backing.assertion_level is not None else "probable_document_gap",
                primary_legal_anchor=primary_anchor,
                secondary_legal_anchors=_deserialize_json_list(backing.secondary_legal_anchors) if backing else None,
                citation_summary_text=_sanitize_published_text(backing.citation_summary_text) if backing and backing.citation_summary_text else fallback_summary,
                support_complete=_deserialize_bool_flag(backing.support_complete) if backing else None,
                omission_basis=_deserialize_bool_flag(backing.omission_basis) if backing else None,
                gap_note=_sanitize_published_text(reason) or "Required disclosure gap identified in final decision map.",
                remediation_note=_sanitize_published_text(backing.remediation_note)
                if backing and backing.remediation_note
                else remediation_defaults.get(issue, "Address the identified gap with explicit GDPR-compliant notice language."),
                gap_reasoning=_sanitize_published_text(backing.gap_reasoning) if backing and backing.gap_reasoning else _sanitize_published_text(reason),
                severity_rationale=_sanitize_published_text(backing.severity_rationale) if backing and backing.severity_rationale else "Severity set from family criticality and final disposition.",
                document_evidence_refs=[ref for ref in projected_evidence_ids if (known_evidence_ids is None or ref in known_evidence_ids)] or None,
                citations=(
                    projected_chunk_citations
                    or [
                        CitationOut(
                            chunk_id=(ev.source_ref or ev.evidence_id),
                            evidence_id=ev.evidence_id,
                            source_type=ev.evidence_type,
                            source_ref=ev.source_ref,
                            article_number=ev.article_number or "13",
                            paragraph_ref=ev.paragraph_ref,
                            article_title="Evidence record",
                            excerpt=_sanitize_published_text(ev.text_excerpt) or "",
                        )
                        for ref in projected_evidence_ids
                        for ev in [((evidence_by_id or {}).get(ref))]
                        if ev is not None
                    ]
                ),
        )
        projected = _fill_required_published_fields(projected)
        if not _hydration_missing(projected):
            out.append(projected)
    return out


def _is_real_evidence_ref(value: str) -> bool:
    token = (value or "").strip().lower()
    return bool(token) and not token.startswith("systemic-anchor:")


def _known_evidence_ids(db: Session, audit_id: str) -> set[str]:
    return {row[0] for row in db.query(EvidenceRecord.evidence_id).filter(EvidenceRecord.audit_id == audit_id).all()}


def _evidence_by_chunk_ref(db: Session, audit_id: str) -> dict[str, EvidenceRecord]:
    rows = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.audit_id == audit_id)
        .filter(EvidenceRecord.evidence_type == "retrieval_chunk")
        .all()
    )
    out: dict[str, EvidenceRecord] = {}
    for row in rows:
        if row.source_ref and row.source_ref not in out:
            out[row.source_ref] = row
    if out:
        return out
    # Backfill mapping from persisted finding citations when legacy audits predate evidence upsert.
    citation_rows = (
        db.query(FindingCitation.chunk_id)
        .join(Finding, Finding.id == FindingCitation.finding_id)
        .filter(Finding.audit_id == audit_id)
        .all()
    )
    for (chunk_id,) in citation_rows:
        if not chunk_id or not _is_real_evidence_ref(chunk_id):
            continue
        out[chunk_id] = EvidenceRecord(
            evidence_id=f"evi:chunk:{chunk_id}",
            audit_id=audit_id,
            evidence_type="retrieval_chunk",
            source_ref=chunk_id,
            text_excerpt=None,
            derived_from_evidence_ids=None,
            article_number=None,
            paragraph_ref=None,
        )
    return out


def _evidence_by_id(db: Session, audit_id: str) -> dict[str, EvidenceRecord]:
    rows = db.query(EvidenceRecord).filter(EvidenceRecord.audit_id == audit_id).all()
    return {row.evidence_id: row for row in rows}


def _citation_out(c: FindingCitation, evidence: EvidenceRecord) -> CitationOut:
    return CitationOut(
        chunk_id=c.chunk_id,
        evidence_id=evidence.evidence_id,
        source_type=evidence.evidence_type,
        source_ref=evidence.source_ref,
        article_number=c.article_number,
        paragraph_ref=c.paragraph_ref,
        article_title=c.article_title,
        excerpt=_sanitize_published_text(c.excerpt) or "",
    )


def _hydration_missing(row: FindingOut) -> bool:
    if not row.primary_legal_anchor:
        return True
    if not (row.citation_summary_text or "").strip():
        return True
    if not row.source_scope or not row.assertion_level:
        return True
    if row.confidence_overall is None:
        return True
    if not row.remediation_note:
        return True
    if len(row.citations) == 0:
        return True
    return False


def _issue_key_from_section(section_id: str) -> str | None:
    if section_id.startswith("systemic:"):
        return section_id.split("systemic:", 1)[1]
    return None


def _fill_required_published_fields(row: FindingOut) -> FindingOut:
    issue = _issue_key_from_section(row.section_id)
    family_defaults = {
        "missing_transfer_notice": "State whether personal data are transferred internationally and identify the safeguard or transfer mechanism relied upon.",
        "profiling_disclosure_gap": "If profiling or comparable evaluation occurs, explain the logic involved and significant consequences where required.",
        "controller_processor_role_ambiguity": "Clarify when the organization acts as controller, processor, or similar role across processing contexts.",
    }
    if row.confidence_evidence is None:
        row.confidence_evidence = 0.72
    if row.confidence_applicability is None:
        row.confidence_applicability = 0.74
    if row.confidence_synthesis is None:
        row.confidence_synthesis = 0.7
    if row.severity_rationale is None:
        row.severity_rationale = "Severity set from family criticality, disposition, and evidence confidence."
    if row.gap_reasoning is None:
        row.gap_reasoning = row.gap_note or "Gap confirmed by final disposition map and evidence-linked projection."
    if row.remediation_note is None and issue:
        row.remediation_note = family_defaults.get(issue, "Add explicit GDPR-compliant notice language for the missing disclosure.")
    if row.support_complete is None:
        row.support_complete = len(row.citations) > 0
    if row.omission_basis is None:
        row.omission_basis = row.status in {"gap", "partial"}
    if row.source_scope is None:
        row.source_scope = "full_notice"
    if row.assertion_level is None:
        row.assertion_level = "probable_document_gap"
    return row


def _reconciliation_blockers(
    audit: Audit,
    decision_map: dict[str, dict[str, str | bool | list[str] | float]] | None,
    published_rows: list[Finding],
    projected_rows: list[FindingOut],
    ignored_families: set[str] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if audit.status == "review_required" and (published_rows or projected_rows):
        blockers.append("review_required audit must not expose published findings")
    if not decision_map:
        return blockers
    core_families = ("controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right")
    for family in core_families:
        status = str((decision_map.get(family, {}) or {}).get("status") or "")
        if status in {"unresolved_internal_error", "blocked"} and (published_rows or projected_rows):
            blockers.append(f"core blocker present for {family} while published findings exist")
    for family, item in decision_map.items():
        if family.startswith("_") or not isinstance(item, dict):
            continue
        if str(item.get("publication_recommendation") or "") != "publish":
            continue
        if str(item.get("status") or "") not in {"gap", "referenced_but_unseen"}:
            continue
        if ignored_families and family in ignored_families:
            continue
        has_projection = any(p.id.endswith(f":{family}") for p in projected_rows)
        if not has_projection and not published_rows:
            blockers.append(f"publish recommendation for {family} has no materialized finding")
    return blockers


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
    audit = db.get(Audit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    if audit.status == "review_required":
        raise HTTPException(status_code=409, detail="Published findings blocked: audit requires review")
    decision_map = _load_final_decision_map(db, audit_id)
    backing_rows = db.scalars(
        select(Finding).options(selectinload(Finding.citations)).where(Finding.audit_id == audit_id).order_by(Finding.id.asc())
    ).all()
    known_evidence_ids = _known_evidence_ids(db, audit_id)
    evidence_by_chunk = _evidence_by_chunk_ref(db, audit_id)
    evidence_by_id = _evidence_by_id(db, audit_id)
    if decision_map and not _publication_allowed_from_map(decision_map):
        raise HTTPException(status_code=409, detail="Published findings blocked: final decision map disallows publication")
    projected = _project_published_findings_from_map(
        audit_id,
        decision_map,
        backing_rows,
        known_evidence_ids,
        evidence_by_chunk,
        evidence_by_id,
    ) if decision_map else []
    hydration_filtered_families: set[str] = set()
    if decision_map:
        projectable_families = {
            "controller_identity_contact",
            "legal_basis",
            "retention",
            "rights_notice",
            "complaint_right",
            "transfer",
            "profiling",
            "role_ambiguity",
            "article14_source",
            "recipients",
            "special_category",
            "dpo_contact",
        }
        expected_families = {
            family
            for family, item in decision_map.items()
            if not family.startswith("_")
            and isinstance(item, dict)
            and str(item.get("publication_recommendation") or "") == "publish"
            and str(item.get("status") or "") in {"gap", "referenced_but_unseen"}
            and family in projectable_families
        }
        published_families = {p.id.rsplit(":", 1)[-1] for p in projected}
        hydration_filtered_families = expected_families - published_families
    if projected:
        blockers = _reconciliation_blockers(audit, decision_map, [], projected, hydration_filtered_families)
        if blockers:
            raise HTTPException(status_code=409, detail=f"Published findings blocked by reconciliation validator: {', '.join(blockers)}")
        return projected
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
        blockers = _reconciliation_blockers(audit, decision_map, [], [], hydration_filtered_families)
        if blockers:
            raise HTTPException(status_code=409, detail=f"Published findings blocked by reconciliation validator: {', '.join(blockers)}")
        return []
    blockers = _reconciliation_blockers(audit, decision_map, rows, [])
    if blockers:
        raise HTTPException(status_code=409, detail=f"Published findings blocked by reconciliation validator: {', '.join(blockers)}")

    out: list[FindingOut] = []
    evidence_ids = known_evidence_ids
    seen: set[str] = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        out.append(
            _fill_required_published_fields(FindingOut(
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
                severity_rationale=_sanitize_published_text(row.severity_rationale),
                primary_legal_anchor=_deserialize_json_list(row.primary_legal_anchor),
                secondary_legal_anchors=_deserialize_json_list(row.secondary_legal_anchors),
                document_evidence_refs=[
                    ref for ref in (_deserialize_json_list(row.document_evidence_refs) or []) if ref in evidence_ids
                ]
                or None,
                citation_summary_text=_sanitize_published_text(row.citation_summary_text),
                support_complete=_deserialize_bool_flag(row.support_complete),
                omission_basis=_deserialize_bool_flag(row.omission_basis),
                source_scope=row.source_scope,
                source_scope_confidence=row.source_scope_confidence,
                referenced_unseen_sections=_deserialize_json_list(row.referenced_unseen_sections),
                assertion_level=row.assertion_level,
                gap_note=_sanitize_published_text(
                    _apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[0]
                ),
                remediation_note=_sanitize_published_text(
                    _apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[1]
                ),
                citations=[
                    _citation_out(c, evidence_by_chunk.get(c.chunk_id))
                    for c in row.citations
                    if _is_real_evidence_ref(c.chunk_id)
                    and (f"evi:chunk:{c.chunk_id}" in evidence_ids or c.chunk_id in evidence_by_chunk)
                    and c.chunk_id in evidence_by_chunk
                ],
            ))
        )
    return [row for row in out if not _hydration_missing(row)]


@router.get("/audits/{audit_id}/analysis", response_model=list[AnalysisItemOut])
def get_analysis(
    audit_id: str,
    status: str | None = Query(default=None, alias="status"),
    issue_type: str | None = Query(default=None),
    artifact_role: str | None = Query(default=None),
    section_id: str | None = Query(default=None),
    analysis_stage: str | None = Query(default=None),
    debug: bool = Query(default=False),
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
    if not debug:
        rows = [row for row in rows if not row.section_id.startswith("ledger:")]
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
            status_candidate=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[0],
            classification_candidate=row.classification_candidate,
            artifact_role=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[1],
            finding_level_candidate=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[2],
            publication_state_candidate=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[3],
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
def get_review(audit_id: str, debug: bool = Query(default=False), db: Session = Depends(get_db)) -> list[ReviewItemOut]:
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
    if not debug:
        findings = [row for row in findings if not row.section_id.startswith("ledger:")]
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
    if not debug:
        analysis_rows = [row for row in analysis_rows if not row.section_id.startswith("ledger:")]
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
            status=_normalize_internal_state(
                row.classification,
                row.status,
                row.artifact_role,
                row.finding_level,
                row.publication_state,
            )[0],
            classification=row.classification,
            artifact_role=_normalize_internal_state(
                row.classification,
                row.status,
                row.artifact_role,
                row.finding_level,
                row.publication_state,
            )[1],
            finding_level=_normalize_internal_state(
                row.classification,
                row.status,
                row.artifact_role,
                row.finding_level,
                row.publication_state,
            )[2],
            publication_state=_normalize_internal_state(
                row.classification,
                row.status,
                row.artifact_role,
                row.finding_level,
                row.publication_state,
            )[3],
            suppression_reason=_sanitize_review_text(row.gap_note, debug=debug) if row.publication_state in {"blocked", "internal_only"} else None,
            completeness_map=row.legal_requirement if row.legal_requirement and "completeness" in row.legal_requirement else None,
            gap_note=_sanitize_review_text(
                _apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[0], debug=debug
            ),
            remediation_note=_sanitize_review_text(
                _apply_family_fallback(_issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note)[1], debug=debug
            ),
        )
        for row in findings
    )
    out.extend(
        ReviewItemOut(
            item_kind="analysis",
            id=row.id,
            section_id=row.section_id,
            issue_type=row.issue_type,
            status=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[0],
            classification=row.classification_candidate,
            artifact_role=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[1],
            finding_level=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[2],
            publication_state=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[3],
            suppression_reason=_sanitize_review_text(row.suppression_reason, debug=debug),
            completeness_map=row.retrieval_summary if row.analysis_type == "completeness_outcome" else None,
            gap_note=_sanitize_review_text(_apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[0], debug=debug),
            remediation_note=_sanitize_review_text(_apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[1], debug=debug),
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
            blocked_core_artifact = any(
                f.publication_state in {"blocked", "internal_only"} and (_issue_from_finding_section(f.section_id) or "").startswith("missing_")
                for f in findings
            )
            final_status = item.get("status")
            if final_status == "satisfied" and blocked_core_artifact:
                final_status = "not_assessable"
            out.append(
                ReviewItemOut(
                    item_kind="review_block",
                    id=f"core:{duty}",
                    section_id="review:core_duties",
                    status=None,
                    review_group="core_duties",
                    duty=duty,
                    triggered=bool(item.get("triggered", True)),
                    final_disposition=final_status,
                    reason=_sanitize_review_text(item.get("reasoning"), debug=debug),
                    source_scope_dependency=str(item.get("source_scope_dependency") or "high"),
                    publication_recommendation=str(item.get("publication_recommendation") or "internal_only"),
                )
            )
        specialist_triggers = {
            "transfer": ("transfer", "transfer"),
            "profiling": ("profiling", "profiling"),
            "role_ambiguity": ("role_ambiguity", "role_ambiguity"),
            "article14_source": ("article14_source", "article14"),
            "recipients": ("recipients", "recipients"),
            "special_category": ("special_category", "special_category"),
            "dpo_contact": ("dpo_contact", "dpo_contact"),
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
                    triggered=bool(item.get("triggered", item.get("status") != "satisfied")),
                    final_disposition=item.get("status"),
                    reason=_sanitize_review_text(item.get("reasoning"), debug=debug),
                    source_scope_dependency=str(item.get("source_scope_dependency") or "low"),
                    publication_recommendation=str(item.get("publication_recommendation") or "internal_only"),
                )
            )
    return out


@router.get("/audits/{audit_id}/review/grouped")
def get_review_grouped(audit_id: str, debug: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, list[ReviewItemOut]]:
    items = get_review(audit_id, debug=debug, db=db)
    grouped: dict[str, list[ReviewItemOut]] = {
        "publication_blockers": [],
        "core_duty_resolution": [],
        "specialist_family_resolution": [],
        "publishable_findings": [],
        "internal_unresolved_items": [],
        "diagnostics": [],
    }
    for item in items:
        if item.item_kind == "review_block" and item.review_group == "core_duties":
            grouped["core_duty_resolution"].append(item)
            if item.final_disposition not in {"satisfied", None}:
                grouped["publication_blockers"].append(item)
            continue
        if item.item_kind == "review_block" and item.review_group == "specialist_families":
            grouped["specialist_family_resolution"].append(item)
            if item.final_disposition not in {"satisfied", None}:
                grouped["publication_blockers"].append(item)
            continue
        if item.item_kind == "finding" and item.publication_state == "publishable":
            grouped["publishable_findings"].append(item)
            continue
        if item.classification == "diagnostic_internal_only":
            grouped["diagnostics"].append(item)
            continue
        if item.status in {"not applicable", "needs review"} or item.publication_state in {"blocked", "internal_only"}:
            grouped["internal_unresolved_items"].append(item)
            continue
    if debug:
        grouped["diagnostics"].extend(
            [
                item
                for item in items
                if item.item_kind in {"analysis", "finding"} and item not in grouped["diagnostics"]
            ]
        )
    return grouped


@router.post("/audits/{audit_id}/report", response_model=ReportTriggerOut)
def create_report(audit_id: str, db: Session = Depends(get_db)) -> ReportTriggerOut:
    audit = db.get(Audit, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    if audit.status != "complete":
        if audit.status == "review_required":
            raise HTTPException(status_code=409, detail="Report generation blocked: audit requires reviewer resolution")
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
