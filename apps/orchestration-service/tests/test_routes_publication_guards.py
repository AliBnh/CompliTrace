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
    assert findings[0].document_evidence_refs is not None
    assert "evi:policy:sec-transfer" in findings[0].document_evidence_refs
    assert "evi:chunk:transfer-chunk-1" in findings[0].document_evidence_refs
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


def test_get_findings_emits_publication_blocker_for_unmaterialized_publishable_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer safeguards missing",'
                '"blocker_reason":"missing evidence linkage","missing_requirements":["document_evidence_refs","citations"]}}'
            ),
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
    blocker = rows[0]
    assert blocker.classification == "publication_blocked"
    assert blocker.publication_blocked is True
    assert blocker.issue_key == "missing_transfer_notice"
    assert "missing evidence" in (blocker.blocker_reason or "")
    assert blocker.missing_requirements is not None
    assert "citations" in blocker.missing_requirements
    assert "document_evidence_refs" in blocker.missing_requirements


def test_get_findings_projects_controller_identity_contact_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    backing = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_controller_contact",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="blocked",
        confidence=0.8,
        confidence_article_fit=0.78,
        confidence_overall=0.79,
        source_scope="full_notice",
        source_scope_confidence=0.9,
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(1)(a)","GDPR Article 14(1)(a)"]',
        citation_summary_text="controller contact summary",
        support_complete="true",
        omission_basis="true",
        remediation_note="Add controller contact route.",
        document_evidence_refs='["evi:policy:sec-controller"]',
    )
    db_session.add(backing)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=backing.id,
            chunk_id="controller-chunk-1",
            article_number="13",
            paragraph_ref="1(a)",
            article_title="Controller details",
            excerpt="Identity and contact details shall be provided.",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"controller_identity_contact":{"status":"gap","publication_recommendation":"publish","reasoning":"controller contact missing","positive_evidence_ids":["evi:policy:sec-controller"]}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:policy:sec-controller",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="sec-controller",
            text_excerpt="controller section",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:controller-chunk-1",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="controller-chunk-1",
            text_excerpt="Identity and contact details shall be provided.",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    assert rows
    assert any(row.section_id == "systemic:missing_controller_contact" and row.classification != "publication_blocked" for row in rows)
    assert rows[0].citations[0].evidence_id == "evi:chunk:controller-chunk-1"


def test_get_findings_emits_blockers_for_all_required_publish_families_when_unmaterialized(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{'
                '"controller_identity_contact":{"status":"gap","publication_recommendation":"publish","reasoning":"controller missing","blocker_reason":"incomplete hydration"},'
                '"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer missing","blocker_reason":"missing evidence linkage"},'
                '"profiling":{"status":"gap","publication_recommendation":"publish","reasoning":"profiling missing","blocker_reason":"missing section traceability"},'
                '"role_ambiguity":{"status":"gap","publication_recommendation":"publish","reasoning":"role ambiguity","blocker_reason":"incomplete hydration"},'
                '"recipients":{"status":"gap","publication_recommendation":"publish","reasoning":"recipients missing","blocker_reason":"missing evidence linkage"},'
                '"purpose_mapping":{"status":"gap","publication_recommendation":"publish","reasoning":"purpose mapping missing","blocker_reason":"confidence inconsistency"}'
                '}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    blocker_rows = [row for row in rows if row.classification == "publication_blocked"]
    assert len(blocker_rows) == 6
    assert {row.issue_key for row in blocker_rows} == {
        "missing_controller_contact",
        "missing_transfer_notice",
        "profiling_disclosure_gap",
        "controller_processor_role_ambiguity",
        "recipients_disclosure_gap",
        "purpose_specificity_gap",
    }


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
    assert rows[0].classification == "publication_blocked"
    assert rows[0].blocker_reason == "missing evidence linkage"
    assert rows[0].missing_requirements is not None
    assert "document_evidence_refs" in rows[0].missing_requirements


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
                section_id="systemic:recipients_disclosure_gap",
                status="gap",
                severity="medium",
                classification="probable_gap",
                finding_type="systemic",
                publication_state="blocked",
                primary_legal_anchor='["GDPR Article 13(1)(e)"]',
                document_evidence_refs='["evi:policy:recipients"]',
            ),
            Finding(
                audit_id=audit.id,
                section_id="systemic:purpose_specificity_gap",
                status="gap",
                severity="medium",
                classification="probable_gap",
                finding_type="systemic",
                publication_state="blocked",
                primary_legal_anchor='["GDPR Article 13(1)(c)"]',
                document_evidence_refs='["evi:policy:purpose"]',
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
                    '"role_ambiguity":{"status":"gap","publication_recommendation":"publish","reasoning":"role allocation missing","positive_evidence_ids":["evi:policy:roles"]},'
                    '"recipients":{"status":"gap","publication_recommendation":"publish","reasoning":"recipients missing","positive_evidence_ids":["evi:policy:recipients"]},'
                    '"purpose_mapping":{"status":"gap","publication_recommendation":"publish","reasoning":"purpose mapping missing","positive_evidence_ids":["evi:policy:purpose"]}}'
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
            EvidenceRecord(evidence_id="evi:policy:recipients", audit_id=audit.id, evidence_type="policy_section", source_ref="recipients", text_excerpt="recipient evidence"),
            EvidenceRecord(evidence_id="evi:policy:purpose", audit_id=audit.id, evidence_type="policy_section", source_ref="purpose", text_excerpt="purpose evidence"),
        ]
    )
    db_session.commit()

    rows = get_findings(audit.id, db_session)
    issues = {r.section_id for r in rows}
    assert "systemic:missing_transfer_notice" in issues
    assert "systemic:profiling_disclosure_gap" in issues
    assert "systemic:controller_processor_role_ambiguity" in issues
    assert "systemic:recipients_disclosure_gap" in issues
    assert "systemic:purpose_specificity_gap" in issues
    for row in rows:
        assert row.confidence_evidence is not None
        assert row.confidence_applicability is not None
        assert row.confidence_synthesis is not None
        assert row.severity_rationale is not None
        assert row.gap_reasoning is not None
        assert row.document_evidence_refs is not None
        assert row.citations
        assert all(c.evidence_id is not None and c.source_type is not None and c.source_ref is not None for c in row.citations)
        assert all(c.source_type != "policy_summary" for c in row.citations)


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
    reasoning = by_section["1.3 Territorial Reach"].gap_reasoning or ""
    assert "In section 1.3 Territorial Reach" in reasoning
    assert "Applicable GDPR duty:" in reasoning and "Breach finding:" in reasoning and "Required remediation:" in reasoning


def test_section_level_findings_exist_for_transfer_profiling_and_role_ambiguity(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    local_rows = [
        ("1.3 Territorial Reach", "transfer", "Transfer safeguard language missing", "transfer-chunk"),
        ("2.4 Usage, Behavioral, and Product Interaction Data", "profiling", "Profiling logic not clearly disclosed", "profiling-chunk"),
        ("1.2 Audience and Application", "controller/processor", "Role allocation is ambiguous", "role-chunk"),
    ]
    for section_id, obligation, gap_note, chunk in local_rows:
        finding = Finding(
            audit_id=audit.id,
            section_id=section_id,
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
            obligation_under_review=obligation,
            policy_evidence_excerpt=gap_note,
            legal_requirement="GDPR transparency rule",
            gap_reasoning=gap_note,
            gap_note=gap_note,
            remediation_note="Add compliant disclosure text.",
            document_evidence_refs='["evi:policy:' + section_id + '"]',
        )
        db_session.add(finding)
        db_session.flush()
        db_session.add(
            FindingCitation(
                finding_id=finding.id,
                chunk_id=chunk,
                article_number="13",
                paragraph_ref=None,
                article_title="Transparency",
                excerpt=gap_note,
            )
        )
        db_session.add(EvidenceRecord(evidence_id=f"evi:chunk:{chunk}", audit_id=audit.id, evidence_type="retrieval_chunk", source_ref=chunk, text_excerpt=gap_note, article_number="13"))
        db_session.add(EvidenceRecord(evidence_id=f"evi:policy:{section_id}", audit_id=audit.id, evidence_type="policy_section", source_ref=section_id, text_excerpt=gap_note))
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer missing"},"profiling":{"status":"gap","publication_recommendation":"publish","reasoning":"profiling missing"},"role_ambiguity":{"status":"gap","publication_recommendation":"publish","reasoning":"role missing"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, db_session)
    section_ids = {r.section_id for r in rows}
    assert "1.3 Territorial Reach" in section_ids
    assert "2.4 Usage, Behavioral, and Product Interaction Data" in section_ids
    assert "1.2 Audience and Application" in section_ids


def test_published_clear_omissions_use_non_compliant_conclusion_class(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    finding = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_legal_basis",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="publishable",
        publish_flag="yes",
        confidence=0.8,
        confidence_evidence=0.8,
        confidence_applicability=0.8,
        confidence_synthesis=0.8,
        confidence_overall=0.8,
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        citation_summary_text="legal basis missing",
        gap_note="Lawful basis disclosure is missing.",
        remediation_note="Add lawful basis by purpose.",
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=finding.id,
            chunk_id="lb-chunk",
            article_number="13",
            paragraph_ref="1(c)",
            article_title="Legal basis",
            excerpt="controller shall provide legal basis",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:lb-chunk",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="lb-chunk",
            text_excerpt="legal basis evidence",
            article_number="13",
            paragraph_ref="1(c)",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, db_session)
    assert rows[0].classification == "non_compliant"


def test_anchor_sanity_corrects_mismatched_transfer_anchor_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer context visible but safeguards missing"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="systemic:missing_transfer_notice",
            status="gap",
            severity="high",
            classification="probable_gap",
            finding_type="systemic",
            publication_state="blocked",
            primary_legal_anchor='["GDPR Article 13(1)(c)"]',
            document_evidence_refs='["evi:policy:transfer"]',
            remediation_note="Add transfer safeguards disclosure.",
        )
    )
    db_session.flush()
    transfer_finding = db_session.query(Finding).filter(Finding.audit_id == audit.id, Finding.section_id == "systemic:missing_transfer_notice").first()
    db_session.add(
        FindingCitation(
            finding_id=transfer_finding.id,
            chunk_id="transfer-anchor-chunk",
            article_number="44",
            paragraph_ref=None,
            article_title="Transfers",
            excerpt="transfer safeguards text",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:policy:transfer",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="transfer",
            text_excerpt="transfer evidence",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:transfer-anchor-chunk",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="transfer-anchor-chunk",
            text_excerpt="transfer safeguards text",
            article_number="44",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, db_session)
    transfer = next(r for r in rows if r.section_id == "systemic:missing_transfer_notice")
    anchors = transfer.primary_legal_anchor or []
    assert any("13(1)(f)" in a for a in anchors)
    assert any("14(1)(f)" in a for a in anchors)


def test_projected_reasoning_avoids_internal_engine_concepts(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    backing = Finding(
        audit_id=audit.id,
        section_id="systemic:purpose_specificity_gap",
        status="gap",
        severity="medium",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="blocked",
        primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        document_evidence_refs='["evi:policy:purpose"]',
        remediation_note="Map categories to purposes.",
    )
    db_session.add(backing)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=backing.id,
            chunk_id="purpose-chunk",
            article_number="13",
            paragraph_ref="1(c)",
            article_title="Purpose mapping",
            excerpt="purpose text",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"purpose_mapping":{"status":"gap","publication_recommendation":"publish","reasoning":"Omission basis confirmed via document obligation map"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(EvidenceRecord(evidence_id="evi:policy:purpose", audit_id=audit.id, evidence_type="policy_section", source_ref="purpose", text_excerpt="purpose evidence"))
    db_session.add(EvidenceRecord(evidence_id="evi:chunk:purpose-chunk", audit_id=audit.id, evidence_type="retrieval_chunk", source_ref="purpose-chunk", text_excerpt="purpose text", article_number="13"))
    db_session.commit()
    rows = get_findings(audit.id, db_session)
    assert rows
    text = " ".join((r.gap_reasoning or "").lower() for r in rows)
    assert "obligation map" not in text
    assert "suppression" not in text
    assert "validator" not in text
    assert "fact:" in text
    assert "law:" in text
    assert "breach:" in text


def test_controller_contact_published_reasoning_uses_fact_rule_application(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    backing = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_controller_contact",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="blocked",
        primary_legal_anchor='["GDPR Article 13(1)(a)"]',
        document_evidence_refs='["evi:policy:controller"]',
        remediation_note="Add privacy contact details.",
    )
    db_session.add(backing)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=backing.id,
            chunk_id="controller-chunk",
            article_number="13",
            paragraph_ref="1(a)",
            article_title="Controller contact",
            excerpt="controller details",
        )
    )
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"controller_identity_contact":{"status":"gap","publication_recommendation":"publish","reasoning":"company named but no contact route"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(EvidenceRecord(evidence_id="evi:policy:controller", audit_id=audit.id, evidence_type="policy_section", source_ref="controller", text_excerpt="company named without contact route"))
    db_session.add(EvidenceRecord(evidence_id="evi:chunk:controller-chunk", audit_id=audit.id, evidence_type="retrieval_chunk", source_ref="controller-chunk", text_excerpt="controller details", article_number="13"))
    db_session.commit()
    rows = get_findings(audit.id, db_session)
    controller = next(r for r in rows if "controller_contact" in r.section_id)
    reasoning = (controller.gap_reasoning or "").lower()
    assert "under gdpr articles 13(1)(a) and 14(1)(a)" in reasoning
    assert "remediation:" in reasoning
    assert controller.classification in {"non_compliant", "partially_compliant"}


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
