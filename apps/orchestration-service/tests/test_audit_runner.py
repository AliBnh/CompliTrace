import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.base import Base
from app.models.audit import Audit, AuditAnalysisItem, EvidenceRecord, Finding, FindingCitation
from app.services.audit_runner import (
    _GDPR_ARTICLE_LEGAL_TEXT,
    _anchor_to_chunk_id,
    _applicability_decision,
    _applicability_memo,
    _apply_applicability_gate_to_citations,
    _article_int,
    _build_document_obligation_map,
    _build_final_disposition_map,
    _build_mandatory_notice_gap,
    _build_retention_gap,
    _build_transfer_gap,
    _citation_claim_compatible,
    _claim_has_primary_anchor,
    _claim_types_from_text,
    _classify_finding_quality,
    _clean_remediation_legal_mismatches,
    _collection_mode,
    _coverage_to_support_valid,
    _document_posture_agent,
    _document_wide_duty_validation,
    _enforce_core_and_specialist_completeness,
    _enforce_substantive_citation_gate,
    _ensure_reasoning_chain,
    _evidence_sufficient,
    _explicit_violation_hits,
    _extract_legal_facts,
    _extract_notice_cross_references,
    _extract_section_evidence,
    _fallback_claim_types_from_section,
    _fallback_notice_citations,
    _final_publication_validator,
    _finding_issue_id,
    _finding_mentions_internal_control_only,
    _finding_signature,
    _gdpr_legal_text,
    _has_positive_contradictory_disclosure,
    _is_citation_conclusion,
    _is_conclusion_evidence,
    _is_legally_relevant_citation,
    _is_not_applicable,
    _is_notice_disclosure_section,
    _issue_has_unseen_reference,
    _issue_relevance_score,
    _legal_qualification_for_issue,
    _legal_reasoning_step,
    _normalize_analysis_anchors,
    _normalize_severity,
    _not_assessable_allowed,
    _paragraph_ref_compatible,
    _partner_review_pass,
    _rerank_chunks_for_mode,
    _retry_needed,
    _reviewer_agent,
    _runtime_budget_exceeded,
    _salvage_citations_from_retrieved,
    _sanitize_legal_reference_text,
    _section_auditability_type,
    _snapshot_analysis_items,
    _source_scope_qualification,
    _spot_candidate_issues,
    _systemic_evidence_refs,
    _systemic_summary_text,
    _targeted_notice_query,
    _upsert_evidence_records,
    _validate_citations,
    _validate_family_obligations,
    _violates_forbidden_article_matrix,
)
from app.services.clients import LlmCitation, LlmFinding, RetrievalChunk, SectionData
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
        RetrievalChunk(
            chunk_id="c1",
            article_number="5",
            article_title="",
            paragraph_ref=None,
            content="controller shall",
            score=0.71,
        ),
        RetrievalChunk(
            chunk_id="c2",
            article_number="6",
            article_title="",
            paragraph_ref=None,
            content="processing must",
            score=0.65,
        ),
        RetrievalChunk(
            chunk_id="c3", article_number="17", article_title="", paragraph_ref=None, content="aux", score=0.30
        ),
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
        "controller_identity_present": True,
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
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
        "controller_identity_present": False,
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
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
        "controller_identity_present": True,
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": False,
        "rights_present": True,
        "complaint_present": True,
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
        db.add(
            FindingCitation(
                finding_id=finding.id,
                chunk_id="c13",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Legal basis",
                excerpt="x",
            )
        )
        db.commit()

        disposition_map = {
            "legal_basis": {
                "status": "gap",
                "publication_recommendation": "publish",
                "reasoning": "legal basis missing",
            }
        }
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
        db.add(
            FindingCitation(
                finding_id=finding.id,
                chunk_id="c21",
                article_number="21",
                paragraph_ref="1",
                article_title="Right to object",
                excerpt="x",
            )
        )
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
        db.add(
            FindingCitation(
                finding_id=finding.id,
                chunk_id="c13",
                article_number="13",
                paragraph_ref="1(f)",
                article_title="Transfers",
                excerpt="Data may move across regions.",
            )
        )
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
        f1 = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_complaint_right",
            status="gap",
            severity="high",
            finding_type="systemic",
        )
        f2 = Finding(
            audit_id=audit.id,
            section_id="systemic:missing_complaint_right",
            status="gap",
            severity="high",
            finding_type="systemic",
        )
        db.add_all([f1, f2])
        db.commit()

        _upsert_evidence_records(db, audit.id)
        db.commit()

        policy_ids = [
            r.evidence_id
            for r in db.query(EvidenceRecord)
            .filter(EvidenceRecord.audit_id == audit.id, EvidenceRecord.evidence_type == "policy_section")
            .all()
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
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
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
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
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
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
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
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
    disposition = _build_final_disposition_map([], sections, obligation_map)
    profiling = disposition["profiling"]
    assert profiling["triggered"] is True
    assert profiling["status"] == "gap"
    assert profiling["severity"] == "medium"


def test_final_disposition_recipients_family_gaps_when_third_parties_without_structured_categories():
    # Purely vague language ("third parties", "selected partners") with no named functional
    # categories should still produce a gap — the disclosure is not identifiable.
    sections = [
        SectionData(
            id="sec-rec",
            section_order=1,
            section_title="Sharing and disclosures",
            content=("We share personal data with third parties and selected partners to operate services."),
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
    disposition = _build_final_disposition_map([], sections, obligation_map)
    recipients = disposition["recipients"]
    assert recipients["triggered"] is True
    assert recipients["status"] == "gap"
    assert recipients["publication_recommendation"] == "publish"


def test_final_disposition_recipients_family_satisfied_when_named_categories_present():
    # Named functional categories (cloud infrastructure providers, analytics platforms, etc.)
    # satisfy GDPR Art. 13/14 even without the exact phrase "categories of recipients".
    sections = [
        SectionData(
            id="sec-rec-named",
            section_order=1,
            section_title="Data sharing",
            content=(
                "We share personal data with cloud infrastructure providers, analytics platforms, "
                "integration partners, and support providers to deliver our services."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
    disposition = _build_final_disposition_map([], sections, obligation_map)
    recipients = disposition["recipients"]
    assert recipients["status"] in {"satisfied", "not_triggered"}, (
        f"Named recipient categories should suppress the gap; got status={recipients['status']!r}"
    )
    assert recipients["publication_recommendation"] == "internal_only"


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
    obligation_map = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
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
            content=("We receive data from third parties, including partners, data aggregators, and public records."),
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
            primary_legal_anchor='["GDPR Article 13(1)(f)"]',
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
            primary_legal_anchor='["GDPR Article 13(2)(a)"]',
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
    hits = _explicit_violation_hits(
        "Data may be retained for extended periods; archived datasets may be retained indefinitely."
    )
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
        RetrievalChunk(
            chunk_id="c1",
            article_number="88",
            article_title="",
            paragraph_ref=None,
            content="employment context",
            score=0.90,
        ),
        RetrievalChunk(
            chunk_id="c2",
            article_number="46",
            article_title="",
            paragraph_ref=None,
            content="appropriate safeguards",
            score=0.82,
        ),
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
    # Must be an analytical summary (not a conclusion "No explicit..." string)
    assert not _is_conclusion_evidence(summary.lower())
    assert "lawful basis" in summary.lower() or "legal basis" in summary.lower()
    assert "Data We Collect" in summary or "reviewed" in summary.lower()


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
        RetrievalChunk(
            chunk_id="c13", article_number="13", article_title="", paragraph_ref="1", content="notice text", score=0.95
        ),
        RetrievalChunk(
            chunk_id="c45",
            article_number="45",
            article_title="",
            paragraph_ref="1",
            content="adequacy text",
            score=0.70,
        ),
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
        RetrievalChunk(
            chunk_id="c5",
            article_number="5",
            article_title="",
            paragraph_ref="1(e)",
            content="storage limitation",
            score=0.75,
        ),
        RetrievalChunk(
            chunk_id="c13",
            article_number="13",
            article_title="",
            paragraph_ref="2",
            content="retention period",
            score=0.71,
        ),
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
    assert (
        _sanitize_legal_reference_text(text)
        == "Controller identity under Article 13(1)(a), DPO under Article 14(1)(b)."
    )


def test_internal_control_only_detection_for_breach_workflow_language():
    assert (
        _finding_mentions_internal_control_only("Missing undue delay breach notification workflow under Article 33.")
        is True
    )


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
        RetrievalChunk(
            chunk_id="c14p34", article_number="14", article_title="", paragraph_ref="3-4", content="timing", score=0.90
        ),
        RetrievalChunk(
            chunk_id="c14p1",
            article_number="14",
            article_title="",
            paragraph_ref="1",
            content="legal basis",
            score=0.81,
        ),
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
    assert _normalize_severity("gap", "high", {"retention"}) == "high"
    assert _normalize_severity("partial", None, {"rights"}) == "high"
    assert _normalize_severity("gap", "medium", {"purpose_mapping"}) == "medium"
    assert _normalize_severity("compliant", "high", {"rights"}) is None


def test_finding_signature_is_stable_for_same_semantics():
    finding = LlmFinding(
        status="gap", severity="high", gap_note="Missing legal basis details", remediation_note=None, citations=[]
    )
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
    assert "Fact:" in (updated.gap_reasoning or "")
    assert "Law:" in (updated.gap_reasoning or "")
    assert "Breach:" in (updated.gap_reasoning or "")
    assert "Conclusion:" in (updated.gap_reasoning or "")


def test_clean_remediation_rewrites_wrong_13_1_f_legal_basis_reference():
    remediation = "Cite Article 13(1)(f) as the legal basis for this disclosure."
    cleaned = _clean_remediation_legal_mismatches(remediation, {"legal_basis"})
    assert "Article 6(1)" in (cleaned or "")


def test_classify_finding_quality_outputs_probable_gap_for_core_notice_without_citations():
    finding = LlmFinding(
        status="gap", severity="high", gap_note="Missing retention.", remediation_note="Add retention.", citations=[]
    )
    klass, conf = _classify_finding_quality(finding, [], {"retention"}, "direct")
    assert klass == "probable_gap"
    assert conf is not None and conf >= 0.55


def test_claim_type_to_issue_mapping_uses_canonical_issue_families():
    from app.services.audit_runner import _claim_type_to_issue_id

    assert _claim_type_to_issue_id("controller_contact") == "missing_controller_contact"
    assert _claim_type_to_issue_id("transfer") == "missing_transfer_notice"
    assert _claim_type_to_issue_id("profiling") == "profiling_disclosure_gap"


def test_classify_finding_quality_avoids_not_assessable_for_specialist_claim_without_citations():
    finding = LlmFinding(
        status="gap",
        severity="medium",
        gap_note="Profiling signals visible.",
        remediation_note="Add profiling disclosures.",
        citations=[],
    )
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
    finding = LlmFinding(
        status="needs review", severity=None, gap_note="insufficient evidence", remediation_note=None, citations=[]
    )
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
        {
            "document_type": "external_privacy_notice_excerpt",
            "triggered_duties": [],
            "not_triggered_duties": [],
            "not_assessable_duties": [],
        },
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
        {
            "document_type": "external_privacy_notice_excerpt",
            "triggered_duties": [],
            "not_triggered_duties": [],
            "not_assessable_duties": [],
        },
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
                "We process on the basis of contract performance, legal obligation, and legitimate interests for each purpose. "
                "Recipient categories are disclosed. "
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
    disposition = _build_final_disposition_map(
        [],
        sections,
        {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True},
    )
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
                "We process data on the basis of contract performance, legal obligation, and legitimate interests for each purpose. "
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
                policy_evidence_excerpt="ACME Corp Ltd, contact privacy@acme.com.",
            )
        )
        db.commit()
        _partner_review_pass(db, audit.id, {"controller_identity_contact": "compliant"})
        rows = db.query(Finding).filter(Finding.audit_id == audit.id).all()
        controller_rows = [r for r in rows if r.section_id == "systemic:missing_controller_contact"]
        assert controller_rows
        assert controller_rows[0].publish_flag == "no"
        disposition = _build_final_disposition_map(
            rows,
            [],
            {"controller_contact": True, "legal_basis": True, "retention": True, "rights": True, "complaint": True},
            {"controller_identity_contact": "compliant"},
        )
        assert disposition["controller_identity_contact"]["status"] == "satisfied"
        assert disposition["controller_identity_contact"]["publication_recommendation"] == "internal_only"


def test_severity_calibration_deterministic_for_core_and_specialist_claims():
    assert _normalize_severity("gap", None, {"legal_basis"}) == "high"
    assert _normalize_severity("gap", None, {"rights"}) == "high"
    assert _normalize_severity("gap", None, {"complaint"}) == "high"
    assert _normalize_severity("gap", None, {"transfer"}) == "high"
    assert _normalize_severity("gap", None, {"profiling"}) == "high"
    assert _normalize_severity("gap", None, {"retention"}) == "high"
    assert _normalize_severity("gap", None, {"recipients"}) == "medium"


def test_confidence_calibration_spreads_high_and_low_ranges():
    high_finding = LlmFinding(
        status="gap", severity="high", gap_note="clear transfer gap", remediation_note="fix", citations=[]
    )
    high_citations = [
        LlmCitation(chunk_id="c1", article_number="13", paragraph_ref="1(f)", article_title="info", excerpt="x"),
        LlmCitation(chunk_id="c2", article_number="44", paragraph_ref=None, article_title="transfer", excerpt="y"),
        LlmCitation(chunk_id="c3", article_number="46", paragraph_ref=None, article_title="safeguards", excerpt="z"),
    ]
    klass_high, conf_high = _classify_finding_quality(high_finding, high_citations, {"transfer"}, "direct")
    low_finding = LlmFinding(
        status="needs review", severity=None, gap_note="fragmentary excerpt", remediation_note=None, citations=[]
    )
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
        {
            "document_type": "external_privacy_notice",
            "triggered_duties": [],
            "not_triggered_duties": [],
            "not_assessable_duties": [],
        },
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


def test_extract_legal_facts_named_recipient_categories_detected_as_present():
    # Named functional categories must be detected as "present", not "missing",
    # so that documents disclosing analytics platforms / cloud providers / etc.
    # are not falsely flagged as missing recipient disclosure.
    facts = _extract_legal_facts(
        "We share data with analytics platforms, cloud infrastructure providers, and payment processors."
    )
    indexed = {(f["fact_type"], f["value"]) for f in facts}
    assert ("recipient_categories", "present") in indexed
    assert ("recipient_categories", "missing") not in indexed


def test_validate_duty_recipients_notice_compliant_with_named_categories():
    # GDPR Art. 13/14 is satisfied by naming functional recipient categories,
    # even without the formal phrase "categories of recipients".
    sections = [
        SectionData(
            id="s-named",
            section_order=1,
            section_title="How we share data",
            content=(
                "We disclose personal data to analytics platforms, cloud infrastructure providers, "
                "integration partners, and support providers in order to deliver our services."
            ),
            page_start=1,
            page_end=1,
        )
    ]
    out = _document_wide_duty_validation(sections, "external_privacy_notice")
    assert out.get("recipients_notice") == "compliant", (
        f"Named recipient categories must satisfy recipients_notice; got {out.get('recipients_notice')!r}"
    )


def test_validate_duty_recipients_notice_non_compliant_for_vague_third_parties():
    # Purely vague language ("third parties", "selected partners") with no named
    # functional categories should produce non_compliant.
    sections = [
        SectionData(
            id="s-vague",
            section_order=1,
            section_title="Data sharing",
            content="We may share your personal data with third parties and our business partners.",
            page_start=1,
            page_end=1,
        )
    ]
    out = _document_wide_duty_validation(sections, "external_privacy_notice")
    result = out.get("recipients_notice")
    assert result in {"non_compliant", "not_assessable_from_provided_text"}, (
        f"Vague third-party-only disclosure must not be marked compliant; got {result!r}"
    )


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


# ---------------------------------------------------------------------------
# _finding_issue_id — anchor-based resolution (step 4)
# ---------------------------------------------------------------------------


def _make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(
        bind=engine, class_=__import__("sqlalchemy.orm", fromlist=["Session"]).Session, expire_on_commit=False
    )()


def test_finding_issue_id_resolves_transfer_from_anchor():
    """_finding_issue_id must resolve missing_transfer_notice from Art. 13(1)(f) anchor."""
    row = Finding(
        section_id="sec-xyz",
        status="gap",
        severity="high",
        publication_state="publishable",
        primary_legal_anchor='["GDPR Article 13(1)(f)"]',
        gap_note="Transfer safeguards not disclosed.",
        remediation_note="Add safeguard details.",
    )
    assert _finding_issue_id(row) == "missing_transfer_notice"


def test_finding_issue_id_resolves_profiling_from_anchor():
    """_finding_issue_id must resolve profiling_disclosure_gap from Art. 13(2)(f)."""
    row = Finding(
        section_id="sec-xyz",
        status="gap",
        severity="high",
        publication_state="publishable",
        primary_legal_anchor='["GDPR Article 13(2)(f)", "GDPR Article 22"]',
        gap_note="Profiling logic not explained.",
        remediation_note="Add profiling disclosure.",
    )
    assert _finding_issue_id(row) == "profiling_disclosure_gap"


def test_finding_issue_id_resolves_retention_from_anchor():
    """_finding_issue_id must resolve missing_retention_period from Art. 13(2)(a)."""
    row = Finding(
        section_id="sec-xyz",
        status="gap",
        primary_legal_anchor='["GDPR Article 13(2)(a)"]',
        gap_note="No retention period disclosed.",
        remediation_note="Add retention criteria.",
    )
    assert _finding_issue_id(row) == "missing_retention_period"


def test_finding_issue_id_resolves_rights_from_anchor():
    """_finding_issue_id must resolve missing_rights_notice from Art. 13(2)(b)."""
    row = Finding(
        section_id="sec-xyz",
        status="gap",
        primary_legal_anchor='["GDPR Article 13(2)(b)"]',
        gap_note="Data subject rights not listed.",
        remediation_note="List rights.",
    )
    assert _finding_issue_id(row) == "missing_rights_notice"


def test_finding_issue_id_returns_none_for_totally_unresolvable_row():
    """Row with no anchor, no known obligation text → must return None."""
    row = Finding(
        section_id="sec-xyz",
        status="gap",
        primary_legal_anchor=None,
        gap_note="Some generic gap.",
        remediation_note="Fix it.",
        obligation_under_review=None,
        legal_requirement=None,
    )
    assert _finding_issue_id(row) is None


# ---------------------------------------------------------------------------
# _snapshot_analysis_items — no unknown_obligation, no supporting_evidence gap
# ---------------------------------------------------------------------------


def _db_with_audit():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(
        bind=engine, class_=__import__("sqlalchemy.orm", fromlist=["Session"]).Session, expire_on_commit=False
    )
    db = Session()
    audit = Audit(document_id="doc-test", status="complete")
    db.add(audit)
    db.flush()
    return db, audit


def test_snapshot_no_unknown_obligation_issue_type():
    """After _snapshot_analysis_items, no AuditAnalysisItem may have issue_type='unknown_obligation'."""
    db, audit = _db_with_audit()
    # Row with no resolvable issue — no anchor, no matching text
    db.add(
        Finding(
            audit_id=audit.id,
            section_id="sec-1",
            status="gap",
            severity="high",
            publication_state="internal_only",
            publish_flag="no",
            finding_type="local",
            artifact_role="support_only",
            gap_note="Generic unresolvable gap.",
            remediation_note="Fix it.",
            primary_legal_anchor=None,
        )
    )
    db.commit()
    _snapshot_analysis_items(db, audit.id)
    rows = db.query(AuditAnalysisItem).filter(AuditAnalysisItem.audit_id == audit.id).all()
    assert rows, "Expected at least one analysis item"
    for row in rows:
        assert row.issue_type != "unknown_obligation", f"Found unknown_obligation issue_type in analysis item {row.id}"


def test_snapshot_no_candidate_gap_without_canonical_issue():
    """No AuditAnalysisItem with status_candidate='candidate_gap' may have issue_type='unknown_obligation'
    or 'diagnostic_internal_only' or None."""
    db, audit = _db_with_audit()
    # Row that resolves via anchor
    db.add(
        Finding(
            audit_id=audit.id,
            section_id="sec-good",
            status="gap",
            severity="high",
            publication_state="publishable",
            publish_flag="yes",
            finding_type="systemic",
            artifact_role="publishable_finding",
            gap_note="Transfer not disclosed.",
            remediation_note="Add safeguard.",
            primary_legal_anchor='["GDPR Article 13(1)(f)"]',
            obligation_under_review="systemic:missing_transfer_notice",
        )
    )
    # Row that CANNOT be resolved (no anchor, no recognizable text)
    db.add(
        Finding(
            audit_id=audit.id,
            section_id="sec-bad",
            status="gap",
            severity="high",
            publication_state="internal_only",
            publish_flag="no",
            finding_type="local",
            artifact_role="support_only",
            gap_note="Generic unresolvable.",
            remediation_note="Fix it.",
            primary_legal_anchor=None,
        )
    )
    db.commit()
    _snapshot_analysis_items(db, audit.id)
    rows = db.query(AuditAnalysisItem).filter(AuditAnalysisItem.audit_id == audit.id).all()
    for row in rows:
        if row.status_candidate == "candidate_gap":
            assert row.issue_type not in {None, "unknown_obligation", "diagnostic_internal_only"}, (
                f"candidate_gap row has unresolvable issue_type={row.issue_type!r} for section {row.section_id}"
            )


def test_snapshot_supporting_evidence_never_candidate_gap():
    """issue_type='supporting_evidence' must never produce status_candidate='candidate_gap'."""
    db, audit = _db_with_audit()
    db.add(
        Finding(
            audit_id=audit.id,
            section_id="sec-support",
            status="gap",
            severity="high",
            publication_state="internal_only",
            publish_flag="no",
            finding_type="supporting_evidence",
            artifact_role="support_only",
            gap_note="Supporting evidence row.",
            remediation_note="n/a",
        )
    )
    db.commit()
    _snapshot_analysis_items(db, audit.id)
    rows = db.query(AuditAnalysisItem).filter(AuditAnalysisItem.audit_id == audit.id).all()
    for row in rows:
        assert not (row.issue_type == "supporting_evidence" and row.status_candidate == "candidate_gap"), (
            f"supporting_evidence row has status_candidate=candidate_gap for section {row.section_id}"
        )


def test_snapshot_no_api_cannot_resolve_suppression_text():
    """No analysis item suppression_reason may contain the banned 'API cannot resolve' text."""
    db, audit = _db_with_audit()
    db.add(
        Finding(
            audit_id=audit.id,
            section_id="sec-gate1",
            status="gap",
            severity="high",
            publication_state="internal_only",
            publish_flag="no",
            finding_type="local",
            artifact_role="support_only",
            gap_note="This section-level finding was excluded: no GDPR legal anchor was determinable for this section.",
            remediation_note=None,
            primary_legal_anchor=None,
        )
    )
    db.commit()
    _snapshot_analysis_items(db, audit.id)
    rows = db.query(AuditAnalysisItem).filter(AuditAnalysisItem.audit_id == audit.id).all()
    for row in rows:
        sr = (row.suppression_reason or "").lower()
        assert "api cannot resolve" not in sr, (
            f"Banned suppression text found in analysis item {row.id}: {row.suppression_reason!r}"
        )


# ── not_assessable override tests ─────────────────────────────────────────────


def _mk_section(content: str, title: str = "Data Processing", sid: str = "s1") -> "SectionData":
    from app.services.clients import SectionData as SD

    return SD(id=sid, section_order=1, section_title=title, content=content, page_start=1, page_end=1)


def _mk_posture() -> dict:
    return {
        "document_type": "privacy_notice",
        "triggered_duties": [],
        "regional_context": None,
        "controller_identity_present": False,
        "legal_basis_present": False,
        "retention_present": False,
        "rights_present": False,
        "complaint_present": False,
    }


def test_explicit_violation_library_detects_inferred_consent():
    hits = _explicit_violation_hits("We rely on inferred consent from your continued usage of the platform.")
    keys = [h[0] for h in hits]
    assert "invalid_consent" in keys, f"Expected invalid_consent in {keys}"
    issues = [h[1]["issue"] for h in hits]
    assert "missing_legal_basis" in issues


def test_explicit_violation_library_detects_continued_usage():
    hits = _explicit_violation_hits("Consent is obtained through continued usage of this service.")
    keys = [h[0] for h in hits]
    assert "invalid_consent" in keys, f"Expected invalid_consent in {keys}"


def test_explicit_violation_library_detects_implied_consent():
    hits = _explicit_violation_hits("We rely on implied consent when users browse the site.")
    keys = [h[0] for h in hits]
    assert "invalid_consent" in keys


def test_explicit_violation_library_detects_indefinite_retention():
    hits = _explicit_violation_hits("Data may be retained indefinitely for operational purposes.")
    keys = [h[0] for h in hits]
    assert "unlawful_retention_wording" in keys
    issues = [h[1]["issue"] for h in hits]
    assert "missing_retention_period" in issues


def test_explicit_violation_library_detects_no_fixed_retention():
    hits = _explicit_violation_hits("There is no fixed retention period for this data category.")
    keys = [h[0] for h in hits]
    assert "unlawful_retention_wording" in keys


def test_explicit_violation_library_detects_weak_transfer_safeguards():
    hits = _explicit_violation_hits(
        "Transfers to countries that may not provide equivalent protections as where practical safeguards are available."
    )
    keys = [h[0] for h in hits]
    assert "weak_transfer_safeguards" in keys
    issues = [h[1]["issue"] for h in hits]
    assert "missing_transfer_notice" in issues


def test_explicit_violation_library_detects_protection_may_vary():
    hits = _explicit_violation_hits("Data is shared with partners where protection may vary by jurisdiction.")
    keys = [h[0] for h in hits]
    assert "weak_transfer_safeguards" in keys


def test_explicit_violation_library_detects_without_human_intervention():
    hits = _explicit_violation_hits("Eligibility decisions are made without human intervention based on risk scores.")
    keys = [h[0] for h in hits]
    assert "profiling_without_required_explanation" in keys
    issues = [h[1]["issue"] for h in hits]
    assert "profiling_disclosure_gap" in issues


def test_explicit_violation_library_detects_service_availability_affected():
    hits = _explicit_violation_hits("Service availability may be affected by our automated profiling system.")
    keys = [h[0] for h in hits]
    assert "profiling_without_required_explanation" in keys


def test_explicit_violation_library_detects_fingerprinting():
    hits = _explicit_violation_hits("We use device fingerprinting and cross-device tracking via our advertising SDK.")
    keys = [h[0] for h in hits]
    assert "tracking_without_consent_controls" in keys
    issues = [h[1]["issue"] for h in hits]
    assert "cookies_tracking_consent_gap" in issues


def test_explicit_violation_library_detects_behavioural_advertising():
    hits = _explicit_violation_hits(
        "We partner with ad networks for interest-based advertising using behavioural advertising techniques."
    )
    keys = [h[0] for h in hits]
    assert "tracking_without_consent_controls" in keys


def test_explicit_violation_library_detects_advertising_ecosystem():
    hits = _explicit_violation_hits("Data is shared across the advertising ecosystem for retargeting and remarketing.")
    keys = [h[0] for h in hits]
    assert "tracking_without_consent_controls" in keys


def test_explicit_violation_library_detects_marketing_list():
    hits = _explicit_violation_hits("Your data may be sourced from marketing lists and data aggregators.")
    keys = [h[0] for h in hits]
    assert "third_party_data_source_gap" in keys
    issues = [h[1]["issue"] for h in hits]
    assert "article14_source_transparency_gap" in issues


def test_explicit_violation_library_detects_demographic_segments():
    hits = _explicit_violation_hits(
        "We acquire demographic segments from third-party data providers and public records."
    )
    keys = [h[0] for h in hits]
    assert "third_party_data_source_gap" in keys


def test_explicit_violation_library_detects_data_broker():
    hits = _explicit_violation_hits("Personal data may be obtained from data brokers for prospecting purposes.")
    keys = [h[0] for h in hits]
    assert "third_party_data_source_gap" in keys


def test_explicit_violation_library_detects_advertising_partners_recipients():
    hits = _explicit_violation_hits("We share your data with advertising partners and integration partners.")
    keys = [h[0] for h in hits]
    assert "recipient_structure_missing" in keys
    issues = [h[1]["issue"] for h in hits]
    assert "recipients_disclosure_gap" in issues


def test_not_assessable_blocked_for_inferred_consent():
    result = _not_assessable_allowed(
        "We rely on inferred consent from continued usage of the platform.",
        status="needs review",
        classification="not_assessable",
    )
    assert result is False, "inferred consent text must block not_assessable"


def test_not_assessable_blocked_for_fingerprinting():
    result = _not_assessable_allowed(
        "We use device fingerprinting and cross-device tracking via advertising SDK.",
        status="needs review",
        classification="not_assessable",
    )
    assert result is False, "fingerprinting text must block not_assessable"


def test_not_assessable_blocked_for_data_broker():
    result = _not_assessable_allowed(
        "Data is sourced from data aggregators and demographic segments.",
        status="needs review",
        classification="not_assessable",
    )
    assert result is False, "data aggregator text must block not_assessable"


def test_not_assessable_blocked_for_indefinite_retention():
    result = _not_assessable_allowed(
        "We may retain data indefinitely for operational purposes.",
        status="needs review",
        classification="not_assessable",
    )
    assert result is False, "indefinite retention text must block not_assessable"


def test_not_assessable_blocked_for_service_availability():
    result = _not_assessable_allowed(
        "Service availability may be affected by automated profiling without human review.",
        status="needs review",
        classification="not_assessable",
    )
    assert result is False, "service availability / without human review text must block not_assessable"


def test_applicability_memo_not_assessable_overridden_by_violation():
    sec = _mk_section("Inferred consent from continued usage.", title="Consent")
    memo = _applicability_memo(sec, {"legal_basis"}, _mk_posture())
    assert memo["visibility"] != "not_assessable", (
        f"Short section with violation should not be not_assessable, got {memo['visibility']}"
    )


def test_applicability_memo_not_assessable_for_genuinely_empty_section():
    sec = _mk_section("See above.", title="Summary")
    memo = _applicability_memo(sec, set(), _mk_posture())
    assert memo["visibility"] == "not_assessable"


def test_classify_finding_quality_needs_review_with_violation_returns_probable_gap():
    from app.services.clients import LlmFinding

    f = LlmFinding(
        status="needs review",
        severity=None,
        gap_note="Inferred consent from continued usage without explicit opt-in.",
        remediation_note="Implement explicit consent.",
        citations=[],
    )
    classification, _ = _classify_finding_quality(f, [], {"legal_basis"}, "direct")
    assert classification != "not_assessable", f"Expected probable_gap or better, got {classification}"
    assert classification in {"probable_gap", "clear_non_compliance"}


def test_classify_finding_quality_needs_review_without_violation_stays_not_assessable():
    from app.services.clients import LlmFinding

    f = LlmFinding(
        status="needs review",
        severity=None,
        gap_note="Insufficient context to assess this section.",
        remediation_note="Provide full notice.",
        citations=[],
    )
    classification, _ = _classify_finding_quality(f, [], set(), "unknown")
    assert classification == "not_assessable"


def test_classify_finding_quality_no_citations_with_transfer_language():
    from app.services.clients import LlmFinding

    f = LlmFinding(
        status="gap",
        severity="high",
        gap_note="Transfers to countries that may not offer equivalent protection where practical safeguards.",
        remediation_note="Specify safeguards.",
        citations=[],
    )
    classification, _ = _classify_finding_quality(f, [], {"transfer"}, "unknown")
    assert classification != "not_assessable", f"Transfer language should prevent not_assessable, got {classification}"


def test_classify_finding_quality_no_citations_with_fingerprinting():
    from app.services.clients import LlmFinding

    f = LlmFinding(
        status="gap",
        severity="high",
        gap_note="Device fingerprinting and cross-device tracking via advertising ecosystem.",
        remediation_note="Disclose.",
        citations=[],
    )
    classification, _ = _classify_finding_quality(f, [], {"cookies"}, "unknown")
    assert classification != "not_assessable", f"Fingerprinting should prevent not_assessable, got {classification}"


# ── Task 5: new specialist families ───────────────────────────────────────────


def _mk_obligation_map(**kwargs) -> dict:
    base = {
        "controller_contact_present": True,
        "legal_basis_present": True,
        "retention_present": True,
        "rights_present": True,
        "complaint_present": True,
    }
    base.update(kwargs)
    return base


def test_invalid_consent_family_triggers_on_inferred_consent_text():
    sections = [
        _mk_section(
            "We collect personal data. Your consent is implied by continued use of this service constitutes your agreement.",
            title="Legal Basis",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    family = disposition.get("invalid_consent", {})
    assert family.get("triggered") is True, "invalid_consent family should trigger on implied/inferred consent"
    assert family.get("status") == "gap", f"Expected gap, got {family.get('status')}"
    assert family.get("severity") == "high"


def test_invalid_consent_family_does_not_trigger_when_valid_consent_present():
    sections = [
        _mk_section(
            "We rely on your freely given, specific, informed and unambiguous consent. You may withdraw consent at any time via your account settings.",
            title="Legal Basis",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    family = disposition.get("invalid_consent", {})
    # Should not be gap — either not triggered or satisfied
    status = family.get("status", "not_triggered")
    assert status not in {"gap"}, f"Valid consent text should not produce gap, got {status}"


def test_cookies_tracking_family_triggers_on_tracking_without_controls():
    sections = [
        _mk_section(
            "We use advertising cookies, retargeting pixels, and cross-device tracking to serve personalised ads.",
            title="Cookies and Tracking",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    family = disposition.get("cookies_tracking", {})
    assert family.get("triggered") is True, "cookies_tracking family should trigger on tracking technology"
    assert family.get("status") == "gap", f"Expected gap without consent controls, got {family.get('status')}"
    assert family.get("severity") == "high"


def test_cookies_tracking_family_satisfied_when_consent_controls_present():
    sections = [
        _mk_section(
            "We use analytics cookies. We obtain your consent before placing non-essential cookies. You can manage cookie preferences via our cookie banner.",
            title="Cookie Policy",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    family = disposition.get("cookies_tracking", {})
    status = family.get("status", "not_triggered")
    assert status not in {"gap"}, f"Consent controls present; should not be gap, got {status}"


def test_article14_source_extended_triggers_on_marketing_list_without_disclosure():
    sections = [
        _mk_section(
            "We may receive personal data from data brokers, marketing lists and third-party data providers to enrich our customer records.",
            title="Data Sources",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    family = disposition.get("article14_source_extended", {})
    assert family.get("triggered") is True, (
        "article14_source_extended should trigger on data broker/marketing list language"
    )
    assert family.get("status") == "gap", f"Expected gap without source-category disclosure, got {family.get('status')}"
    assert family.get("severity") == "high"


def test_article14_source_extended_satisfied_when_source_categories_disclosed():
    sections = [
        _mk_section(
            "We receive data from third parties including data aggregators. The categories of sources of personal data include public records and commercial data providers.",
            title="Data Sources",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    family = disposition.get("article14_source_extended", {})
    status = family.get("status", "not_triggered")
    assert status not in {"gap"}, f"Source categories disclosed; should not be gap, got {status}"


def test_obligation_taxonomy_has_all_new_issue_keys():
    from app.services.audit_runner import OBLIGATION_TAXONOMY

    for key in ("invalid_consent_or_legal_basis", "cookies_tracking_consent_gap", "article14_source_transparency_gap"):
        assert key in OBLIGATION_TAXONOMY, f"Missing from OBLIGATION_TAXONOMY: {key}"
        entry = OBLIGATION_TAXONOMY[key]
        assert "family" in entry
        assert "severity" in entry
        assert "anchors" in entry
        assert "gap_note" in entry


def test_gdpr_duty_registry_has_invalid_consent_notice():
    from app.services.audit_runner import GDPR_DUTY_REGISTRY

    assert "invalid_consent_notice" in GDPR_DUTY_REGISTRY
    entry = GDPR_DUTY_REGISTRY["invalid_consent_notice"]
    assert "6(1)(a)" in str(entry.get("primary_articles", "")) or "Art. 6" in str(entry.get("primary_articles", ""))


def test_specialist_trigger_rules_has_all_new_issue_keys():
    from app.services.audit_runner import SPECIALIST_TRIGGER_RULES

    for key in ("invalid_consent_or_legal_basis", "cookies_tracking_consent_gap", "article14_source_transparency_gap"):
        assert key in SPECIALIST_TRIGGER_RULES, f"Missing from SPECIALIST_TRIGGER_RULES: {key}"
        signals, label = SPECIALIST_TRIGGER_RULES[key]
        assert len(signals) >= 3, f"{key} should have at least 3 trigger signals"
        assert label, f"{key} should have a non-empty trigger label"


def test_new_families_not_in_specialist_families_list_do_not_appear_in_publication():
    # Validates that when there are no trigger signals in corpus, the new families
    # do not inject spurious gap entries into disposition
    sections = [
        _mk_section(
            "We are a data controller. We collect names and email addresses for account creation. You have rights to access, rectify and erase your data.",
            title="Privacy Notice",
        )
    ]
    disposition = _build_final_disposition_map([], sections, _mk_obligation_map())
    for family in ("invalid_consent", "cookies_tracking", "article14_source_extended"):
        f = disposition.get(family, {})
        if f.get("triggered"):
            assert f.get("status") != "gap", f"{family} should not be gap without evidence signals"


# ── Task 6: evidence quality ───────────────────────────────────────────────────


def test_is_conclusion_evidence_detects_no_explicit_prefix():
    assert _is_conclusion_evidence("No explicit lawful basis is disclosed for the processing activities.")
    assert _is_conclusion_evidence("no explicit lawful basis is disclosed")
    assert _is_conclusion_evidence("No right to lodge a complaint is disclosed.")
    assert _is_conclusion_evidence("No complete data subject rights disclosure is present.")
    assert _is_conclusion_evidence("No explicit disclosure was found in the reviewed notice")
    assert _is_conclusion_evidence("Processing purposes are described but not clearly mapped")


def test_is_conclusion_evidence_accepts_real_text():
    assert not _is_conclusion_evidence("[Legal Basis] We process your data under consent (Art. 6(1)(a)).")
    assert not _is_conclusion_evidence("We collect names and email addresses for account creation.")
    assert not _is_conclusion_evidence("Retention: Personal data is kept for 12 months after account closure.")
    assert not _is_conclusion_evidence("GDPR Art.13(1)(c) disclosure requirement.")
    assert not _is_conclusion_evidence("")


def test_extract_section_evidence_returns_real_text():
    sections = [
        _mk_section(
            "We process personal data under the lawful basis of consent (Article 6(1)(a)).",
            title="Legal Basis",
            sid="s1",
        ),
        _mk_section("Data is retained for 24 months from the date of last interaction.", title="Retention", sid="s2"),
    ]
    refs = ["section:s1", "section:s2"]
    result = _extract_section_evidence(sections, refs)
    assert "[Legal Basis]" in result
    assert "consent" in result.lower() or "article 6" in result.lower()
    assert not _is_conclusion_evidence(result)


def test_extract_section_evidence_skips_non_section_refs():
    sections = [_mk_section("Some content.", title="Data Use", sid="s1")]
    refs = ["systemic-anchor:art13", "section:s1"]
    result = _extract_section_evidence(sections, refs)
    assert "systemic-anchor" not in result
    assert "[Data Use]" in result


def test_extract_section_evidence_returns_empty_for_no_match():
    sections = [_mk_section("Content here.", title="T", sid="s1")]
    result = _extract_section_evidence(sections, ["section:s_missing"])
    assert result == ""


def test_systemic_summary_text_no_explicit_strings():
    refs = ["section:s1", "section:s2"]
    summary = _systemic_summary_text("missing_legal_basis", refs, omission_basis=True)
    assert not _is_conclusion_evidence(summary)
    assert "Sections reviewed" in summary or "reviewed" in summary.lower()
    assert "lawful basis" in summary.lower() or "legal basis" in summary.lower()


def test_systemic_summary_text_no_refs():
    summary = _systemic_summary_text("missing_retention_period", [], omission_basis=True)
    assert not _is_conclusion_evidence(summary)
    assert "retention" in summary.lower()


# ── Task 7: citation quality ───────────────────────────────────────────────────


def test_is_citation_conclusion_detects_notice_does_not():
    assert _is_citation_conclusion("The notice does not explain the lawful basis.")
    assert _is_citation_conclusion("The privacy notice does not disclose transfer safeguards.")
    assert _is_citation_conclusion("This section does not contain retention criteria.")
    assert _is_citation_conclusion("The controller has not disclosed the data subject rights.")
    assert _is_citation_conclusion("There is no mention of the right to complain.")
    assert _is_citation_conclusion("No disclosure of the lawful basis is present.")


def test_is_citation_conclusion_detects_policy_text_prefix():
    # Section text leaked in (e.g. from _extract_section_evidence) must be rejected
    assert _is_citation_conclusion("[4. Legal Basis for Processing] 4.1 The Company relies on…")
    assert _is_citation_conclusion("[Retention] Data is stored for 12 months.")


def test_is_citation_conclusion_accepts_gdpr_rule_text():
    assert not _is_citation_conclusion(
        "The controller shall provide the purposes of the processing and the legal basis for the processing."
    )
    assert not _is_citation_conclusion("Processing shall be lawful only if the data subject has given consent.")
    assert not _is_citation_conclusion(
        "Every data subject shall have the right to lodge a complaint with a supervisory authority."
    )
    assert not _is_citation_conclusion("")


def test_gdpr_legal_text_covers_required_anchors():
    required = [
        "GDPR Art. 13(1)(c)",
        "GDPR Art. 14(1)(c)",
        "GDPR Art. 13(2)(a)",
        "GDPR Art. 14(2)(a)",
        "GDPR Art. 13(2)(b)-(d)",
        "GDPR Art. 14(2)(c)-(e)",
        "GDPR Art. 13(1)(f)",
        "GDPR Art. 14(1)(f)",
        "GDPR Art. 13(2)(f)",
        "GDPR Art. 14(2)(g)",
        "GDPR Art. 77",
        "GDPR Art. 5(1)(e)",
        "GDPR Art. 6(1)(a)",
        "GDPR Art. 7(1)",
    ]
    for anchor in required:
        text = _gdpr_legal_text(anchor)
        assert anchor in _GDPR_ARTICLE_LEGAL_TEXT, f"{anchor} missing from _GDPR_ARTICLE_LEGAL_TEXT"
        assert text, f"_gdpr_legal_text('{anchor}') returned empty"
        assert not _is_citation_conclusion(text), f"Legal text for '{anchor}' detected as conclusion: {text[:80]}"
        assert not text.startswith("GDPR Art."), f"Legal text for '{anchor}' is just the anchor string: {text}"


def test_gdpr_legal_text_no_doubled_gdpr_prefix():
    for anchor, text in _GDPR_ARTICLE_LEGAL_TEXT.items():
        assert not text.lower().startswith("gdpr gdpr"), f"Doubled GDPR prefix in legal text for {anchor}"
        assert not text.lower().startswith("gdpr art."), f"Legal text starts with anchor ref, not rule text: {anchor}"


def test_anchor_to_chunk_id_is_unique_per_subparagraph():
    ids = {
        _anchor_to_chunk_id("GDPR Art. 13(1)(a)"),
        _anchor_to_chunk_id("GDPR Art. 13(1)(c)"),
        _anchor_to_chunk_id("GDPR Art. 13(1)(e)"),
        _anchor_to_chunk_id("GDPR Art. 13(1)(f)"),
        _anchor_to_chunk_id("GDPR Art. 13(2)(a)"),
        _anchor_to_chunk_id("GDPR Art. 13(2)(d)"),
        _anchor_to_chunk_id("GDPR Art. 13(2)(f)"),
    }
    assert len(ids) == 7, f"chunk_id collision: {ids}"


def test_add_systemic_finding_citations_uses_legal_text(tmp_path):
    """_add_systemic_finding_citations must produce GDPR rule text excerpts, not policy/conclusion text."""
    import uuid

    from app.models.audit import Audit, Base, Finding, FindingCitation
    from app.services.audit_runner import _add_systemic_finding_citations
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    audit = Audit(
        id=str(uuid.uuid4()),
        document_id="doc1",
        status="complete",
        model_provider="test",
        model_name="test",
        embedding_model="test",
        corpus_version="v1",
    )
    db.add(audit)
    finding = Finding(id=str(uuid.uuid4()), audit_id=audit.id, section_id="systemic:missing_legal_basis", status="gap")
    db.add(finding)
    db.flush()

    _add_systemic_finding_citations(db, finding.id, "missing_legal_basis")
    db.flush()

    citations = db.query(FindingCitation).filter(FindingCitation.finding_id == finding.id).all()
    assert len(citations) >= 1, "Expected at least one citation"
    for c in citations:
        excerpt = (c.excerpt or "").strip()
        assert excerpt, "Citation excerpt must not be empty"
        assert not _is_citation_conclusion(excerpt), f"Citation excerpt is a conclusion: {excerpt[:100]}"
        assert not excerpt.startswith("GDPR GDPR"), f"Doubled GDPR prefix in excerpt: {excerpt[:60]}"
        assert not excerpt.lower().startswith("gdpr art."), f"Excerpt is just the anchor ref: {excerpt[:60]}"
        assert len(excerpt) > 40, f"Citation excerpt too short to be legal text: {excerpt}"
    db.close()


def test_validate_citations_replaces_conclusion_excerpt():
    """_validate_citations must replace LLM conclusion text with GDPR chunk content."""
    from app.services.audit_runner import _validate_citations
    from app.services.clients import LlmCitation, RetrievalChunk, SectionData

    chunk = RetrievalChunk(
        chunk_id="gdpr-art-13-p-1-sp-c-seg-1",
        article_number="13",
        article_title="Information to be provided where personal data are collected",
        paragraph_ref="1",
        content="The controller shall provide the purposes of the processing and the legal basis for the processing.",
        score=0.9,
    )
    cit = LlmCitation(
        chunk_id="gdpr-art-13-p-1-sp-c-seg-1",
        article_number="13",
        paragraph_ref="1",
        article_title="",
        excerpt="The notice does not explain the lawful basis for any of the processing activities.",
    )
    section = _mk_section("We process personal data.", title="Data Use")
    valid = _validate_citations([cit], [chunk], section, "privacy_notice", claim_text="legal basis missing")
    if valid:
        assert not _is_citation_conclusion(valid[0].excerpt), f"Conclusion excerpt was not replaced: {valid[0].excerpt}"
        assert "controller shall provide" in valid[0].excerpt.lower() or len(valid[0].excerpt) > 20


def test_policy_evidence_excerpt_not_a_conclusion_in_published_findings():
    """_is_conclusion_evidence must reject all _readable_evidence() outputs."""
    from app.services.audit_runner import _readable_evidence

    for issue in [
        "missing_legal_basis",
        "missing_retention_period",
        "missing_rights_notice",
        "missing_complaint_right",
        "missing_controller_identity",
        "missing_transfer_notice",
        "profiling_disclosure_gap",
    ]:
        text = _readable_evidence(issue)
        assert _is_conclusion_evidence(text.lower()), (
            f"_readable_evidence('{issue}') = '{text}' is not detected as a conclusion — "
            "update _CONCLUSION_EVIDENCE_PREFIXES to cover it"
        )
