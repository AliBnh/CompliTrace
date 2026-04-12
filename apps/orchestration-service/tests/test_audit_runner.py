from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.audit_runner import (
    _applicability_memo,
    _applicability_decision,
    _apply_applicability_gate_to_citations,
    _article_int,
    _build_transfer_gap,
    _build_retention_gap,
    _citation_claim_compatible,
    _claim_types_from_text,
    _fallback_claim_types_from_section,
    _build_mandatory_notice_gap,
    _collection_mode,
    _enforce_substantive_citation_gate,
    _evidence_sufficient,
    _fallback_notice_citations,
    _is_legally_relevant_citation,
    _is_notice_disclosure_section,
    _is_not_applicable,
    _paragraph_ref_compatible,
    _rerank_chunks_for_mode,
    _retry_needed,
    _reviewer_agent,
    _salvage_citations_from_retrieved,
    _sanitize_legal_reference_text,
    _document_posture_agent,
    _finding_mentions_internal_control_only,
    _runtime_budget_exceeded,
    _targeted_notice_query,
    _claim_has_primary_anchor,
    _normalize_severity,
    _normalize_analysis_anchors,
    _partner_review_pass,
    _finding_signature,
    _ensure_reasoning_chain,
    _clean_remediation_legal_mismatches,
    _classify_finding_quality,
    _validate_citations,
    _section_auditability_type,
    _spot_candidate_issues,
    _legal_qualification_for_issue,
    _violates_forbidden_article_matrix,
    _systemic_evidence_refs,
    _systemic_summary_text,
    _coverage_to_support_valid,
    _enforce_core_and_specialist_completeness,
    _build_final_disposition_map,
    _document_wide_duty_validation,
    _final_publication_validator,
    _upsert_evidence_records,
    _extract_notice_cross_references,
    _source_scope_qualification,
    _issue_has_unseen_reference,
    _has_positive_contradictory_disclosure,
    _extract_legal_facts,
    _explicit_violation_hits,
    _legal_reasoning_step,
    _validate_family_obligations,
    _not_assessable_allowed,
    _issue_relevance_score,
    _build_document_obligation_map,
)
from app.services.clients import LlmCitation, LlmFinding, RetrievalChunk, SectionData
from app.models.audit import Audit, EvidenceRecord, Finding, FindingCitation
from app.db.base import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_not_applicable_admin_section():
    section = SectionData(
        id="s1",
        section_order=1,
        section_title="Definitions",
        content="This section defines terms used in the policy.",
        page_start=1,
        page_end=1,
    )
    assert _is_not_applicable(section) is True


def test_retry_rule_when_low_score():
    chunks = [
        RetrievalChunk(
            chunk_id="c1",
            article_number="5",
            article_title="Principles",
            paragraph_ref="1(e)",
            content="retention obligations apply",
            score=0.32,
        )
    ]
    assert _retry_needed(chunks, "data retention") is True


def test_evidence_sufficient_true_case():
    chunks = [
        RetrievalChunk(chunk_id="c1", article_number="5", article_title="", paragraph_ref=None, content="controller shall", score=0.71),
        RetrievalChunk(chunk_id="c2", article_number="6", article_title="", paragraph_ref=None, content="processing must", score=0.65),
        RetrievalChunk(chunk_id="c3", article_number="17", article_title="", paragraph_ref=None, content="aux", score=0.30),
    ]
    assert _evidence_sufficient(chunks) is True


def test_final_disposition_keeps_controller_family_satisfied_when_identity_and_contact_are_present():
    sections = [
        SectionData(
            id="sec-1",
            section_order=1,
            section_title="Privacy notice",
            content="We are ACME Corp and process personal data.",
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {
        "controller_identity": True,
        "controller_contact": True,
        "legal_basis": True,
        "retention": True,
        "rights": True,
        "complaint": True,
    }

    disposition = _build_final_disposition_map([], sections, obligation_map)

    controller = disposition["controller_identity_contact"]
    assert controller["status"] == "satisfied"
    assert controller["publication_recommendation"] == "internal_only"


def test_upsert_evidence_records_creates_policy_and_chunk_entries():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-1", status="running")
        db.add(audit)
        db.flush()
        finding = Finding(
            audit_id=audit.id,
            section_id="sec-1",
            status="gap",
            severity="high",
            classification="probable_gap",
            publish_flag="yes",
            publication_state="publishable",
            finding_type="local",
            policy_evidence_excerpt="Controller contact is missing",
            document_evidence_refs='["sec:1"]',
        )
        db.add(finding)
        db.flush()
        db.add(
            FindingCitation(
                finding_id=finding.id,
                chunk_id="gdpr-art-13-p-1-c",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Information to be provided",
                excerpt="The controller shall provide contact details.",
            )
        )
        db.commit()

        _upsert_evidence_records(db, audit.id)
        db.commit()

        records = db.query(EvidenceRecord).filter(EvidenceRecord.audit_id == audit.id).all()
        ids = {r.evidence_id for r in records}
        assert f"evi:policy:{finding.section_id}" in ids
        assert "evi:chunk:gdpr-art-13-p-1-c" in ids


def test_final_publication_validator_marks_audit_incomplete_when_publishable_gap_family_is_unmaterialized():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-1", status="running")
        db.add(audit)
        db.flush()
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="sec-1",
                status="partial",
                severity="medium",
                classification="supporting_evidence",
                finding_type="supporting_evidence",
                publish_flag="no",
                publication_state="internal_only",
                gap_note="support row",
            )
        )
        db.commit()
        disposition_map = {
            "transfer": {
                "status": "gap",
                "publication_recommendation": "publish",
                "reasoning": "transfer disclosure missing",
            }
        }

        _final_publication_validator(db, audit.id, disposition_map, source_scope="full_notice")
        db.refresh(audit)
        assert audit.status == "audit_incomplete"


def test_final_publication_validator_marks_audit_incomplete_when_publishable_referenced_unseen_family_is_unmaterialized():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-2", status="running")
        db.add(audit)
        db.flush()
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="sec-2",
                status="partial",
                severity="medium",
                classification="supporting_evidence",
                finding_type="supporting_evidence",
                publish_flag="no",
                publication_state="internal_only",
                gap_note="support row",
            )
        )
        db.commit()
        disposition_map = {
            "profiling": {
                "status": "referenced_but_unseen",
                "publication_recommendation": "publish",
                "reasoning": "profiling references unresolved",
            }
        }

        _final_publication_validator(db, audit.id, disposition_map, source_scope="full_notice")
        db.refresh(audit)
        assert audit.status == "audit_incomplete"


def test_build_final_disposition_map_splits_controller_identity_from_contact_when_identity_missing():
    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="1. Introduction",
            content="We process personal data.",
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {
        "controller_identity": False,
        "controller_contact": True,
        "controller_identity_contact": False,
        "legal_basis": True,
        "retention": True,
        "rights": True,
        "complaint": True,
    }
    out = _build_final_disposition_map([], sections, obligation_map)
    controller = out["controller_identity_contact"]
    assert controller["status"] == "gap"
    assert controller["issue_key"] == "missing_controller_identity"


def test_build_final_disposition_map_marks_retention_gap_when_obligation_not_visible():
    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="7. Retention",
            content="Archived datasets may be retained indefinitely for historical analysis.",
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {
        "controller_identity": True,
        "controller_contact": True,
        "controller_identity_contact": True,
        "legal_basis": True,
        "retention": False,
        "rights": True,
        "complaint": True,
    }
    out = _build_final_disposition_map([], sections, obligation_map)
    retention = out["retention"]
    assert retention["status"] == "gap"
    assert retention["publication_recommendation"] == "publish"
    assert retention["severity"] == "high"


def test_final_publication_validator_blocks_publishable_row_without_flbc_reasoning():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-3", status="running")
        db.add(audit)
        db.flush()
        finding = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_legal_basis",
            status="gap",
            severity="high",
            classification="probable_gap",
            finding_type="systemic",
            publish_flag="yes",
            publication_state="publishable",
            primary_legal_anchor='["GDPR Article 13(1)(c)"]',
            citation_summary_text="summary",
            source_scope="full_notice",
            assertion_level="confirmed_document_gap",
            confidence_overall=0.71,
            remediation_note="Add legal bases by purpose.",
            gap_reasoning="Missing legal basis disclosure in notice.",
            document_evidence_refs='["evi:policy:lb"]',
        )
        db.add(finding)
        db.flush()
        db.add(FindingCitation(finding_id=finding.id, chunk_id="c13", article_number="13", paragraph_ref="1(c)", article_title="Legal basis", excerpt="x"))
        db.commit()

        disposition_map = {"legal_basis": {"status": "gap", "publication_recommendation": "publish", "reasoning": "legal basis missing"}}
        _final_publication_validator(db, audit.id, disposition_map, source_scope="full_notice")
        db.refresh(finding)
        assert finding.publish_flag == "no"
        assert finding.publication_state == "blocked"


def test_final_publication_validator_blocks_publishable_row_on_citation_article_matrix_mismatch():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-4", status="running")
        db.add(audit)
        db.flush()
        finding = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_transfer_notice",
            status="gap",
            severity="high",
            classification="probable_gap",
            finding_type="systemic",
            publish_flag="yes",
            publication_state="publishable",
            primary_legal_anchor='["GDPR Article 13(1)(f)"]',
            citation_summary_text="summary",
            source_scope="full_notice",
            assertion_level="confirmed_document_gap",
            confidence_overall=0.74,
            remediation_note="Add transfer safeguards.",
            gap_reasoning="Fact: transfer context. Law: Article 13(1)(f). Breach: missing safeguards. Conclusion: gap.",
            document_evidence_refs='["evi:policy:transfer"]',
        )
        db.add(finding)
        db.flush()
        db.add(FindingCitation(finding_id=finding.id, chunk_id="c21", article_number="21", paragraph_ref="1", article_title="Right to object", excerpt="x"))
        db.commit()

        disposition_map = {
            "controller_identity_contact": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "legal_basis": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "retention": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "rights_notice": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "complaint_right": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "transfer": {"status": "gap", "publication_recommendation": "publish", "reasoning": "transfer missing"},
            "profiling": {"status": "not_triggered", "publication_recommendation": "internal_only"},
            "role_ambiguity": {"status": "not_triggered", "publication_recommendation": "internal_only"},
            "article14_source": {"status": "not_triggered", "publication_recommendation": "internal_only"},
            "recipients": {"status": "not_triggered", "publication_recommendation": "internal_only"},
            "purpose_mapping": {"status": "not_triggered", "publication_recommendation": "internal_only"},
            "special_category": {"status": "not_triggered", "publication_recommendation": "internal_only"},
            "dpo_contact": {"status": "not_triggered", "publication_recommendation": "internal_only"},
        }
        _final_publication_validator(db, audit.id, disposition_map, source_scope="full_notice")
        db.refresh(finding)
        assert finding.publish_flag == "no"
        assert finding.publication_state == "blocked"


def test_contradiction_helper_requires_positive_quote_not_just_wording():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-5", status="running")
        db.add(audit)
        db.flush()
        finding = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_transfer_notice",
            status="gap",
            severity="high",
            classification="probable_gap",
            finding_type="systemic",
            publish_flag="yes",
            publication_state="publishable",
            primary_legal_anchor='["GDPR Article 13(1)(f)"]',
            citation_summary_text="summary",
            source_scope="full_notice",
            assertion_level="confirmed_document_gap",
            confidence_overall=0.72,
            remediation_note="Add transfer safeguards.",
            gap_reasoning="Fact: transfer context exists. Law: Art 13(1)(f). Breach: safeguards absent. Conclusion: contradiction check pending.",
            omission_basis="true",
            support_complete="true",
            document_evidence_refs='["evi:policy:transfer"]',
        )
        db.add(finding)
        db.flush()
        db.add(FindingCitation(finding_id=finding.id, chunk_id="c13", article_number="13", paragraph_ref="1(f)", article_title="Transfers", excerpt="Data may move across regions."))
        db.commit()

        assert _has_positive_contradictory_disclosure(db, finding, "missing_transfer_notice") is False


def test_final_publication_validator_blocks_when_positive_contradictory_quote_exists():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-6", status="running")
        db.add(audit)
        db.flush()
        finding = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_controller_contact",
            status="gap",
            severity="high",
            classification="probable_gap",
            finding_type="systemic",
            publish_flag="yes",
            publication_state="publishable",
            primary_legal_anchor='["GDPR Article 13(1)(a)"]',
            citation_summary_text="summary",
            source_scope="full_notice",
            assertion_level="probable_document_gap",
            confidence_overall=0.73,
            remediation_note="Add contact route.",
            gap_reasoning="Fact: contact appears contradictory. Law: Art 13(1)(a). Breach: unclear. Conclusion: contradictory text may already disclose contact.",
            document_evidence_refs='["evi:policy:controller"]',
        )
        db.add(finding)
        db.flush()
        db.add(
            FindingCitation(
                finding_id=finding.id,
                chunk_id="c-contact",
                article_number="13",
                paragraph_ref="1(a)",
                article_title="Controller contact",
                excerpt="You may contact us at privacy@example.com for any request.",
            )
        )
        db.commit()
        assert _has_positive_contradictory_disclosure(db, finding, "missing_controller_contact") is True

        disposition_map = {
            "controller_identity_contact": {
                "status": "gap",
                "publication_recommendation": "publish",
                "reasoning": "contact missing",
            },
            "legal_basis": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "retention": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "rights_notice": {"status": "satisfied", "publication_recommendation": "internal_only"},
            "complaint_right": {"status": "satisfied", "publication_recommendation": "internal_only"},
        }
        _final_publication_validator(db, audit.id, disposition_map, source_scope="full_notice")
        db.refresh(finding)
        assert finding.publish_flag == "no"
        assert finding.publication_state == "blocked"


def test_upsert_evidence_records_deduplicates_same_policy_section_id():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-1", status="running")
        db.add(audit)
        db.flush()
        f1 = Finding(audit_id=audit.id, section_id="systemic:missing_complaint_right", status="gap", severity="high", finding_type="systemic")
        f2 = Finding(audit_id=audit.id, section_id="systemic:missing_complaint_right", status="gap", severity="high", finding_type="systemic")
        db.add_all([f1, f2])
        db.commit()

        _upsert_evidence_records(db, audit.id)
        db.commit()

        policy_ids = [
            r.evidence_id
            for r in db.query(EvidenceRecord).filter(EvidenceRecord.audit_id == audit.id, EvidenceRecord.evidence_type == "policy_section").all()
        ]
        assert policy_ids.count("evi:policy:systemic:missing_complaint_right") == 1


def test_final_disposition_promotes_role_ambiguity_to_gap_when_mixed_roles_without_allocation():
    sections = [
        SectionData(
            id="sec-role",
            section_order=1,
            section_title="Roles",
            content="We act as both controller and processor and may process data on behalf of customers.",
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}
    disposition = _build_final_disposition_map([], sections, obligation_map)
    role = disposition["role_ambiguity"]
    assert role["triggered"] is True
    assert role["status"] == "gap"
    assert role["publication_recommendation"] == "publish"


def test_final_disposition_role_ambiguity_explicit_split_is_satisfied_not_gap():
    sections = [
        SectionData(
            id="sec-role-clear",
            section_order=1,
            section_title="Controller and processor roles",
            content=(
                "For our own purposes we act as controller for account administration and fraud prevention. "
                "For customer instructions we act as processor and process customer data only on behalf of customers."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}
    disposition = _build_final_disposition_map([], sections, obligation_map)
    role = disposition["role_ambiguity"]
    assert role["triggered"] is True
    assert role["status"] == "satisfied"
    assert role["publication_recommendation"] == "internal_only"


def test_final_disposition_profiling_tier_automated_decisioning_sets_high_severity_gap():
    sections = [
        SectionData(
            id="sec-prof-auto",
            section_order=1,
            section_title="Automated decisions",
            content=(
                "We use profiling models and automated decision-making without human intervention "
                "for eligibility decisions that may have legal effect."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}
    disposition = _build_final_disposition_map([], sections, obligation_map)
    profiling = disposition["profiling"]
    assert profiling["triggered"] is True
    assert profiling["status"] == "gap"
    assert profiling["severity"] == "high"


def test_final_disposition_profiling_only_without_required_disclosure_is_medium_gap():
    sections = [
        SectionData(
            id="sec-prof-only",
            section_order=1,
            section_title="Personalization",
            content="We use profiling and segmentation models to personalize marketing and audience scoring.",
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}
    disposition = _build_final_disposition_map([], sections, obligation_map)
    profiling = disposition["profiling"]
    assert profiling["triggered"] is True
    assert profiling["status"] == "gap"
    assert profiling["severity"] == "medium"


def test_final_disposition_recipients_family_gaps_when_third_parties_without_structured_categories():
    sections = [
        SectionData(
            id="sec-rec",
            section_order=1,
            section_title="Sharing and disclosures",
            content=(
                "We share personal data with vendors, partners, marketplaces, payment providers and cloud providers "
                "to operate services."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}
    disposition = _build_final_disposition_map([], sections, obligation_map)
    recipients = disposition["recipients"]
    assert recipients["triggered"] is True
    assert recipients["status"] == "gap"
    assert recipients["publication_recommendation"] == "publish"


def test_final_disposition_purpose_mapping_family_non_silent_for_broad_categories():
    sections = [
        SectionData(
            id="sec-2-4",
            section_order=4,
            section_title="2.4 Usage, Behavioral, and Product Interaction Data",
            content=(
                "Categories of personal data include usage logs, behavioral data, and interaction telemetry. "
                "We use this data for business purposes and as necessary to improve services."
            ),
            page_start=2,
            page_end=3,
        )
    ]
    obligation_map = {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}
    disposition = _build_final_disposition_map([], sections, obligation_map)
    purpose = disposition["purpose_mapping"]
    assert purpose["triggered"] is True
    assert purpose["status"] in {"gap", "not_assessable"}


def test_final_disposition_article14_source_requires_source_categories_and_timing():
    sections = [
        SectionData(
            id="sec-a14",
            section_order=1,
            section_title="Data sources",
            content=(
                "We receive data from third parties, including partners, data aggregators, and public records."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    disposition = _build_final_disposition_map([], sections, {})
    article14 = disposition["article14_source"]
    assert article14["triggered"] is True
    assert article14["status"] == "gap"
    assert "timing duties" in str(article14["reasoning"])


def test_final_disposition_special_category_ambiguous_sensitive_language_not_overcalled():
    sections = [
        SectionData(
            id="sec-sensitive",
            section_order=1,
            section_title="Sensitive data",
            content="We may handle sensitive information under applicable law where appropriate.",
            page_start=1,
            page_end=1,
        )
    ]
    disposition = _build_final_disposition_map([], sections, {})
    special = disposition["special_category"]
    assert special["triggered"] is True
    assert special["status"] == "referenced_but_unseen"
    assert special["publication_recommendation"] == "publish"


def test_final_disposition_special_category_true_art9_without_condition_is_gap():
    sections = [
        SectionData(
            id="sec-art9",
            section_order=1,
            section_title="Health processing",
            content=(
                "As controller we collect health data and biometric data for service delivery. "
                "This special category processing is performed for operations."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    disposition = _build_final_disposition_map([], sections, {})
    special = disposition["special_category"]
    assert special["triggered"] is True
    assert special["status"] == "gap"
    assert special["publication_recommendation"] == "publish"


def test_substantive_finding_without_citations_keeps_substantive_status():
    finding = LlmFinding(
        status="partial",
        severity="high",
        gap_note="Missing legal basis",
        remediation_note="Add legal basis",
        citations=[],
    )
    gated = _enforce_substantive_citation_gate(finding, valid_citations=[])
    assert gated.status == "partial"
    assert gated.severity == "high"
    assert "Evidence note:" in (gated.gap_note or "")


def test_substantive_finding_with_citations_is_kept():
    finding = LlmFinding(
        status="gap",
        severity="high",
        gap_note="Missing retention period",
        remediation_note="Add retention period",
        citations=[],
    )
    citation = LlmCitation(chunk_id="c1", article_number="13")
    gated = _enforce_substantive_citation_gate(finding, valid_citations=[citation])
    assert gated.status == "gap"


def test_runtime_budget_exceeded():
    assert _runtime_budget_exceeded(0.0, 181.0, 180) is True
    assert _runtime_budget_exceeded(0.0, 180.0, 180) is False


def test_article_int_parsing():
    assert _article_int("13") == 13
    assert _article_int("Article 46") == 46
    assert _article_int(None) is None


def test_document_obligation_map_detects_controller_identity_from_corporate_suffix():
    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="Introduction",
            content='Orion Data Systems, Inc. ("Company", "we", "us") provides cloud services.',
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = _build_document_obligation_map(sections)
    assert obligation_map["controller_identity_present"] is True


def test_normalize_analysis_anchors_rewrites_mismatched_transfer_family():
    anchors = _normalize_analysis_anchors("missing_transfer_notice", '["GDPR Article 13(1)(a)"]')
    assert anchors is not None
    assert "13(1)(f)" in anchors
    assert "14(1)(f)" in anchors


def test_normalize_analysis_anchors_enforces_family_validators_for_rights_and_complaint():
    rights = _normalize_analysis_anchors("missing_rights_notice", '["GDPR Article 13(1)(a)"]') or ""
    complaint = _normalize_analysis_anchors("missing_complaint_right", '["GDPR Article 13(1)(a)"]') or ""
    assert "13(2)(b)" in rights
    assert "14(2)(e)" in rights
    assert "13(2)(d)" in complaint
    assert "77" in complaint


def test_partner_review_pass_reduces_not_assessable_for_explicit_context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-1", status="running")
        db.add(audit)
        db.flush()
        row = Finding(
            audit_id=audit.id,
            section_id="sec-transfer",
            status="needs review",
            severity=None,
            finding_type="local",
            publish_flag="no",
            gap_note="We transfer data outside the EEA but safeguards are not disclosed.",
            remediation_note=None,
            policy_evidence_excerpt="We transfer personal data and no safeguards are listed.",
        )
        db.add(row)
        db.commit()
        _partner_review_pass(db, audit.id)
        updated = db.get(Finding, row.id)
        assert updated.classification in {"probable_gap", "clear_non_compliance"}
        assert updated.artifact_role == "publishable_finding"


def test_partner_review_promotes_not_assessable_retention_violation():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-1", status="running")
        db.add(audit)
        db.flush()
        row = Finding(
            audit_id=audit.id,
            section_id="sec-retention",
            status="partial",
            severity=None,
            classification="not_assessable",
            finding_type="supporting_evidence",
            publish_flag="no",
            gap_note="Not assessable from provided excerpt; additional documentary context is required.",
            remediation_note="Provide complete notice excerpts and rerun legal qualification.",
            policy_evidence_excerpt="Archived datasets may be retained indefinitely and retained for extended periods.",
        )
        db.add(row)
        db.commit()
        _partner_review_pass(db, audit.id)
        updated = db.get(Finding, row.id)
        assert updated.classification == "clear_non_compliance"
        assert updated.publish_flag == "yes"
        assert updated.artifact_role == "publishable_finding"


def test_partner_review_suppresses_controller_missing_when_identity_disclosed():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-1", status="running")
        db.add(audit)
        db.flush()
        identity_row = Finding(
            audit_id=audit.id,
            section_id="sec-intro",
            status="partial",
            severity="medium",
            classification="probable_gap",
            finding_type="local",
            publish_flag="yes",
            policy_evidence_excerpt='Orion Data Systems, Inc. ("Company", "we", "us") provides services.',
            gap_note="context row",
        )
        controller_row = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_controller_identity",
            status="gap",
            severity="high",
            classification="systemic_violation",
            finding_type="systemic",
            publish_flag="yes",
            publication_state="publishable",
            gap_note="The notice does not clearly identify the controller legal entity and contact route.",
        )
        db.add(identity_row)
        db.add(controller_row)
        db.commit()
        _partner_review_pass(db, audit.id)
        updated = db.get(Finding, controller_row.id)
        assert updated.publish_flag == "no"
        assert updated.classification == "no_issue"
        assert updated.publication_state == "internal_only"


def test_explicit_violation_hits_detect_consent_inferred_from_interactions():
    hits = _explicit_violation_hits("Consent is inferred from interactions and continued usage of the service.")
    assert any(key == "invalid_consent" for key, _ in hits)


def test_explicit_violation_hits_detect_extended_indefinite_retention():
    hits = _explicit_violation_hits("Data may be retained for extended periods; archived datasets may be retained indefinitely.")
    assert any(key == "unlawful_retention_wording" for key, _ in hits)


def test_paragraph_ref_compatible_tolerates_format_variants():
    assert _paragraph_ref_compatible("1(f)", "Paragraph 1(f)") is True
    assert _paragraph_ref_compatible("2", "3") is False


def test_rerank_demotes_article_88_for_privacy_notice_non_employment():
    section = SectionData(
        id="s2",
        section_order=2,
        section_title="International Transfers",
        content="Data may be accessed from countries outside the EEA.",
        page_start=2,
        page_end=2,
    )
    chunks = [
        RetrievalChunk(chunk_id="c1", article_number="88", article_title="", paragraph_ref=None, content="employment context", score=0.90),
        RetrievalChunk(chunk_id="c2", article_number="46", article_title="", paragraph_ref=None, content="appropriate safeguards", score=0.82),
    ]
    reranked = _rerank_chunks_for_mode(section, chunks, "privacy_notice")
    assert reranked[0].article_number == "46"


def test_legal_relevance_rejects_article_30_for_privacy_notice_without_ropa_context():
    section = SectionData(
        id="s3",
        section_order=3,
        section_title="Privacy Notice",
        content="We provide transparency about personal data usage.",
        page_start=3,
        page_end=3,
    )
    citation = LlmCitation(chunk_id="c30", article_number="30")
    assert _is_legally_relevant_citation(citation, section, "privacy_notice") is False


def test_legal_relevance_rejects_article_46_without_transfer_signals():
    section = SectionData(
        id="s4",
        section_order=4,
        section_title="Payment Processors",
        content="Payments are handled by third-party processors.",
        page_start=4,
        page_end=4,
    )
    citation = LlmCitation(chunk_id="c46", article_number="46")
    assert _is_legally_relevant_citation(citation, section, "privacy_notice") is False


def test_legal_relevance_rejects_article_44_without_transfer_signals():
    section = SectionData(
        id="s4b",
        section_order=4,
        section_title="Data Categories",
        content="We process account and billing data to provide services.",
        page_start=4,
        page_end=4,
    )
    citation = LlmCitation(chunk_id="c44", article_number="44")
    assert _is_legally_relevant_citation(citation, section, "privacy_notice") is False


def test_legal_relevance_rejects_article_18_for_privacy_notice():
    section = SectionData(
        id="s4c",
        section_order=4,
        section_title="International Processing",
        content="Data may be transferred internationally.",
        page_start=4,
        page_end=4,
    )
    citation = LlmCitation(chunk_id="c18", article_number="18")
    assert _is_legally_relevant_citation(citation, section, "privacy_notice") is False


def test_legal_relevance_rejects_article_24_for_privacy_notice():
    section = SectionData(
        id="s4d",
        section_order=4,
        section_title="Privacy Notice",
        content="We process personal data for service delivery.",
        page_start=4,
        page_end=4,
    )
    citation = LlmCitation(chunk_id="c24", article_number="24")
    assert _is_legally_relevant_citation(citation, section, "privacy_notice") is False


def test_build_mandatory_notice_gap_when_multiple_required_disclosures_missing():
    section = SectionData(
        id="s5",
        section_order=5,
        section_title="Data We Collect",
        content="We collect technical and usage data from users.",
        page_start=5,
        page_end=5,
    )
    chunks = [
        RetrievalChunk(
            chunk_id="c13",
            article_number="13",
            article_title="Information to be provided",
            paragraph_ref=None,
            content="Controller shall provide identity, contact, legal basis and purposes",
            score=0.81,
        )
    ]
    finding = _build_mandatory_notice_gap(section, chunks)
    assert finding is not None
    assert finding.status == "gap"
    assert len(finding.citations) == 1


def test_fallback_notice_citations_deprioritizes_article_14_paragraph_5():
    section = SectionData(
        id="s6",
        section_order=6,
        section_title="Data We Collect",
        content="We collect profile and usage data from users.",
        page_start=6,
        page_end=6,
    )
    chunks = [
        RetrievalChunk(
            chunk_id="c14p5",
            article_number="14",
            article_title="Information to be provided",
            paragraph_ref="5",
            content="Paragraphs 1 to 4 shall not apply...",
            score=0.95,
        ),
        RetrievalChunk(
            chunk_id="c13p1",
            article_number="13",
            article_title="Information to be provided",
            paragraph_ref="1",
            content="Controller identity and legal basis must be provided",
            score=0.80,
        ),
    ]
    fallback = _fallback_notice_citations(section, chunks)
    assert fallback
    assert fallback[0].chunk_id == "c13p1"


def test_collection_mode_indirect_when_third_party_signals_present():
    section = SectionData(
        id="s7",
        section_order=7,
        section_title="Data Sources",
        content="We receive personal data from partners and suppliers.",
        page_start=7,
        page_end=7,
    )
    assert _collection_mode(section) == "indirect"


def test_collection_mode_unknown_when_no_source_signals():
    section = SectionData(
        id="s7b",
        section_order=7,
        section_title="General Principles",
        content="We process personal data in line with our privacy principles.",
        page_start=7,
        page_end=7,
    )
    assert _collection_mode(section) == "unknown"


def test_systemic_evidence_refs_use_section_refs_and_omission_flag():
    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="Data We Collect",
            content="We collect account and usage data to provide services.",
            page_start=1,
            page_end=1,
        )
    ]
    refs, omission_basis = _systemic_evidence_refs(
        "missing_legal_basis",
        sections,
        {
            "legal_basis_present": False,
        },
    )
    assert omission_basis is True
    assert any(ref.startswith("section:") for ref in refs)
    assert all(not ref.startswith("coverage_check:") for ref in refs)


def test_systemic_summary_text_uses_scoped_absence_statement_without_internal_tokens():
    summary = _systemic_summary_text("missing_legal_basis", ["section:s1:Data We Collect"], True)
    assert summary == "No explicit required disclosure was found in the provided notice text for this obligation."


def test_coverage_to_support_validator_requires_required_obligation_absence():
    refs = ["section:s1:Data We Collect", "obligation_map:legal_basis_present=not_visible"]
    assert _coverage_to_support_valid(
        "missing_legal_basis",
        refs,
        {"legal_basis_present": False},
        ["GDPR Art. 13(1)(c)", "GDPR Art. 14(1)(c)"],
    )
    assert not _coverage_to_support_valid(
        "missing_legal_basis",
        refs,
        {"legal_basis_present": True},
        ["GDPR Art. 13(1)(c)", "GDPR Art. 14(1)(c)"],
    )


def test_core_duty_completeness_records_suppression_ledger():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    db = SessionLocal()
    audit = Audit(document_id="doc-1", status="running")
    db.add(audit)
    db.commit()

    db.add(
        Finding(
            audit_id=audit.id,
            section_id="systemic:missing_legal_basis",
            status="gap",
            severity="high",
            classification="systemic_violation",
            finding_type="systemic",
            publish_flag="yes",
            gap_note="Missing legal basis",
            remediation_note="Add legal basis",
        )
    )
    db.commit()

    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="Policy Owner",
            content="Administrative owner details only.",
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {
        "controller_identity_present": False,
        "controller_contact_present": False,
        "legal_basis_present": False,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
    _enforce_core_and_specialist_completeness(db, audit.id, sections, obligation_map)

    ledger_rows = db.query(Finding).filter(Finding.section_id.like("ledger:%")).all()
    assert ledger_rows
    assert any("core_duty_completeness_gate" in (row.legal_requirement or "") for row in ledger_rows)


def test_extract_cross_references_detects_unseen_section():
    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="Section 1 Scope",
            content="Data subject rights are described in Section 10 of this notice.",
            page_start=1,
            page_end=1,
        )
    ]
    refs = _extract_notice_cross_references(sections)
    assert refs
    assert refs[0]["section_present_in_reviewed_source"] == "no"
    assert refs[0]["referenced_topic"] == "rights"


def test_source_scope_qualification_marks_partial_when_unseen_refs_exist():
    sections = [
        SectionData(
            id="s1",
            section_order=1,
            section_title="Section 1 Scope",
            content="Retention periods are described in Section 9.",
            page_start=1,
            page_end=1,
        )
    ]
    refs = _extract_notice_cross_references(sections)
    scope, confidence, unseen = _source_scope_qualification(sections, refs)
    assert scope == "partial_notice_excerpt"
    assert confidence >= 0.8
    assert "Section 9" in unseen
    assert _issue_has_unseen_reference("missing_retention_period", refs) is True


def test_collection_mode_direct_from_form_language():
    section = SectionData(
        id="s7d",
        section_order=7,
        section_title="Contact Form",
        content="We collect personal data directly when you submit our contact form.",
        page_start=7,
        page_end=7,
    )
    assert _collection_mode(section) == "direct"


def test_collection_mode_indirect_from_obtained_wording():
    section = SectionData(
        id="s7e",
        section_order=7,
        section_title="Partner Imports",
        content="Personal data is obtained from external sources and affiliate companies.",
        page_start=7,
        page_end=7,
    )
    assert _collection_mode(section) == "indirect"


def test_collection_mode_mixed_when_both_signals_present():
    section = SectionData(
        id="s7f",
        section_order=7,
        section_title="Data Sources",
        content="We collect data when you sign up and also receive profile attributes from partners.",
        page_start=7,
        page_end=7,
    )
    assert _collection_mode(section) == "mixed"


def test_collection_mode_direct_when_collect_personal_data_without_other_hints():
    section = SectionData(
        id="s7g",
        section_order=7,
        section_title="Data Handling",
        content="We collect personal data for account support and fraud prevention.",
        page_start=7,
        page_end=7,
    )
    assert _collection_mode(section) == "direct"


def test_notice_disclosure_section_false_for_non_notice_content():
    section = SectionData(
        id="s7h",
        section_order=7,
        section_title="Information Security",
        content="We apply technical and organizational controls for system hardening.",
        page_start=7,
        page_end=7,
    )
    assert _is_notice_disclosure_section(section) is False


def test_claim_types_extract_legal_basis_not_transfer():
    claims = _claim_types_from_text("Missing legal basis for processing under Article 13(1)(c).")
    assert "legal_basis" in claims
    assert "transfer" not in claims


def test_claim_types_extract_sensitive_and_profiling():
    claims = _claim_types_from_text("Profiling outputs and explicit consent for special category data under Article 9.")
    assert "profiling" in claims
    assert "sensitive_data" in claims


def test_claim_types_extract_right_to_object():
    claims = _claim_types_from_text("Data subjects have a right to object to direct marketing processing.")
    assert "right_to_object" in claims


def test_fallback_claim_types_from_section_for_transfer_topic():
    section = SectionData(
        id="sx1",
        section_order=1,
        section_title="International Transfers",
        content="We transfer data outside the EEA.",
        page_start=1,
        page_end=1,
    )
    inferred = _fallback_claim_types_from_section(section)
    assert "transfer" in inferred


def test_citation_claim_compatible_rejects_article_14_para_3_for_legal_basis_claim():
    citation = LlmCitation(chunk_id="c1", article_number="14", paragraph_ref="3-4")
    chunk = RetrievalChunk(
        chunk_id="c1",
        article_number="14",
        article_title="Information to be provided",
        paragraph_ref="3-4",
        content="timing for disclosure",
        score=0.91,
    )
    assert _citation_claim_compatible(citation, chunk, {"legal_basis"}) is False


def test_citation_claim_compatible_rejects_article_13_para_3_for_transfer_claim():
    citation = LlmCitation(chunk_id="c2", article_number="13", paragraph_ref="3-4")
    chunk = RetrievalChunk(
        chunk_id="c2",
        article_number="13",
        article_title="Information to be provided",
        paragraph_ref="3-4",
        content="further processing information",
        score=0.86,
    )
    assert _citation_claim_compatible(citation, chunk, {"transfer"}) is False


def test_citation_claim_compatible_allows_article_14_when_paragraph_unknown_for_legal_basis():
    citation = LlmCitation(chunk_id="c1", article_number="14", paragraph_ref=None)
    chunk = RetrievalChunk(
        chunk_id="c1",
        article_number="14",
        article_title="Information to be provided",
        paragraph_ref=None,
        content="controller shall provide legal basis",
        score=0.91,
    )
    assert _citation_claim_compatible(citation, chunk, {"legal_basis"}) is True


def test_build_transfer_gap_for_transfer_section():
    section = SectionData(
        id="s7i",
        section_order=7,
        section_title="International Transfers",
        content="We transfer data outside the EEA and rely on safeguards.",
        page_start=7,
        page_end=7,
    )
    chunks = [
        RetrievalChunk(
            chunk_id="c44",
            article_number="44",
            article_title="General principle for transfers",
            paragraph_ref=None,
            content="Any transfer of personal data ...",
            score=0.77,
        ),
        RetrievalChunk(
            chunk_id="c46",
            article_number="46",
            article_title="Transfers subject to safeguards",
            paragraph_ref="1",
            content="In the absence of an adequacy decision ...",
            score=0.74,
        ),
    ]
    finding = _build_transfer_gap(section, chunks)
    assert finding is not None
    assert finding.status == "gap"
    assert len(finding.citations) >= 1


def test_transfer_gap_prioritizes_transfer_articles():
    section = SectionData(
        id="s7j",
        section_order=7,
        section_title="International Transfers",
        content="We transfer data outside the EEA.",
        page_start=7,
        page_end=7,
    )
    chunks = [
        RetrievalChunk(chunk_id="c13", article_number="13", article_title="", paragraph_ref="1", content="notice text", score=0.95),
        RetrievalChunk(chunk_id="c45", article_number="45", article_title="", paragraph_ref="1", content="adequacy text", score=0.70),
    ]
    finding = _build_transfer_gap(section, chunks)
    assert finding is not None
    assert finding.citations[0].article_number == "45"


def test_build_retention_gap_returns_gap_with_articles_13_14_5():
    section = SectionData(
        id="sx2",
        section_order=2,
        section_title="Retention",
        content="We keep data while needed.",
        page_start=2,
        page_end=2,
    )
    chunks = [
        RetrievalChunk(chunk_id="c5", article_number="5", article_title="", paragraph_ref="1(e)", content="storage limitation", score=0.75),
        RetrievalChunk(chunk_id="c13", article_number="13", article_title="", paragraph_ref="2", content="retention period", score=0.71),
    ]
    finding = _build_retention_gap(section, chunks)
    assert finding is not None
    assert finding.status == "gap"
    assert len(finding.citations) >= 1


def test_sanitize_legal_reference_fixes_wrong_article_pointer():
    text = "Legal basis should be disclosed under Article 14(1)(f)."
    assert _sanitize_legal_reference_text(text) == "Legal basis should be disclosed under Article 14(1)(c)."


def test_sanitize_legal_reference_fixes_article_letter_notation():
    text = "Controller identity under Article 13(a), DPO under Article 14(b)."
    assert _sanitize_legal_reference_text(text) == "Controller identity under Article 13(1)(a), DPO under Article 14(1)(b)."


def test_internal_control_only_detection_for_breach_workflow_language():
    assert _finding_mentions_internal_control_only("Missing undue delay breach notification workflow under Article 33.") is True


def test_tailored_notice_gap_and_remediation_use_generic_template():
    section = SectionData(
        id="s7m",
        section_order=7,
        section_title="Data Collection",
        content="We collect and process personal data.",
        page_start=7,
        page_end=7,
    )
    finding = _build_mandatory_notice_gap(
        section,
        [
            RetrievalChunk(
                chunk_id="c13",
                article_number="13",
                article_title="Information to be provided",
                paragraph_ref="1",
                content="controller shall provide identity and contact details",
                score=0.80,
            )
        ],
    )
    assert finding is not None
    assert "appears to omit mandatory privacy-notice disclosures" in (finding.gap_note or "")
    assert "identify the specific controller entity and add contact details" in (finding.remediation_note or "")


def test_salvage_citations_from_retrieved_returns_claim_compatible_candidates():
    section = SectionData(
        id="s7k",
        section_order=7,
        section_title="Data Processing",
        content="We process personal data for service delivery.",
        page_start=7,
        page_end=7,
    )
    chunks = [
        RetrievalChunk(chunk_id="c14p34", article_number="14", article_title="", paragraph_ref="3-4", content="timing", score=0.90),
        RetrievalChunk(chunk_id="c14p1", article_number="14", article_title="", paragraph_ref="1", content="legal basis", score=0.81),
    ]
    salvaged = _salvage_citations_from_retrieved(chunks, section, "privacy_notice", "Missing legal basis disclosure")
    assert salvaged
    assert salvaged[0].chunk_id == "c14p1"


def test_targeted_notice_query_uses_article_14_for_indirect_mode():
    section = SectionData(
        id="s7c",
        section_order=7,
        section_title="Partner Data",
        content="We receive account data from partners and suppliers.",
        page_start=7,
        page_end=7,
    )
    q = _targeted_notice_query(section)
    assert "Article 14(1)(a)-(f)" in q


def test_fallback_notice_citations_excludes_article_14_para_3_4_when_better_fit_exists():
    section = SectionData(
        id="s8",
        section_order=8,
        section_title="Data Sources",
        content="We collect personal data from users directly.",
        page_start=8,
        page_end=8,
    )
    chunks = [
        RetrievalChunk(
            chunk_id="c14p34",
            article_number="14",
            article_title="Information to be provided",
            paragraph_ref="3-4",
            content="timing of information provision",
            score=0.95,
        ),
        RetrievalChunk(
            chunk_id="c13p1",
            article_number="13",
            article_title="Information to be provided",
            paragraph_ref="1",
            content="identity, legal basis, purposes",
            score=0.70,
        ),
    ]
    fallback = _fallback_notice_citations(section, chunks)
    assert fallback
    assert all(c.chunk_id != "c14p34" for c in fallback)


def test_claim_has_primary_anchor_requires_matching_claim_articles():
    citations = [LlmCitation(chunk_id="c1", article_number="21")]
    assert _claim_has_primary_anchor({"complaint"}, citations) is False
    citations.append(LlmCitation(chunk_id="c2", article_number="77"))
    assert _claim_has_primary_anchor({"complaint"}, citations) is True


def test_normalize_severity_applies_policy_buckets():
    assert _normalize_severity("gap", "high", {"retention"}) == "medium"
    assert _normalize_severity("partial", None, {"rights"}) == "high"
    assert _normalize_severity("gap", "medium", {"purpose_mapping"}) == "medium"
    assert _normalize_severity("compliant", "high", {"rights"}) is None


def test_finding_signature_is_stable_for_same_semantics():
    finding = LlmFinding(status="gap", severity="high", gap_note="Missing legal basis details", remediation_note=None, citations=[])
    cits_a = [LlmCitation(chunk_id="x1", article_number="13"), LlmCitation(chunk_id="x2", article_number="6")]
    cits_b = [LlmCitation(chunk_id="x3", article_number="6"), LlmCitation(chunk_id="x4", article_number="13")]
    assert _finding_signature(finding, cits_a) == _finding_signature(finding, cits_b)


def test_ensure_reasoning_chain_adds_evidence_requirement_assessment():
    section = SectionData(
        id="s9",
        section_order=9,
        section_title="Legal Basis",
        content="We process data to improve service quality.",
        page_start=9,
        page_end=9,
    )
    finding = LlmFinding(
        status="gap",
        severity="high",
        gap_note="Missing explicit lawful basis mapping.",
        remediation_note="Add lawful basis by purpose.",
        citations=[],
    )
    updated = _ensure_reasoning_chain(
        finding,
        section,
        [LlmCitation(chunk_id="c13", article_number="13")],
        {"legal_basis"},
    )
    assert "Fact:" in (updated.gap_note or "")
    assert "Law:" in (updated.gap_note or "")
    assert "Breach:" in (updated.gap_note or "")
    assert "Conclusion:" in (updated.gap_note or "")


def test_clean_remediation_rewrites_wrong_13_1_f_legal_basis_reference():
    remediation = "Cite Article 13(1)(f) as the legal basis for this disclosure."
    cleaned = _clean_remediation_legal_mismatches(remediation, {"legal_basis"})
    assert "Article 6(1)" in (cleaned or "")


def test_classify_finding_quality_outputs_probable_gap_for_core_notice_without_citations():
    finding = LlmFinding(status="gap", severity="high", gap_note="Missing retention.", remediation_note="Add retention.", citations=[])
    klass, conf = _classify_finding_quality(finding, [], {"retention"}, "direct")
    assert klass == "probable_gap"
    assert conf is not None and conf >= 0.55


def test_claim_type_to_issue_mapping_uses_canonical_issue_families():
    from app.services.audit_runner import _claim_type_to_issue_id

    assert _claim_type_to_issue_id("controller_contact") == "missing_controller_contact"
    assert _claim_type_to_issue_id("transfer") == "missing_transfer_notice"
    assert _claim_type_to_issue_id("profiling") == "profiling_disclosure_gap"


def test_classify_finding_quality_avoids_not_assessable_for_specialist_claim_without_citations():
    finding = LlmFinding(status="gap", severity="medium", gap_note="Profiling signals visible.", remediation_note="Add profiling disclosures.", citations=[])
    klass, conf = _classify_finding_quality(finding, [], {"profiling"}, "direct")
    assert klass == "probable_gap"
    assert conf is not None and conf >= 0.5


def test_classify_finding_quality_treats_role_ambiguity_as_presumptively_assessable_without_citations():
    finding = LlmFinding(
        status="gap",
        severity="medium",
        gap_note="Controller/processor role language is ambiguous in notice sections.",
        remediation_note="Clarify roles by processing purpose.",
        citations=[],
    )
    klass, conf = _classify_finding_quality(finding, [], {"role_ambiguity"}, "direct")
    assert klass == "probable_gap"
    assert conf is not None and conf >= 0.5


def test_classify_finding_quality_allows_not_assessable_when_excerpt_is_fragmentary():
    finding = LlmFinding(
        status="gap",
        severity="medium",
        gap_note="Fragmentary excerpt; unseen section needed for legal conclusion.",
        remediation_note=None,
        citations=[],
    )
    klass, conf = _classify_finding_quality(finding, [], {"role_ambiguity"}, "direct")
    assert klass == "not_assessable"
    assert conf == 0.2


def test_classify_finding_quality_marks_needs_review_as_probable_gap_for_core_notice():
    finding = LlmFinding(status="needs review", severity=None, gap_note="insufficient evidence", remediation_note=None, citations=[])
    klass, conf = _classify_finding_quality(finding, [], {"retention"}, "unknown")
    assert klass == "probable_gap"
    assert conf == 0.55


def test_validate_citations_rejects_article_14_for_direct_collection_notice_claims():
    section = SectionData(
        id="sx10",
        section_order=10,
        section_title="Account Registration",
        content="We collect personal data directly when you create an account.",
        page_start=10,
        page_end=10,
    )
    chunk = RetrievalChunk(
        chunk_id="c14",
        article_number="14",
        article_title="Information to be provided where personal data have not been obtained",
        paragraph_ref="1",
        content="The controller shall provide information where personal data are not obtained from the data subject.",
        score=0.9,
    )
    citation = LlmCitation(chunk_id="c14", article_number="14", paragraph_ref="1")
    valid = _validate_citations(
        [citation],
        [chunk],
        section,
        "privacy_notice",
        claim_text="Missing legal basis and rights disclosure",
    )
    assert valid == []


def test_validate_citations_rejects_article_21_for_complaint_claims():
    section = SectionData(
        id="sx11",
        section_order=11,
        section_title="Complaint Rights",
        content="You may file complaints with your supervisory authority.",
        page_start=11,
        page_end=11,
    )
    chunk = RetrievalChunk(
        chunk_id="c21",
        article_number="21",
        article_title="Right to object",
        paragraph_ref="1-2",
        content="The data subject shall have the right to object.",
        score=0.88,
    )
    citation = LlmCitation(chunk_id="c21", article_number="21", paragraph_ref="1-2")
    valid = _validate_citations(
        [citation],
        [chunk],
        section,
        "privacy_notice",
        claim_text="Missing complaint mechanism and supervisory authority details",
    )
    assert valid == []


def test_document_posture_agent_identifies_notice_excerpt():
    sections = [
        SectionData(
            id="p1",
            section_order=1,
            section_title="Privacy Notice",
            content="This privacy notice explains legal basis and rights.",
            page_start=1,
            page_end=1,
        )
    ]
    posture = _document_posture_agent(sections, "privacy_notice")
    assert "external_privacy_notice" in posture["document_type"]
    assert "articles_12_14_transparency" in posture["triggered_duties"]


def test_reviewer_agent_downgrades_not_assessable_visibility():
    finding = LlmFinding(status="gap", severity="high", gap_note="Possible issue", remediation_note="Fix", citations=[])
    memo = _applicability_memo(
        SectionData(
            id="p2",
            section_order=2,
            section_title="Snippet",
            content="Short.",
            page_start=2,
            page_end=2,
        ),
        {"legal_basis"},
        {"document_type": "external_privacy_notice_excerpt", "triggered_duties": [], "not_triggered_duties": [], "not_assessable_duties": []},
    )
    reviewed, reviewed_citations = _reviewer_agent(finding, [], {"legal_basis"}, memo)
    assert reviewed.status == "needs review"
    assert reviewed_citations == []


def test_applicability_memo_keeps_explicit_consent_excerpt_assessable_even_if_short():
    memo = _applicability_memo(
        SectionData(
            id="p2b",
            section_order=2,
            section_title="Consent snippet",
            content="Consent is inferred from continued use.",
            page_start=2,
            page_end=2,
        ),
        {"legal_basis"},
        {"document_type": "external_privacy_notice_excerpt", "triggered_duties": [], "not_triggered_duties": [], "not_assessable_duties": []},
    )
    assert memo["visibility"] != "not_assessable"


def test_not_assessable_gate_forbids_explicit_unlawful_patterns():
    text = "Consent inferred from continued use and retained indefinitely."
    assert _not_assessable_allowed(text, "needs review", "not_assessable") is False


def test_document_wide_duty_validation_marks_compliant_notice_as_compliant():
    sections = [
        SectionData(
            id="sec-duty-ok",
            section_order=1,
            section_title="Privacy notice",
            content=(
                "Controller identity and contact route are provided. Specific purpose statements are listed. "
                "Lawful basis disclosed and mapped to purpose where needed. Recipient categories are disclosed. "
                "Transfer disclosed with safeguard mechanism. Specific retention period and objective criteria are stated. "
                "Rights listed and actionable. Supervisory authority complaint right disclosed. "
                "Profiling logic involved significance and effects safeguards where relevant."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    out = _document_wide_duty_validation(sections, "external_privacy_notice")
    assert out["controller_identity_contact"] == "compliant"
    assert out["legal_basis_notice"] == "compliant"
    assert out["retention_notice"] == "compliant"
    assert out["rights_notice"] == "compliant"
    assert out["complaint_right_notice"] == "compliant"


def test_document_wide_duty_validation_marks_non_compliant_notice_as_non_compliant():
    sections = [
        SectionData(
            id="sec-duty-bad",
            section_order=1,
            section_title="Privacy notice",
            content=(
                "Consent inferred from use of the service. Archived datasets may be retained indefinitely "
                "and safeguards where practical may be used for transfers."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    out = _document_wide_duty_validation(sections, "external_privacy_notice")
    assert out["legal_basis_notice"] == "non_compliant"
    assert out["retention_notice"] == "non_compliant"
    assert out["transfers_notice"] == "non_compliant"


def test_document_wide_duty_validation_compliant_privacy_notice_specialists_resolve():
    sections = [
        SectionData(
            id="sec-good-full",
            section_order=1,
            section_title="Privacy Notice",
            content=(
                "ACME Corp LLC is the controller and can be contacted at privacy@acme.com. "
                "We process data for fraud prevention, account security, payment processing, and support requests. "
                "Legal basis includes contract, legal obligation, and legitimate interests for each purpose. "
                "Retention period is 24 months or longer only where required by law and objective criteria are documented. "
                "You have rights of access, rectification, erasure, restriction, objection, and portability. "
                "You may lodge a complaint with your supervisory authority. "
                "International transfers outside the EEA use Standard Contractual Clauses and adequacy decisions. "
                "Recipient categories include processors, payment providers, cloud providers, and support vendors. "
                "We use profiling for fraud prevention with meaningful information about the logic, significance, effects, and human intervention."
            ),
            page_start=1,
            page_end=2,
        )
    ]
    out = _document_wide_duty_validation(sections, "external_privacy_notice")
    assert out["controller_identity_contact"] == "compliant"
    assert out["legal_basis_notice"] in {"compliant", "partially_compliant"}
    assert out["retention_notice"] in {"compliant", "partially_compliant"}
    assert out["rights_notice"] == "compliant"
    assert out["complaint_right_notice"] == "compliant"
    assert out["transfers_notice"] in {"compliant", "partially_compliant"}
    assert out["profiling_notice"] in {"compliant", "partially_compliant"}
    disposition = _build_final_disposition_map([], sections, {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True})
    assert disposition["transfer"]["status"] in {"satisfied", "not_triggered"}
    assert disposition["profiling"]["status"] in {"satisfied", "not_triggered"}
    assert disposition["recipients"]["status"] in {"satisfied", "not_triggered"}
    assert disposition["role_ambiguity"]["publication_recommendation"] == "internal_only"


def test_document_wide_duty_validation_non_compliant_privacy_notice_promotes_failures():
    sections = [
        SectionData(
            id="sec-bad-full",
            section_order=1,
            section_title="Privacy Notice",
            content=(
                "We collect personal data. Consent inferred from continued use. "
                "Archived datasets may be retained indefinitely for operational needs. "
                "We transfer data outside the EEA with safeguards where practical. "
                "We use automated profiling without logic explanation."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    out = _document_wide_duty_validation(sections, "external_privacy_notice")
    assert out["legal_basis_notice"] == "non_compliant"
    assert out["retention_notice"] == "non_compliant"
    assert out["transfers_notice"] == "non_compliant"
    assert out["profiling_notice"] == "non_compliant"


def test_benchmark_compliant_forbidden_major_findings_do_not_survive():
    sections = [
        SectionData(
            id="bench-ok-1",
            section_order=1,
            section_title="Privacy Notice",
            content=(
                "Controller identity and contact details are provided. "
                "We set out lawful bases and purpose mapping. "
                "Data subject rights include access, rectification, erasure, restriction, portability and objection. "
                "You can lodge a complaint with a supervisory authority. "
                "Retention periods and objective criteria are listed. "
                "International transfers use adequacy decisions and SCC safeguards."
            ),
            page_start=1,
            page_end=2,
        )
    ]
    out = _document_wide_duty_validation(sections, "privacy_notice")
    forbidden = {
        "legal_basis_notice",
        "rights_notice",
        "complaint_right_notice",
        "retention_notice",
        "transfers_notice",
    }
    assert all(out[duty] == "compliant" for duty in forbidden)


def test_benchmark_noncompliant_required_major_findings_are_present():
    sections = [
        SectionData(
            id="bench-bad-1",
            section_order=1,
            section_title="Bad Privacy Notice",
            content=(
                "By continuing to use this site, you consent to all processing. "
                "We keep data indefinitely including archives and logs. "
                "Transfers may occur globally with appropriate safeguards where possible. "
                "Some rights may apply. "
                "We use cookies, ad networks and profiling for risk scores without detailed logic explanations."
            ),
            page_start=1,
            page_end=2,
        )
    ]
    out = _document_wide_duty_validation(sections, "privacy_notice")
    required_non_compliant = {
        "legal_basis_notice",
        "retention_notice",
        "transfers_notice",
        "profiling_notice",
        "cookies_consent_notice",
    }
    assert all(out[duty] == "non_compliant" for duty in required_non_compliant)


def test_document_wide_duty_validation_cookie_notice_consent_modes():
    good_sections = [
        SectionData(
            id="cookie-good",
            section_order=1,
            section_title="Cookie Notice",
            content=(
                "We use analytics cookie and advertising cookie technologies. "
                "Non-essential cookies require opt-in prior consent via consent banner with accept all / reject all controls. "
                "You can withdraw consent and change cookie settings at any time."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    bad_sections = [
        SectionData(
            id="cookie-bad",
            section_order=1,
            section_title="Cookie Notice",
            content="Analytics cookie and advertising cookie are used and continued usage means consent.",
            page_start=1,
            page_end=1,
        )
    ]
    good = _document_wide_duty_validation(good_sections, "consent_text")
    bad = _document_wide_duty_validation(bad_sections, "consent_text")
    assert good["cookies_consent_notice"] == "compliant"
    assert bad["cookies_consent_notice"] == "non_compliant"


def test_document_wide_duty_validation_dpa_and_internal_policy_are_document_type_sensitive():
    dpa_sections = [
        SectionData(
            id="dpa-1",
            section_order=1,
            section_title="Data Processing Agreement",
            content=(
                "For our own purposes we act as controller. For customer instructions we act as processor on behalf of customers. "
                "Role allocation and responsibilities are defined in this agreement."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    internal_sections = [
        SectionData(
            id="int-1",
            section_order=1,
            section_title="Internal privacy governance policy",
            content=(
                "Roles and responsibilities define controller and processor accountability and incident response. "
                "Data protection officer is appointed and can be contacted at dpo@example.com."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    dpa_out = _document_wide_duty_validation(dpa_sections, "dpa")
    internal_out = _document_wide_duty_validation(internal_sections, "internal_policy")
    assert dpa_out["role_allocation_notice"] == "compliant"
    assert "rights_notice" not in dpa_out
    assert internal_out["dpo_contact_notice"] == "compliant"
    assert "complaint_right_notice" not in internal_out


def test_final_disposition_honors_duty_validation_for_core_compliance():
    sections = [
        SectionData(
            id="sec-core",
            section_order=1,
            section_title="Privacy notice",
            content="Lawful basis includes contract and legal obligation. Retention period is 24 months.",
            page_start=1,
            page_end=1,
        )
    ]
    disposition = _build_final_disposition_map(
        [],
        sections,
        {"controller_contact": False, "legal_basis": False, "retention": False, "rights": False, "complaint": False},
        {"legal_basis_notice": "compliant", "retention_notice": "compliant"},
    )
    assert disposition["legal_basis"]["status"] == "satisfied"
    assert disposition["retention"]["status"] == "satisfied"
    assert disposition["legal_basis"]["publication_recommendation"] == "internal_only"


def test_cross_stage_controller_contact_remains_suppressed_when_duty_compliant():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        audit = Audit(document_id="doc-x", status="running")
        db.add(audit)
        db.flush()
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="systemic:missing_controller_contact",
                status="gap",
                severity="high",
                classification="systemic_violation",
                finding_type="systemic",
                publish_flag="yes",
                publication_state="publishable",
                gap_note="Controller contact route missing.",
            )
        )
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="sec-intro",
                status="compliant",
                severity=None,
                classification="no_issue",
                finding_type="supporting_evidence",
                publish_flag="no",
                publication_state="internal_only",
                policy_evidence_excerpt='ACME Corp Ltd, contact privacy@acme.com.',
            )
        )
        db.commit()
        _partner_review_pass(db, audit.id, {"controller_identity_contact": "compliant"})
        rows = db.query(Finding).filter(Finding.audit_id == audit.id).all()
        controller_rows = [r for r in rows if r.section_id == "systemic:missing_controller_contact"]
        assert controller_rows
        assert controller_rows[0].publish_flag == "no"
        disposition = _build_final_disposition_map(rows, [], {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True}, {"controller_identity_contact": "compliant"})
        assert disposition["controller_identity_contact"]["status"] == "satisfied"
        assert disposition["controller_identity_contact"]["publication_recommendation"] == "internal_only"


def test_severity_calibration_deterministic_for_core_and_specialist_claims():
    assert _normalize_severity("gap", None, {"legal_basis"}) == "high"
    assert _normalize_severity("gap", None, {"rights"}) == "high"
    assert _normalize_severity("gap", None, {"complaint"}) == "high"
    assert _normalize_severity("gap", None, {"transfer"}) == "high"
    assert _normalize_severity("gap", None, {"profiling"}) == "high"
    assert _normalize_severity("gap", None, {"retention"}) == "medium"
    assert _normalize_severity("gap", None, {"recipients"}) == "medium"


def test_confidence_calibration_spreads_high_and_low_ranges():
    high_finding = LlmFinding(status="gap", severity="high", gap_note="clear transfer gap", remediation_note="fix", citations=[])
    high_citations = [
        LlmCitation(chunk_id="c1", article_number="13", paragraph_ref="1(f)", article_title="info", excerpt="x"),
        LlmCitation(chunk_id="c2", article_number="44", paragraph_ref=None, article_title="transfer", excerpt="y"),
        LlmCitation(chunk_id="c3", article_number="46", paragraph_ref=None, article_title="safeguards", excerpt="z"),
    ]
    klass_high, conf_high = _classify_finding_quality(high_finding, high_citations, {"transfer"}, "direct")
    low_finding = LlmFinding(status="needs review", severity=None, gap_note="fragmentary excerpt", remediation_note=None, citations=[])
    klass_low, conf_low = _classify_finding_quality(low_finding, [], {"legal_basis"}, "unknown")
    assert klass_high in {"clear_non_compliance", "probable_gap"}
    assert conf_high is not None and conf_high >= 0.85
    assert klass_low == "not_assessable"
    assert conf_low is not None and conf_low <= 0.3


def test_issue_relevance_score_prefers_retention_over_transfer_for_retention_section():
    section = SectionData(
        id="ret-sec",
        section_order=1,
        section_title="Data Retention",
        content="We retain personal data for 24 months and then delete it.",
        page_start=1,
        page_end=1,
    )
    retention_score = _issue_relevance_score("missing_retention", section)
    transfer_score = _issue_relevance_score("missing_transfer_notice", section)
    assert retention_score > transfer_score


def test_applicability_decision_direct_allows_article_13():
    section = SectionData(
        id="a1",
        section_order=1,
        section_title="Signup",
        content="We collect personal data directly from you via forms.",
        page_start=1,
        page_end=1,
    )
    memo = _applicability_memo(
        section,
        {"legal_basis"},
        {"document_type": "external_privacy_notice", "triggered_duties": [], "not_triggered_duties": [], "not_assessable_duties": []},
    )
    decision = _applicability_decision(section, memo)
    assert decision["allowed_notice_articles"] == [13]


def test_applicability_gate_filters_disallowed_notice_article():
    citations = [
        LlmCitation(chunk_id="c13", article_number="13"),
        LlmCitation(chunk_id="c14", article_number="14"),
    ]
    decision = {
        "collection_mode": "direct",
        "applicability_status": "confirmed",
        "allowed_notice_articles": [13],
        "unresolved_trigger": None,
    }
    gated = _apply_applicability_gate_to_citations(citations, decision, {"legal_basis"})
    assert len(gated) == 1
    assert gated[0].article_number == "13"


def test_section_auditability_identifies_definition_section():
    section = SectionData(
        id="q1",
        section_order=1,
        section_title="Definitions",
        content="This glossary defines terminology used in this notice.",
        page_start=1,
        page_end=1,
    )
    assert _section_auditability_type(section) == "definition_section"


def test_spot_candidate_issues_returns_notice_missing_candidates():
    section = SectionData(
        id="q2",
        section_order=2,
        section_title="Data We Collect",
        content="We collect identifiers and usage data.",
        page_start=2,
        page_end=2,
    )
    issues = _spot_candidate_issues(section, "direct")
    assert any(i["candidate_issue_type"] == "missing_legal_basis" for i in issues)


def test_spot_candidate_issues_fact_fallback_prefers_article14_for_third_party_source():
    section = SectionData(
        id="q2b",
        section_order=2,
        section_title="Data sources",
        content="We obtain personal data from third parties and external datasets.",
        page_start=2,
        page_end=2,
    )
    issues = _spot_candidate_issues(section, "indirect")
    assert issues
    assert issues[0]["candidate_issue_type"] == "article_14_indirect_collection_gap"


def test_spot_candidate_issues_applies_mandatory_legal_posture_layer_for_invalid_consent():
    section = SectionData(
        id="q2c",
        section_order=3,
        section_title="Lawful basis",
        content="Consent is inferred from continued use of the service.",
        page_start=3,
        page_end=3,
    )
    issues = _spot_candidate_issues(section, "direct")
    legal_basis_issue = next(i for i in issues if i["candidate_issue_type"] == "missing_legal_basis")
    assert legal_basis_issue["legal_posture"] == "present_but_legally_invalid"
    assert "Art. 6/7" in legal_basis_issue["legal_posture_reason"]


def test_legal_qualification_maps_transfer_notice_to_13_1_f():
    issue = {
        "candidate_issue_type": "missing_transfer_notice",
        "evidence_text": "Transfers occur",
        "evidence_strength": 0.7,
        "local_or_document_level": "local",
        "possible_collection_mode": "indirect",
        "is_visible_gap": True,
    }
    qual = _legal_qualification_for_issue(issue)
    assert qual["primary_article"] == "13(1)(f)"
    assert qual["obligation_family"] == "international_transfers"
    assert qual["defect_type"] == "missing_disclosure"


def test_legal_qualification_keeps_legal_basis_in_notice_family_without_validity_signal():
    issue = {
        "candidate_issue_type": "missing_legal_basis",
        "evidence_text": "We process personal data for service delivery.",
        "evidence_strength": 0.7,
        "local_or_document_level": "local",
        "possible_collection_mode": "direct",
        "is_visible_gap": True,
    }
    qual = _legal_qualification_for_issue(issue, [])
    assert qual["primary_article"] == "13(1)(c)"
    assert "14(1)(c)" in qual["secondary_articles"]
    assert "6(1)" not in qual["secondary_articles"]
    assert "7(1)" not in qual["secondary_articles"]


def test_forbidden_matrix_rejects_article_21_for_complaint():
    citations = [LlmCitation(chunk_id="z1", article_number="21")]
    assert _violates_forbidden_article_matrix({"complaint"}, citations) is True


def test_legal_qualification_marks_invalid_consent_wording_as_present_but_invalid():
    issue = {
        "candidate_issue_type": "missing_legal_basis",
        "evidence_text": "Consent is inferred from continued use of the service.",
        "evidence_strength": 0.7,
        "local_or_document_level": "local",
        "possible_collection_mode": "direct",
        "is_visible_gap": True,
    }
    qual = _legal_qualification_for_issue(issue)
    assert qual["defect_type"] == "potential_unlawful_practice"
    assert qual["primary_article"] == "6(1)"
    assert qual["obligation_family"] == "lawful_basis_and_validity"
    assert qual["priority_bucket"] == "fatal"


def test_legal_qualification_maps_indefinite_retention_to_storage_limitation_primary():
    issue = {
        "candidate_issue_type": "missing_retention",
        "evidence_text": "Data may be retained indefinitely for operational analytics.",
        "evidence_strength": 0.8,
        "local_or_document_level": "local",
        "possible_collection_mode": "direct",
        "is_visible_gap": True,
    }
    qual = _legal_qualification_for_issue(issue)
    assert qual["defect_type"] == "potential_unlawful_practice"
    assert qual["primary_article"] == "5(1)(e)"
    assert qual["priority_bucket"] == "fatal"


def test_legal_qualification_adds_article_22_only_when_profiling_is_truly_triggered():
    issue = {
        "candidate_issue_type": "profiling_disclosure_gap",
        "evidence_text": "We use profiling for service optimization.",
        "evidence_strength": 0.6,
        "local_or_document_level": "local",
        "possible_collection_mode": "direct",
        "is_visible_gap": True,
    }
    qual_plain = _legal_qualification_for_issue(issue, [])
    assert "22" not in qual_plain["secondary_articles"]

    facts = _extract_legal_facts("Automated decisions may produce legal effects without human intervention.")
    qual_triggered = _legal_qualification_for_issue(issue, facts)
    assert "22" in qual_triggered["secondary_articles"]


def test_legal_qualification_uses_facts_to_mark_lawful_basis_present_but_unmapped():
    issue = {
        "candidate_issue_type": "missing_legal_basis",
        "evidence_text": "Legal basis is listed but not mapped by purpose.",
        "evidence_strength": 0.8,
        "local_or_document_level": "local",
        "possible_collection_mode": "direct",
        "is_visible_gap": True,
    }
    facts = _extract_legal_facts("Our legal basis includes legitimate interests for processing.")
    qual = _legal_qualification_for_issue(issue, facts)
    assert qual["defect_type"] == "present_but_invalid_disclosure"


def test_legal_qualification_uses_facts_to_mark_recipients_present_but_unstructured():
    issue = {
        "candidate_issue_type": "recipients_disclosure_gap",
        "evidence_text": "We share with partners and vendors.",
        "evidence_strength": 0.7,
        "local_or_document_level": "local",
        "possible_collection_mode": "direct",
        "is_visible_gap": True,
    }
    facts = _extract_legal_facts("We disclose personal data to partners and vendors.")
    qual = _legal_qualification_for_issue(issue, facts)
    assert qual["defect_type"] == "present_but_invalid_disclosure"


def test_extract_legal_facts_captures_partner_source_and_undefined_retention():
    facts = _extract_legal_facts(
        "We may collect data from partners and external datasets and keep data as long as necessary."
    )
    fact_types = {f["fact_type"] for f in facts}
    assert "data_source" in fact_types
    assert "retention_policy" in fact_types


def test_extract_legal_facts_captures_transfer_recipients_and_unmapped_lawful_basis():
    facts = _extract_legal_facts(
        "We transfer personal data outside the EEA to service providers and partners. "
        "Our legal basis includes legitimate interests."
    )
    indexed = {(f["fact_type"], f["value"]) for f in facts}
    assert ("transfer_scope", "outside_jurisdiction") in indexed
    assert ("recipient_categories", "missing") in indexed
    assert ("lawful_basis", "present") in indexed
    assert ("lawful_basis", "present_but_unmapped") in indexed


def test_legal_reasoning_step_outputs_text_to_fact_to_family_flow():
    section = SectionData(
        id="sec-flow",
        section_order=1,
        section_title="Data sources",
        content="We may collect data from partners and public records.",
        page_start=1,
        page_end=1,
    )
    issue = {
        "candidate_issue_type": "article_14_indirect_collection_gap",
        "evidence_text": section.content,
        "evidence_strength": 0.7,
        "local_or_document_level": "local",
        "possible_collection_mode": "indirect",
        "is_visible_gap": True,
    }
    qual = _legal_qualification_for_issue(issue)
    facts, narrative = _legal_reasoning_step(section, issue, qual)
    assert any(f["fact_type"] == "data_source" and f["value"] == "third_party" for f in facts)
    assert "triggered_obligation_family=indirect_collection_article14" in narrative
    assert "obligation_validation" in narrative


def test_validate_family_obligations_for_article14_reports_missing_obligations():
    text = "We receive data from third parties and external datasets."
    facts = _extract_legal_facts(text)
    out = _validate_family_obligations("indirect_collection_article14", text, facts)
    assert out["satisfied"] is False
    missing = set(out["missing"])
    assert "legal_basis" in missing
    assert "rights" in missing


def test_classify_finding_quality_uses_visible_violation_rule_without_citations():
    finding = LlmFinding(
        status="gap",
        severity="high",
        gap_note="The policy states retention is indefinite retention for all account data.",
        remediation_note="Define bounded retention periods.",
        citations=[],
    )
    klass, conf = _classify_finding_quality(finding, [], {"retention"}, "direct")
    assert klass == "probable_gap"
    assert (conf or 0) >= 0.6
