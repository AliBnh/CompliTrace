from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import _sanitize_published_text, _sanitize_review_text, create_report, get_findings, get_review, get_review_grouped
from app.db.base import Base
from app.models.audit import Audit, EvidenceRecord, Finding, FindingCitation


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with SessionLocal() as db:
        yield db


def _create_audit(db: Session, *, status: str) -> Audit:
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status=status)
    db.add(audit)
    db.commit()
    return audit


def test_get_findings_blocks_publication_when_review_required(db_session: Session):
    audit = _create_audit(db_session, status="review_required")

    with pytest.raises(HTTPException) as exc:
        get_findings(audit.id, db_session)

    assert exc.value.status_code == 409
    assert "requires review" in str(exc.value.detail)


def test_create_report_blocks_generation_when_review_required(db_session: Session):
    audit = _create_audit(db_session, status="review_required")

    with pytest.raises(HTTPException) as exc:
        create_report(audit.id, db_session)

    assert exc.value.status_code == 409
    assert "reviewer resolution" in str(exc.value.detail)


def test_sanitize_published_text_strips_internal_markers():
    raw = (
        "Gap text [withheld by final publication validator] "
        "suppression_validator=final_disposition_map "
        "state_invariant_violation:blocked_publish_yes"
    )

    cleaned = _sanitize_published_text(raw)

    assert cleaned == "Gap text"


def test_get_findings_projects_publishable_specialist_gaps_from_decision_map(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    projected_backing = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_transfer_notice",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="blocked",
        confidence=0.81,
        confidence_article_fit=0.77,
        confidence_overall=0.8,
        source_scope="full_notice",
        source_scope_confidence=0.88,
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(1)(f)"]',
        remediation_note="Add transfer safeguard mechanisms.",
    )
    db_session.add(projected_backing)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=projected_backing.id,
            chunk_id="transfer-chunk-1",
            article_number="13",
            paragraph_ref="1(f)",
            article_title="Transfer disclosure",
            excerpt="Transfers may occur outside the EEA.",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer safeguards missing","positive_evidence_ids":["evi:policy:sec-transfer"]}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:policy:sec-transfer",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="sec-transfer",
            text_excerpt="transfer evidence",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:transfer-chunk-1",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="transfer-chunk-1",
            text_excerpt="Transfers may occur outside the EEA.",
        )
    )
    db_session.commit()

    findings = get_findings(audit.id, db_session)

    assert len(findings) == 1
    assert findings[0].section_id == "systemic:missing_transfer_notice"
    assert findings[0].document_evidence_refs == ["evi:policy:sec-transfer"]
    assert findings[0].confidence_overall == 0.8
    assert findings[0].primary_legal_anchor == ["GDPR Article 13(1)(f)"]
    assert [c.chunk_id for c in findings[0].citations] == ["transfer-chunk-1"]


def test_get_findings_blocks_when_decision_map_disallows_publication(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"_controls":{"publication_allowed":false}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        get_findings(audit.id, db_session)
    assert exc.value.status_code == 409


def test_get_findings_blocks_when_publish_recommendation_has_no_materialized_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"unmapped_family":{"status":"gap","publication_recommendation":"publish","reasoning":"x"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        get_findings(audit.id, db_session)
    assert exc.value.status_code == 409


def test_get_findings_filters_synthetic_systemic_anchor_citations(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    finding = Finding(
        audit_id=audit.id,
        section_id="sec-1",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="local",
        publish_flag="yes",
        publication_state="publishable",
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add_all(
        [
            FindingCitation(
                finding_id=finding.id,
                chunk_id="systemic-anchor:systemic:missing_legal_basis",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Information to be provided",
                excerpt="synthetic",
            ),
            FindingCitation(
                finding_id=finding.id,
                chunk_id="sec:real-evidence-1",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Information to be provided",
                excerpt="real",
            ),
        ]
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:sec:real-evidence-1",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="sec:real-evidence-1",
            text_excerpt="real",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    assert len(rows) == 1
    assert [c.chunk_id for c in rows[0].citations] == ["sec:real-evidence-1"]


def test_sanitize_review_text_strips_internal_markers_when_not_debug():
    raw = "Systemic finding withheld from publication pending complete legal/document support package [withheld by final publication validator]"
    cleaned = _sanitize_review_text(raw, debug=False)
    assert cleaned is not None
    assert "withheld by final publication validator" not in cleaned
    assert "not yet finalized for publication" in cleaned


def test_get_review_includes_recipients_and_dpo_blocks_from_decision_map(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"recipients":{"status":"gap","publication_recommendation":"publish","reasoning":"Recipients not clearly disclosed"},"dpo_contact":{"status":"not_assessable","publication_recommendation":"internal_only","reasoning":"DPO applicability uncertain"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_review(audit.id, debug=False, db=db_session)
    families = {r.family for r in rows if r.item_kind == "review_block" and r.review_group == "specialist_families"}
    assert "recipients" in families
    assert "dpo_contact" in families


def test_get_review_grouped_returns_expected_sections(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="systemic:missing_legal_basis",
            status="gap",
            severity="high",
            classification="probable_gap",
            publish_flag="yes",
            publication_state="publishable",
            finding_type="systemic",
            artifact_role="publishable_finding",
            finding_level="systemic",
        )
    )
    db_session.commit()

    grouped = get_review_grouped(audit.id, debug=False, db=db_session)
    assert set(grouped.keys()) == {
        "publication_blockers",
        "core_duty_resolution",
        "specialist_family_resolution",
        "publishable_findings",
        "internal_unresolved_items",
        "diagnostics",
    }
