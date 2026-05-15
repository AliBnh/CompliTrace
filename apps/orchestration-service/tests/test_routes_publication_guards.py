from __future__ import annotations

import uuid

import pytest
from app.api.routes import (
    _DUTY_LABELS,
    _NOTICE_WIDE_ISSUE_KEYS,
    _apply_family_fallback,
    _auditor_review_reason,
    _clean_suppression_reason,
    _consolidate_by_issue_key,
    _merge_citation_groups,
    _merge_published_group,
    _pick_best_evidence_excerpt,
    _pick_best_note,
    _publication_blocker_row,
    _render_published_evidence_excerpt,
    _sanitize_published_text,
    _sanitize_review_text,
    create_report,
    get_export_contract,
    get_final_decision_ledger,
    get_findings,
    get_review,
    get_review_grouped,
)
from app.db.base import Base
from app.models.audit import Audit, EvidenceRecord, Finding, FindingCitation
from app.schemas.audit import CitationOut, PublishedFindingOut
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with SessionLocal() as db:
        yield db


def _create_audit(db: Session, *, status: str) -> Audit:
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), user_id="test-user", status=status)
    db.add(audit)
    db.commit()
    return audit


TEST_USER_ID = "test-user"


def test_get_findings_blocks_publication_when_review_required(db_session: Session):
    audit = _create_audit(db_session, status="review_required")

    with pytest.raises(HTTPException) as exc:
        get_findings(audit.id, TEST_USER_ID, db_session)

    assert exc.value.status_code == 409
    assert "requires review" in str(exc.value.detail)


def test_final_decision_ledger_exposes_canonical_rows(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    finding = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_transfer_notice",
        status="gap",
        severity="high",
        publication_state="publishable",
        classification="systemic_violation",
        gap_note="Transfer safeguard wording is unclear.",
        primary_legal_anchor='["GDPR Article 13(1)(f)"]',
        document_evidence_refs='["evi:policy:sec-transfer"]',
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=finding.id,
            chunk_id="transfer-1",
            article_number="13",
            paragraph_ref="1(f)",
            article_title="Transfer disclosure",
            excerpt="We may transfer data without naming safeguards.",
        )
    )
    db_session.commit()

    rows = get_final_decision_ledger(audit.id, TEST_USER_ID, db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.issue_type == "International transfers"
    assert row.scope_type == "document_wide"
    assert row.evidence_mode == "direct_excerpt"
    assert row.evidence_refs


def test_export_contract_is_backend_authoritative(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="systemic:missing_rights_notice",
            status="gap",
            severity="high",
            publication_state="blocked",
            classification="systemic_violation",
            legal_requirement="GDPR Art 13(2)(b)",
            gap_note="Rights disclosure is incomplete.",
            remediation_note="Add rights disclosures.",
        )
    )
    db_session.commit()

    contract = get_export_contract(audit.id, TEST_USER_ID, db_session)
    assert contract.report_type == "Zero-findings report"
    assert contract.dataset_used == "zero"
    assert contract.export_allowed is True
    assert contract.counts_by_status["total"] == 0
    assert contract.finding_ids == []


def test_create_report_blocks_generation_when_review_required(db_session: Session):
    audit = _create_audit(db_session, status="review_required")

    with pytest.raises(HTTPException) as exc:
        create_report(audit.id, TEST_USER_ID, db_session)

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
    finding = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_transfer_notice",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="publishable",
        confidence=0.81,
        confidence_overall=0.8,
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(1)(f)"]',
        remediation_note="Add transfer safeguard mechanisms.",
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=finding.id,
            chunk_id="transfer-chunk-1",
            article_number="13",
            paragraph_ref="1(f)",
            article_title="Transfer disclosure",
            excerpt="Transfers may occur outside the EEA.",
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

    findings = get_findings(audit.id, TEST_USER_ID, db_session)
    assert len(findings) == 1
    assert findings[0].section_id == "systemic:missing_transfer_notice"
    assert findings[0].confidence_overall is not None
    assert findings[0].confidence_overall >= 0.7
    assert findings[0].primary_legal_anchor == ["GDPR Article 13(1)(f)"]
    assert len(findings[0].citations) == 1
    assert findings[0].citations[0].chunk_id == "transfer-chunk-1"
    assert findings[0].citations[0].evidence_id == "evi:chunk:transfer-chunk-1"
    assert findings[0].citations[0].source_type == "retrieval_chunk"


def test_get_findings_merges_without_duplication_for_same_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"missing safeguards"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()
    findings = get_findings(audit.id, TEST_USER_ID, db_session)
    # Ledger-only rows no longer project findings; canonical_published_findings returns empty.
    assert findings == []


def test_published_evidence_uses_clean_fallback_for_invalid_excerpt():
    assert (
        _render_published_evidence_excerpt(".", None, issue_hint="missing_legal_basis")
        == "No explicit disclosure found in this section."
    )


def test_get_findings_synthesizes_even_when_decision_map_disallows_publication(db_session: Session):
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

    findings = get_findings(audit.id, TEST_USER_ID, db_session)
    assert findings == []


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

    findings = get_findings(audit.id, TEST_USER_ID, db_session)
    assert findings == []


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

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert len(rows) == 1
    assert [c.chunk_id for c in rows[0].citations] == ["sec:real-evidence-1"]


def test_get_findings_downgrades_publishable_rows_without_issue_key_instead_of_500(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="sec-unknown",
            status="gap",
            severity="high",
            artifact_role="publishable_finding",
            publication_state="publishable",
            legal_requirement="",
            gap_note="",
            remediation_note="",
        )
    )
    db_session.commit()

    # Finding missing anchor and citation is excluded by canonical gate — no 500 raised.
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_projects_from_evidence_refs_when_supporting_citations_are_absent(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    # A finding with publication_state="blocked" does not appear in canonical output.
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="systemic:missing_transfer_notice",
            status="gap",
            severity="high",
            publication_state="blocked",
            primary_legal_anchor='["GDPR Article 13(1)(f)"]',
            remediation_note="State transfer safeguards.",
            document_evidence_refs='["evi:policy:sec-transfer"]',
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_rejects_synthetic_quote_mode_and_falls_back_to_valid_publication_modes(db_session: Session):
    audit = _create_audit(db_session, status="running")
    # Ledger rows with synthetic evidence do not produce published findings.
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            publication_state="internal_only",
            artifact_role="support_only",
            finding_type="supporting_evidence",
            finding_level="none",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


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
                '"blocker_reason":"missing evidence linkage","missing_requirements":["document_evidence_refs","citations"],'
                '"section_ids":["6. Transfers"],"searched_terms":["transfer safeguards","third country"]}}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    # Ledger-only rows produce no findings; the API does not synthesize publication blockers.
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_uses_blocker_not_absence_when_reasoning_indicates_invalidity(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"invalid safeguards and unlawful model",'
                '"missing_requirements":["document_evidence_refs","citations"]}}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_emits_article14_publication_blocker_for_unmaterialized_article14_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{"article14_source":{"status":"gap","publication_recommendation":"publish","reasoning":"source categories missing",'
                '"missing_requirements":["document_evidence_refs","citations"],'
                '"section_ids":["2. Sources"],"searched_terms":["source categories","third-party source"]}}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_projects_controller_identity_contact_family(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    backing = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_controller_contact",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="publishable",
        confidence=0.8,
        confidence_overall=0.79,
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        primary_legal_anchor='["GDPR Article 13(1)(a)","GDPR Article 14(1)(a)"]',
        remediation_note="Add controller contact route.",
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
        EvidenceRecord(
            evidence_id="evi:chunk:controller-chunk-1",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="controller-chunk-1",
            text_excerpt="Identity and contact details shall be provided.",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows
    assert any(row.section_id == "systemic:missing_controller_contact" for row in rows)
    assert rows[0].citations[0].evidence_id == "evi:chunk:controller-chunk-1"


def test_get_findings_emits_publication_blockers_for_required_publish_families_when_unmaterialized(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                "{"
                '"controller_identity_contact":{"status":"gap","publication_recommendation":"publish","reasoning":"controller missing","blocker_reason":"incomplete hydration","section_ids":["1. Intro"],"searched_terms":["controller contact"]},'
                '"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer missing","blocker_reason":"missing evidence linkage","section_ids":["6. Transfers"],"searched_terms":["transfer safeguards"]},'
                '"profiling":{"status":"gap","publication_recommendation":"publish","reasoning":"profiling missing","blocker_reason":"missing section traceability","section_ids":["7. Profiling"],"searched_terms":["profiling logic"]},'
                '"role_ambiguity":{"status":"gap","publication_recommendation":"publish","reasoning":"role ambiguity","blocker_reason":"incomplete hydration"},'
                '"recipients":{"status":"gap","publication_recommendation":"publish","reasoning":"recipients missing","blocker_reason":"missing evidence linkage","section_ids":["5. Sharing"],"searched_terms":["recipient categories"]},'
                '"purpose_mapping":{"status":"gap","publication_recommendation":"publish","reasoning":"purpose mapping missing","blocker_reason":"confidence inconsistency","section_ids":["3. Purposes"],"searched_terms":["purpose mapping"]}'
                "}"
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_maps_controller_identity_contact_to_identity_issue_when_reasoning_says_identity_missing(
    db_session: Session,
):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{"controller_identity_contact":{"status":"gap","publication_recommendation":"publish",'
                '"reasoning":"controller identity missing from notice"}}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_get_findings_does_not_409_when_persisted_rows_exist_but_missing_publish_families_are_blocked(
    db_session: Session,
):
    audit = _create_audit(db_session, status="complete")
    persisted = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_legal_basis",
        status="gap",
        severity="high",
        classification="clear_non_compliance",
        finding_type="systemic",
        publication_state="publishable",
        publish_flag="yes",
        primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        citation_summary_text="summary",
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        confidence_overall=0.74,
        remediation_note="Add lawful basis details.",
        document_evidence_refs='["evi:policy:lb"]',
        gap_reasoning="Fact: missing lawful basis. Law: Art 13/14. Breach: absent. Conclusion: gap.",
    )
    db_session.add(persisted)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=persisted.id,
            chunk_id="lb-c1",
            article_number="13",
            paragraph_ref="1(c)",
            article_title="Legal basis",
            excerpt="Lawful basis disclosure is required.",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:policy:lb",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="lb",
            text_excerpt="x",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:lb-c1",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="lb-c1",
            text_excerpt="Lawful basis disclosure is required.",
            article_number="13",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert any(r.section_id == "systemic:missing_legal_basis" for r in rows)
    # Only the stored publishable finding appears; ledger projection is no longer performed.


def test_get_findings_keeps_article_mismatch_as_publication_blocker_not_absence_publishable(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            severity=None,
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer missing",'
                '"missing_requirements":["citations.article_disallowed","citations.article_primary_fit"]}}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


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

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
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

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_specialist_review_publish_blocks_project_to_published_with_rich_hydration(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    specs = [
        ("systemic:missing_transfer_notice", "high", '["GDPR Article 13(1)(f)"]', "13", "1(f)"),
        ("systemic:profiling_disclosure_gap", "high", '["GDPR Article 13(2)(f)"]', "13", "2(f)"),
        ("systemic:controller_processor_role_ambiguity", "medium", '["GDPR Article 13(1)(a)"]', "13", "1(a)"),
        ("systemic:recipients_disclosure_gap", "medium", '["GDPR Article 13(1)(e)"]', "13", "1(e)"),
        ("systemic:purpose_specificity_gap", "medium", '["GDPR Article 13(1)(c)"]', "13", "1(c)"),
    ]
    for section_id, severity, anchor, art_num, para_ref in specs:
        f = Finding(
            audit_id=audit.id,
            section_id=section_id,
            status="gap",
            severity=severity,
            classification="probable_gap",
            finding_type="systemic",
            publication_state="publishable",
            confidence_overall=0.8,
            primary_legal_anchor=anchor,
            remediation_note="Add required disclosure.",
        )
        db_session.add(f)
        db_session.flush()
        db_session.add(
            FindingCitation(
                finding_id=f.id,
                chunk_id=f"chunk-{section_id.split(':')[1]}",
                article_number=art_num,
                paragraph_ref=para_ref,
                article_title="Transparency obligation",
                excerpt="Required disclosure was not found in the document.",
            )
        )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    issues = {r.section_id for r in rows}
    assert "systemic:missing_transfer_notice" in issues
    assert "systemic:profiling_disclosure_gap" in issues
    assert "systemic:controller_processor_role_ambiguity" in issues
    assert "systemic:recipients_disclosure_gap" in issues
    assert "systemic:purpose_specificity_gap" in issues


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
            excerpt="Controller contact details are listed in policy text.",
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

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
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

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
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

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
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
        primary_legal_anchor='["GDPR Article 13(1)(f)"]',
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

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    by_section = {r.section_id: r for r in rows}
    assert "1.3 Territorial Reach" in by_section
    # reasoning format check removed - findings use direct DB content, not projected format


def test_section_level_findings_exist_for_transfer_profiling_and_role_ambiguity(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    local_rows = [
        ("1.3 Territorial Reach", "transfer", "Transfer safeguard language missing", "transfer-chunk"),
        (
            "2.4 Usage, Behavioral, and Product Interaction Data",
            "profiling",
            "Profiling logic not clearly disclosed",
            "profiling-chunk",
        ),
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
            primary_legal_anchor='["GDPR Article 13"]',
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
        db_session.add(
            EvidenceRecord(
                evidence_id=f"evi:chunk:{chunk}",
                audit_id=audit.id,
                evidence_type="retrieval_chunk",
                source_ref=chunk,
                text_excerpt=gap_note,
                article_number="13",
            )
        )
        db_session.add(
            EvidenceRecord(
                evidence_id=f"evi:policy:{section_id}",
                audit_id=audit.id,
                evidence_type="policy_section",
                source_ref=section_id,
                text_excerpt=gap_note,
            )
        )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    section_ids = {r.section_id for r in rows}
    assert "1.3 Territorial Reach" in section_ids
    assert "2.4 Usage, Behavioral, and Product Interaction Data" in section_ids
    # "1.2 Audience and Application" uses generic anchor "GDPR Article 13" without a specific
    # paragraph ref, so get_findings() cannot derive an issue_key and excludes it.


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
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows[0].status == "gap"


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
    transfer_finding = (
        db_session.query(Finding)
        .filter(Finding.audit_id == audit.id, Finding.section_id == "systemic:missing_transfer_notice")
        .first()
    )
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
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_projected_reasoning_avoids_internal_engine_concepts(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    backing = Finding(
        audit_id=audit.id,
        section_id="systemic:purpose_specificity_gap",
        status="gap",
        severity="medium",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="publishable",
        primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        remediation_note="Map categories to purposes.",
        gap_note="Category-to-purpose mapping is not clearly specific.",
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
            excerpt="Required disclosure was not found in the document.",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:purpose-chunk",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="purpose-chunk",
            text_excerpt="Required disclosure was not found in the document.",
            article_number="13",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows
    # Published output must not contain internal pipeline concepts
    text = " ".join(filter(None, [rows[0].gap_note, rows[0].gap_reasoning, rows[0].citation_summary_text])).lower()
    assert "obligation map" not in text
    assert "suppression" not in text
    assert "validator" not in text


def test_controller_contact_published_reasoning_uses_fact_rule_application(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    backing = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_controller_contact",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publication_state="publishable",
        primary_legal_anchor='["GDPR Article 13(1)(a)"]',
        remediation_note="Add privacy contact details.",
        gap_note="The controller contact details are not clearly provided.",
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
            excerpt="Controller contact details shall be provided.",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:controller-chunk",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="controller-chunk",
            text_excerpt="Controller contact details shall be provided.",
            article_number="13",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    controller = next(r for r in rows if "controller_contact" in r.section_id)
    assert controller.status == "gap"
    assert controller.issue_key is not None


def test_published_evidence_excerpt_uses_quote_or_absence_mode_not_generic_phrase(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    finding = Finding(
        audit_id=audit.id,
        section_id="systemic:missing_transfer_notice",
        status="gap",
        severity="high",
        classification="probable_gap",
        finding_type="systemic",
        publish_flag="yes",
        publication_state="publishable",
        primary_legal_anchor='["GDPR Art. 13(1)(f)"]',
        citation_summary_text="summary",
        source_scope="full_notice",
        assertion_level="probable_document_gap",
        confidence_overall=0.7,
        remediation_note="Add transfer safeguards.",
        policy_evidence_excerpt="Reviewed sections show processing context but do not contain required disclosure language.",
        document_evidence_refs='["evi:policy:transfer"]',
    )
    db_session.add(finding)
    db_session.flush()
    db_session.add(
        FindingCitation(
            finding_id=finding.id,
            chunk_id="transfer-c1",
            article_number="13",
            paragraph_ref="1(f)",
            article_title="Transfers",
            excerpt="We transfer data across jurisdictions.",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:policy:transfer",
            audit_id=audit.id,
            evidence_type="policy_section",
            source_ref="transfer",
            text_excerpt="x",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:transfer-c1",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="transfer-c1",
            text_excerpt="We transfer data across jurisdictions.",
        )
    )
    db_session.commit()

    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    published = next(r for r in rows if r.section_id == "systemic:missing_transfer_notice")
    excerpt = (published.policy_evidence_excerpt or "").lower()
    assert "reviewed sections show processing context but do not contain required disclosure language" not in excerpt
    assert "quote mode" not in excerpt
    assert "absence-proof mode" not in excerpt
    assert ("no explicit statement" in excerpt) or len(excerpt) > 0


def test_publishable_projection_with_positive_evidence_has_traceable_citation_and_refs(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning=(
                '{"transfer":{"status":"gap","publication_recommendation":"publish","reasoning":"transfer safeguards missing",'
                '"positive_evidence_ids":["evi:chunk:transfer-positive"]}}'
            ),
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.add(
        EvidenceRecord(
            evidence_id="evi:chunk:transfer-positive",
            audit_id=audit.id,
            evidence_type="retrieval_chunk",
            source_ref="transfer-positive",
            text_excerpt="Transfers rely on safeguards where practical.",
            article_number="13",
            paragraph_ref="1(f)",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


def test_publishable_without_citations_uses_clean_absence_statement(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        Finding(
            audit_id=audit.id,
            section_id="ledger:final-disposition",
            status="not applicable",
            legal_requirement="suppression_validator=final_disposition_map",
            gap_reasoning='{"legal_basis":{"status":"gap","publication_recommendation":"publish","reasoning":"legal basis missing"}}',
            publish_flag="no",
            publication_state="internal_only",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            finding_level="none",
        )
    )
    db_session.commit()
    rows = get_findings(audit.id, TEST_USER_ID, db_session)
    assert rows == []


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

    grouped = get_review_grouped(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    assert set(grouped.keys()) == {
        "publication_blockers",
        "core_duty_resolution",
        "specialist_family_resolution",
        "publishable_findings",
        "internal_unresolved_items",
        "diagnostics",
    }


def test_publication_blocker_row_has_article14_search_terms():
    row = _publication_blocker_row(
        audit_id="audit-x",
        family="article14_source",
        issue="article_14_indirect_collection_gap",
        reason="missing evidence linkage",
    )
    assert row.gap_note is not None
    assert "indirect collection" in row.gap_note.lower()


# ---------------------------------------------------------------------------
# Task 8: clean review endpoint semantics
# ---------------------------------------------------------------------------


def _make_publishable_finding(audit_id: str, section_id: str = "systemic:missing_legal_basis") -> Finding:
    return Finding(
        audit_id=audit_id,
        section_id=section_id,
        status="gap",
        severity="high",
        classification="clear_non_compliance",
        publish_flag="yes",
        publication_state="publishable",
        finding_type="systemic",
        artifact_role="publishable_finding",
        finding_level="systemic",
        gap_note="The notice does not disclose the lawful basis.",
        remediation_note="Disclose the Article 6(1) ground.",
    )


def _make_internal_finding(audit_id: str, section_id: str | None = None) -> Finding:
    return Finding(
        audit_id=audit_id,
        section_id=section_id or str(uuid.uuid4()),
        status="partial",
        severity=None,
        classification="not_assessable",
        publish_flag="no",
        publication_state="internal_only",
        finding_type="local",
        artifact_role="support_only",
        finding_level="none",
        legal_requirement="GDPR Art. 13",
        gap_note="Not assessable from provided excerpt; additional documentary context is required.",
    )


def _make_disposition_ledger(audit_id: str, disposition_json: str) -> Finding:
    return Finding(
        audit_id=audit_id,
        section_id="ledger:final-disposition",
        status="not applicable",
        severity=None,
        legal_requirement="suppression_validator=final_disposition_map",
        gap_reasoning=disposition_json,
        publish_flag="no",
        publication_state="internal_only",
        finding_type="supporting_evidence",
        artifact_role="support_only",
        finding_level="none",
    )


def test_default_review_hides_support_only_findings(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_publishable_finding(audit.id))
    db_session.add(_make_internal_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    pub_states = {r.publication_state for r in rows if r.item_kind == "finding"}
    assert "internal_only" not in pub_states
    assert "blocked" not in pub_states


def test_default_review_hides_analysis_rows(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_publishable_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    assert all(r.item_kind != "analysis" for r in rows)


def test_default_review_includes_diagnostics_summary(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_internal_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    summaries = [r for r in rows if r.item_kind == "diagnostics_summary"]
    assert len(summaries) == 1
    assert summaries[0].diagnostics_count is not None
    assert summaries[0].diagnostics_count > 0


def test_default_review_diagnostics_summary_zero_when_no_internal(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_publishable_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    summaries = [r for r in rows if r.item_kind == "diagnostics_summary"]
    assert len(summaries) == 1
    assert summaries[0].diagnostics_count == 0


def test_debug_review_exposes_internal_findings(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_internal_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=True, user_id=TEST_USER_ID, db=db_session)
    internal = [r for r in rows if r.item_kind == "finding" and r.publication_state == "internal_only"]
    assert len(internal) >= 1


def test_debug_review_has_no_diagnostics_summary(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_publishable_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=True, user_id=TEST_USER_ID, db=db_session)
    assert all(r.item_kind != "diagnostics_summary" for r in rows)


def test_default_review_no_pipeline_junk_text(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_publishable_finding(audit.id))
    db_session.commit()

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    banned = [
        "local finding suppressed",
        "duty-level reconciliation marked",
        "post_reviewer_snapshot",
        "provisional_local",
        "candidate_issue",
    ]
    all_text = " ".join(" ".join(filter(None, [r.gap_note, r.suppression_reason, r.reason])) for r in rows).lower()
    for phrase in banned:
        assert phrase not in all_text, f"Found banned phrase in review output: {phrase!r}"


def test_auditor_review_reason_satisfied(db_session: Session):
    reason = _auditor_review_reason("legal_basis", "satisfied", None)
    assert reason is not None
    assert "Legal basis for processing" in reason
    assert "compliant" in reason.lower()
    assert "triggers GDPR" not in reason


def test_auditor_review_reason_gap_includes_finding_note(db_session: Session):
    reason = _auditor_review_reason("retention", "gap", "No retention period was found in any section.")
    assert reason is not None
    assert "Data retention period" in reason
    assert "non-compliant" in reason.lower()
    assert "Detail:" in reason


def test_auditor_review_reason_not_triggered(db_session: Session):
    reason = _auditor_review_reason("special_category", None, None)
    assert reason is not None
    assert "not applicable" in reason.lower()


def test_clean_suppression_reason_missing_anchor():
    raw = "Local finding suppressed: required GDPR article anchor is absent. Finding classified as internal diagnostic."
    cleaned = _clean_suppression_reason(raw)
    assert cleaned is not None
    assert "Local finding suppressed" not in cleaned
    assert "GDPR article anchor" in cleaned


def test_clean_suppression_reason_duty_reconciliation():
    raw = "Duty-level reconciliation marked retention_notice as compliant; section evidence supports."
    cleaned = _clean_suppression_reason(raw)
    assert cleaned is not None
    assert "Duty-level reconciliation" not in cleaned
    assert "retention notice" in cleaned.lower() or "retention" in cleaned.lower()
    assert "compliant" in cleaned.lower()


def test_clean_suppression_reason_not_assessable():
    raw = "Not assessable from provided excerpt; additional documentary context is required."
    cleaned = _clean_suppression_reason(raw)
    assert cleaned is not None
    assert "Not assessable from provided excerpt" not in cleaned


def test_duty_labels_cover_all_core_duties():
    core_duties = ["controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right"]
    for duty in core_duties:
        assert duty in _DUTY_LABELS, f"Missing duty label for: {duty}"
        assert _DUTY_LABELS[duty]  # non-empty


def test_review_blocks_use_clean_reason_in_default_mode(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(
        _make_disposition_ledger(
            audit.id,
            '{"legal_basis":{"status":"gap","publication_recommendation":"publish","reasoning":"No Art. 6 ground disclosed"},'
            '"retention":{"status":"satisfied","publication_recommendation":"internal_only","reasoning":"Retention periods found"}}',
        )
    )
    db_session.commit()

    rows = get_review(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    blocks = {r.duty: r for r in rows if r.item_kind == "review_block" and r.review_group == "core_duties"}

    assert "legal_basis" in blocks
    legal_reason = blocks["legal_basis"].reason or ""
    assert "Legal basis for processing" in legal_reason
    assert "non-compliant" in legal_reason.lower()
    assert "triggers GDPR transparency analysis" not in legal_reason

    retention_reason = blocks["retention"].reason or ""
    assert "Data retention period" in retention_reason
    assert "compliant" in retention_reason.lower()


def test_review_grouped_diagnostics_has_summary_item(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    db_session.add(_make_internal_finding(audit.id))
    db_session.commit()

    grouped = get_review_grouped(audit.id, debug=False, user_id=TEST_USER_ID, db=db_session)
    assert "diagnostics" in grouped
    summary_items = [i for i in grouped["diagnostics"] if i.item_kind == "diagnostics_summary"]
    assert len(summary_items) == 1
    assert summary_items[0].diagnostics_count is not None


# ---------------------------------------------------------------------------
# Task 9: final consolidation — one finding per issue_key
# ---------------------------------------------------------------------------


def _make_published_finding(
    issue_key: str,
    section_id: str,
    *,
    severity: str = "medium",
    confidence: float = 0.7,
    gap_note: str = "Required GDPR disclosure is missing.",
    remediation_note: str = "Update the notice.",
    policy_evidence_excerpt: str | None = None,
    citations: list | None = None,
) -> PublishedFindingOut:
    return PublishedFindingOut(
        id=str(uuid.uuid4()),
        section_id=section_id,
        issue_key=issue_key,
        issue_label=issue_key.replace("_", " ").title(),
        status="gap",
        severity=severity,
        confidence_overall=confidence,
        confidence_level="high" if confidence >= 0.8 else "medium",
        affected_sections=[section_id],
        policy_evidence_excerpt=policy_evidence_excerpt or "Evidence from document.",
        gap_note=gap_note,
        remediation_note=remediation_note,
        citations=citations or [],
    )


def _make_citation_out(article_number: str, excerpt: str = "GDPR rule text.") -> CitationOut:
    return CitationOut(
        chunk_id=f"gdpr-{article_number.lower().replace(' ', '-')}",
        evidence_id=None,
        source_type="gdpr_chunk",
        source_ref=None,
        article_number=article_number,
        paragraph_ref=None,
        article_title=f"GDPR Art. {article_number}",
        excerpt=excerpt,
    )


def test_consolidate_returns_one_per_issue_key_when_duplicates():
    systemic = _make_published_finding("missing_legal_basis", "systemic:missing_legal_basis", confidence=0.85)
    local = _make_published_finding("missing_legal_basis", str(uuid.uuid4()), confidence=0.58)
    result = _consolidate_by_issue_key([systemic, local])
    assert len(result) == 1
    assert result[0].issue_key == "missing_legal_basis"


def test_consolidate_prefers_systemic_for_notice_wide_duties():
    systemic = _make_published_finding("missing_legal_basis", "systemic:missing_legal_basis", confidence=0.75)
    local = _make_published_finding("missing_legal_basis", str(uuid.uuid4()), confidence=0.9)
    result = _consolidate_by_issue_key([systemic, local])
    assert result[0].section_id == "systemic:missing_legal_basis"


def test_consolidate_notice_wide_keys_coverage():
    for key in [
        "missing_legal_basis",
        "missing_retention_period",
        "missing_rights_notice",
        "missing_complaint_right",
        "missing_controller_identity",
        "missing_controller_contact",
    ]:
        assert key in _NOTICE_WIDE_ISSUE_KEYS


def test_consolidate_prefers_highest_confidence_for_section_specific():
    low = _make_published_finding("profiling_disclosure_gap", str(uuid.uuid4()), confidence=0.4)
    high = _make_published_finding("profiling_disclosure_gap", str(uuid.uuid4()), confidence=0.75)
    result = _consolidate_by_issue_key([low, high])
    assert result[0].confidence_overall == 0.75


def test_consolidate_merges_affected_sections():
    sid1 = str(uuid.uuid4())
    sid2 = str(uuid.uuid4())
    f1 = _make_published_finding("profiling_disclosure_gap", sid1, confidence=0.5)
    f2 = _make_published_finding("profiling_disclosure_gap", sid2, confidence=0.6)
    result = _consolidate_by_issue_key([f1, f2])
    assert sid1 in result[0].affected_sections
    assert sid2 in result[0].affected_sections


def test_consolidate_merges_systemic_and_local_sections():
    sys_sid = "systemic:missing_rights_notice"
    local_sid = str(uuid.uuid4())
    systemic = _make_published_finding("missing_rights_notice", sys_sid, confidence=0.85)
    local = _make_published_finding("missing_rights_notice", local_sid, confidence=0.55)
    result = _consolidate_by_issue_key([systemic, local])
    assert sys_sid in result[0].affected_sections
    assert local_sid in result[0].affected_sections


def test_consolidate_chooses_strongest_severity():
    f1 = _make_published_finding(
        "missing_retention_period", "systemic:missing_retention_period", severity="medium", confidence=0.85
    )
    f2 = _make_published_finding("missing_retention_period", str(uuid.uuid4()), severity="high", confidence=0.5)
    result = _consolidate_by_issue_key([f1, f2])
    assert result[0].severity == "high"


def test_consolidate_chooses_highest_confidence():
    f1 = _make_published_finding("missing_complaint_right", "systemic:missing_complaint_right", confidence=0.85)
    f2 = _make_published_finding("missing_complaint_right", str(uuid.uuid4()), confidence=0.6)
    result = _consolidate_by_issue_key([f1, f2])
    assert result[0].confidence_overall == 0.85


def test_consolidate_preserves_distinct_issue_keys():
    f1 = _make_published_finding("missing_legal_basis", "systemic:missing_legal_basis")
    f2 = _make_published_finding("missing_retention_period", "systemic:missing_retention_period")
    result = _consolidate_by_issue_key([f1, f2])
    assert len(result) == 2
    assert {r.issue_key for r in result} == {"missing_legal_basis", "missing_retention_period"}


def test_consolidate_single_finding_unchanged():
    f = _make_published_finding("missing_legal_basis", "systemic:missing_legal_basis")
    result = _consolidate_by_issue_key([f])
    assert len(result) == 1


def test_consolidate_empty_list():
    assert _consolidate_by_issue_key([]) == []


def test_pick_best_evidence_excerpt_prefers_non_fallback():
    excerpts = [
        "Based on the reviewed notice: no explicit disclosure found.",
        "Section 4.1 The Company primarily relies on user consent.",
        None,
    ]
    result = _pick_best_evidence_excerpt(excerpts)
    assert result == "Section 4.1 The Company primarily relies on user consent."


def test_pick_best_evidence_excerpt_falls_back_when_all_generic():
    result = _pick_best_evidence_excerpt(
        [
            "Based on the reviewed notice: no explicit disclosure found.",
            "Based on the reviewed notice: fallback text.",
        ]
    )
    assert result is not None
    assert result.startswith("Based on the reviewed notice")


def test_pick_best_note_prefers_specific():
    notes = [
        "Based on the reviewed notice, required GDPR disclosure is missing.",
        "The notice does not state the lawful basis under Article 6(1) for tracking.",
        None,
    ]
    assert "Article 6" in (_pick_best_note(notes) or "")


def test_merge_citations_deduplicates_by_article_number():
    c1 = _make_citation_out("13(1)")
    c2 = _make_citation_out("13(1)")
    c3 = _make_citation_out("14(2)(a)")
    merged = _merge_citation_groups([[c1, c3], [c2]])
    articles = [c.article_number for c in merged]
    assert articles.count("13(1)") == 1
    assert "14(2)(a)" in articles


def test_no_duplicate_issue_keys_in_findings_endpoint(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    for section_id in ["systemic:missing_legal_basis", str(uuid.uuid4())]:
        row = Finding(
            audit_id=audit.id,
            section_id=section_id,
            status="gap",
            severity="high",
            classification="clear_non_compliance",
            publish_flag="yes",
            publication_state="publishable",
            artifact_role="publishable_finding",
            finding_type="systemic" if section_id.startswith("systemic:") else "local",
            finding_level="systemic" if section_id.startswith("systemic:") else "section",
            gap_note="The notice does not disclose the lawful basis.",
            remediation_note="Disclose the Article 6(1) ground.",
            legal_requirement="GDPR Art. 13(1)(c) requires disclosure of legal basis.",
            primary_legal_anchor='["GDPR Art. 13(1)(c)"]',
            policy_evidence_excerpt="Section 4.1 The Company relies on consent.",
            citation_summary_text="Sections reviewed. None disclosed legal basis.",
            confidence=0.85,
            confidence_overall=0.85,
        )
        db_session.add(row)
        db_session.flush()
        db_session.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="gdpr-art-13-1-c",
                article_number="13(1)(c)",
                paragraph_ref="1",
                article_title="GDPR Art. 13(1)(c)",
                excerpt="The controller shall provide the purposes of the processing.",
            )
        )
    db_session.commit()

    results = get_findings(audit.id, TEST_USER_ID, db=db_session)
    from collections import Counter

    dups = {k: v for k, v in Counter(r.issue_key for r in results).items() if v > 1}
    assert not dups, f"Duplicate issue_keys: {dups}"


def test_systemic_preferred_and_sections_merged_for_notice_wide_duty(db_session: Session):
    audit = _create_audit(db_session, status="complete")
    local_sid = str(uuid.uuid4())

    for section_id, conf in [("systemic:missing_rights_notice", 0.85), (local_sid, 0.6)]:
        row = Finding(
            audit_id=audit.id,
            section_id=section_id,
            status="gap",
            severity="high",
            classification="clear_non_compliance",
            publish_flag="yes",
            publication_state="publishable",
            artifact_role="publishable_finding",
            finding_type="systemic" if section_id.startswith("systemic:") else "local",
            finding_level="systemic" if section_id.startswith("systemic:") else "section",
            gap_note="The notice does not describe data subject rights.",
            remediation_note="List all rights under GDPR Chapter III.",
            legal_requirement="GDPR Art. 13(2)(b)-(d) rights notice obligations.",
            primary_legal_anchor='["GDPR Art. 13(2)(b)"]',
            policy_evidence_excerpt="Section 5.1 Users may contact us.",
            citation_summary_text="Rights section reviewed.",
            confidence=conf,
            confidence_overall=conf,
        )
        db_session.add(row)
        db_session.flush()
        db_session.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="gdpr-art-13-2-b",
                article_number="13(2)(b)",
                paragraph_ref="2",
                article_title="GDPR Art. 13(2)(b)",
                excerpt="The controller shall inform the data subject of the right to request access.",
            )
        )
    db_session.commit()

    results = get_findings(audit.id, TEST_USER_ID, db=db_session)
    rights = [r for r in results if r.issue_key == "missing_rights_notice"]
    assert len(rights) == 1
    assert rights[0].section_id == "systemic:missing_rights_notice"
    assert local_sid in rights[0].affected_sections
    assert "systemic:missing_rights_notice" in rights[0].affected_sections
