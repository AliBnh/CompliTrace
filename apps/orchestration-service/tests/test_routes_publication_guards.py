from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import (
    _apply_family_fallback,
    _sanitize_published_text,
    _sanitize_review_text,
    create_report,
    get_findings,
    get_review,
    get_review_grouped,
)
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
        citation_summary_text="transfer disclosure summary",
        support_complete="true",
        omission_basis="true",
        document_evidence_refs='["evi:policy:sec-transfer"]',
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
    assert findings[0].citations[0].evidence_id == "evi:chunk:transfer-chunk-1"
    assert findings[0].citations[0].source_type == "retrieval_chunk"


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
        primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        citation_summary_text="core summary",
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        confidence_overall=0.72,
        remediation_note="Add missing disclosure language.",
        document_evidence_refs='["evi:policy:sec-1"]',
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
            evidence_id="evi:policy:sec-1",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="sec-1",
            text_excerpt="policy section",
        )
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


def test_get_findings_projects_from_evidence_refs_when_supporting_citations_are_absent(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
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
            citation_summary_text="transfer summary",
            support_complete="true",
            omission_basis="true",
            remediation_note="State transfer safeguards.",
            document_evidence_refs='["evi:policy:sec-transfer"]',
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
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    assert len(rows) == 1
    assert rows[0].section_id == "systemic:missing_transfer_notice"
    assert rows[0].citations[0].evidence_id == "evi:policy:sec-transfer"


def test_get_findings_backfills_evidence_linkage_from_citations_when_evidence_rows_missing(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    finding = Finding(
        audit_id=audit.id,
        section_id="sec-legacy",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="local",
        publish_flag="yes",
        publication_state="publishable",
        primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        citation_summary_text="legacy summary",
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        confidence_overall=0.71,
        remediation_note="Add missing legal basis disclosure.",
        document_evidence_refs='["evi:policy:sec-legacy"]',
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=finding.id,
            chunk_id="legacy-chunk-1",
            article_number="13",
            paragraph_ref="1(c)",
            article_title="Information to be provided",
            excerpt="Legacy citation text",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:policy:sec-legacy",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="sec-legacy",
            text_excerpt="policy section",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    assert len(rows) == 1
    assert rows[0].citations[0].evidence_id == "evi:chunk:legacy-chunk-1"
    assert rows[0].citations[0].source_ref == "legacy-chunk-1"


def test_projected_findings_keep_non_null_citation_linkage_when_chunk_evidence_rows_missing(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    projected_backing = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_rights_notice",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="blocked",
        confidence=0.8,
        confidence_article_fit=0.77,
        confidence_overall=0.79,
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(2)(b)"]',
        citation_summary_text="rights missing",
        remediation_note="Add rights transparency details.",
    )
    db_session.add(projected_backing)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=projected_backing.id,
            chunk_id="rights-legacy-chunk",
            article_number="13",
            paragraph_ref="2(b)",
            article_title="Rights",
            excerpt="Data subject rights text.",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"rights_notice":{"status":"gap","publication_recommendation":"publish","reasoning":"rights disclosure missing"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    assert len(rows) == 1
    assert rows[0].citations[0].evidence_id == "evi:chunk:rights-legacy-chunk"
    assert rows[0].citations[0].source_type == "retrieval_chunk"
    assert rows[0].citations[0].source_ref == "rights-legacy-chunk"


def test_specialist_review_publish_blocks_project_to_published_with_rich_hydration(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add_all(
        [
            Finding(
                audit_id=audit.id,
                section_id="systemic:missing_transfer_notice",
                status="gap",
                severity="high",
                classification="probable_gap",
                finding_type="systemic",
                publication_state="blocked",
                primary_legal_anchor='["GDPR Article 13(1)(f)"]',
                document_evidence_refs='["evi:policy:transfer"]',
            ),
            Finding(
                audit_id=audit.id,
                section_id="systemic:profiling_disclosure_gap",
                status="gap",
                severity="high",
                classification="probable_gap",
                finding_type="systemic",
                publication_state="blocked",
                primary_legal_anchor='["GDPR Article 13(2)(f)"]',
                document_evidence_refs='["evi:policy:profiling"]',
            ),
            Finding(
                audit_id=audit.id,
                section_id="systemic:controller_processor_role_ambiguity",
                status="gap",
                severity="medium",
                classification="probable_gap",
                finding_type="systemic",
                publication_state="blocked",
                primary_legal_anchor='["GDPR Article 13(1)(a)"]',
                document_evidence_refs='["evi:policy:roles"]',
            ),
            Finding(
                audit_id=audit.id,
                section_id="ledger:final-disposition",
                status="not applicable",
                severity=None,
                legal_requirement="suppression_validator=final_disposition_map",
                gap_reasoning=(
                    '{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer missing","positive_evidence_ids":["evi:policy:transfer"]},'
                    '"profiling":{"status":"gap","publication_recommendation":"publish","reasoning":"profiling missing","positive_evidence_ids":["evi:policy:profiling"]},'
                    '"role_ambiguity":{"status":"gap","publication_recommendation":"publish","reasoning":"role allocation missing","positive_evidence_ids":["evi:policy:roles"]}}'
                ),
                publish_flag="no",
                publication_state="internal_only",
                finding_type="supporting_evidence",
                artifact_role="support_only",
                finding_level="none",
            ),
            EvidenceRecord(evidence_id="evi:policy:transfer", audit_id=audit.id, evidence_type="policy_section", source_ref="transfer", text_excerpt="transfer evidence"),
            EvidenceRecord(evidence_id="evi:policy:profiling", audit_id=audit.id, evidence_type="policy_section", source_ref="profiling", text_excerpt="profiling evidence"),
            EvidenceRecord(evidence_id="evi:policy:roles", audit_id=audit.id, evidence_type="policy_section", source_ref="roles", text_excerpt="roles evidence"),
        ]
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    issues = {r.section_id for r in rows}
    assert "systemic:missing_transfer_notice" in issues
    assert "systemic:profiling_disclosure_gap" in issues
    assert "systemic:controller_processor_role_ambiguity" in issues
    for row in rows:
        assert row.confidence_evidence is not None
        assert row.confidence_applicability is not None
        assert row.confidence_synthesis is not None
        assert row.severity_rationale is not None
        assert row.gap_reasoning is not None
        assert row.citations
        assert all(c.evidence_id is not None and c.source_type is not None and c.source_ref is not None for c in row.citations)


def test_sanitize_review_text_strips_internal_markers_when_not_debug():
    raw = "Systemic finding withheld from publication pending complete legal/document support package [withheld by final publication validator]"
    cleaned = _sanitize_review_text(raw, debug=False)
    assert cleaned is not None
    assert "withheld by final publication validator" not in cleaned
    assert "not yet finalized for publication" in cleaned


def test_apply_family_fallback_rewrites_generic_unresolved_copy_for_purpose_mapping():
    gap, remediation = _apply_family_fallback(
        "purpose_specificity_gap",
        "Not assessable from excerpt: additional documentary context is required.",
        "Provide complete notice excerpts and rerun legal qualification.",
    )
    assert gap is not None and "category-to-purpose mapping" in gap
    assert remediation is not None and "Map each key data category" in remediation


def test_published_citation_excerpt_uses_clean_renderer_not_internal_phrase(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    finding = Finding(
        audit_id=audit.id,
        section_id="sec-1",
        status="gap",
        severity="medium",
        classification="probable_gap",
        finding_type="local",
        publication_state="publishable",
        publish_flag="yes",
        confidence=0.7,
        confidence_evidence=0.7,
        confidence_applicability=0.7,
        confidence_synthesis=0.7,
        confidence_overall=0.7,
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(1)(a)"]',
        citation_summary_text="summary",
        gap_note="gap",
        remediation_note="fix",
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=finding.id,
            chunk_id="chunk-internal",
            article_number="13",
            paragraph_ref="1(a)",
            article_title="Controller",
            excerpt="withheld by final publication validator",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:chunk-internal",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="chunk-internal",
            text_excerpt="Controller contact details are listed in policy text.",
            article_number="13",
            paragraph_ref="1(a)",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    assert rows
    excerpt = rows[0].citations[0].excerpt.lower()
    assert "withheld" not in excerpt
    assert "validator" not in excerpt


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


def test_get_review_includes_purpose_mapping_block_from_decision_map(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"purpose_mapping":{"status":"gap","publication_recommendation":"publish","reasoning":"Category-to-purpose mapping is too broad"}}',
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
    assert "purpose_mapping" in families


def test_projected_findings_include_section_level_high_signal_findings(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    local_transfer = Finding(
        audit_id=audit.id,
        section_id="1.3 Territorial Reach",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="local",
        publication_state="publishable",
        publish_flag="yes",
        confidence=0.78,
        confidence_evidence=0.76,
        confidence_applicability=0.74,
        confidence_synthesis=0.72,
        source_scope="full_notice",
        source_scope_confidence=0.8,
        assertion_level="probable_document_gap",
        obligation_under_review="transfer",
        policy_evidence_excerpt="We transfer personal data outside the EEA.",
        legal_requirement="Article 13(1)(f)/14(1)(f) transfer disclosure obligations.",
        gap_reasoning="Section transfer wording omits mechanism.",
        gap_note="Transfer context is visible but safeguards are not disclosed.",
        remediation_note="Disclose SCC/adequacy mechanism.",
    )
    db_session.add(local_transfer)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=local_transfer.id,
            chunk_id="transfer-local-chunk",
            article_number="13",
            paragraph_ref="1(f)",
            article_title="Transfer disclosure",
            excerpt="Transfer disclosure excerpt.",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer missing"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:transfer-local-chunk",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="transfer-local-chunk",
            text_excerpt="chunk evidence",
            article_number="13",
            paragraph_ref="1(f)",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    by_section = {r.section_id: r for r in rows}
    assert "1.3 Territorial Reach" in by_section
    assert "section=1.3 Territorial Reach;" in (by_section["1.3 Territorial Reach"].gap_reasoning or "")


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
