from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.audit_runner import (
    _applicability_memo,
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
    _finding_signature,
    _ensure_reasoning_chain,
    _clean_remediation_legal_mismatches,
    _classify_finding_quality,
    _validate_citations,
)
from app.services.clients import LlmCitation, LlmFinding, RetrievalChunk, SectionData


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


def test_substantive_finding_without_citations_is_downgraded():
    finding = LlmFinding(
        status="partial",
        severity="high",
        gap_note="Missing legal basis",
        remediation_note="Add legal basis",
        citations=[],
    )
    gated = _enforce_substantive_citation_gate(finding, valid_citations=[])
    assert gated.status == "needs review"
    assert gated.severity is None


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


def test_normalize_severity_escalates_key_transparency_claims():
    assert _normalize_severity("gap", "medium", {"retention"}) == "high"
    assert _normalize_severity("partial", None, {"rights"}) == "high"
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
    assert "Evidence:" in (updated.gap_note or "")
    assert "Requirement:" in (updated.gap_note or "")
    assert "Assessment:" in (updated.gap_note or "")


def test_clean_remediation_rewrites_wrong_13_1_f_legal_basis_reference():
    remediation = "Cite Article 13(1)(f) as the legal basis for this disclosure."
    cleaned = _clean_remediation_legal_mismatches(remediation, {"legal_basis"})
    assert "Article 6(1)" in (cleaned or "")


def test_classify_finding_quality_outputs_not_assessable_without_citations():
    finding = LlmFinding(status="gap", severity="high", gap_note="Missing retention.", remediation_note="Add retention.", citations=[])
    klass, conf = _classify_finding_quality(finding, [], {"retention"}, "direct")
    assert klass == "not_assessable"
    assert conf is not None and conf < 0.5


def test_classify_finding_quality_marks_needs_review_as_not_assessable():
    finding = LlmFinding(status="needs review", severity=None, gap_note="insufficient evidence", remediation_note=None, citations=[])
    klass, conf = _classify_finding_quality(finding, [], {"retention"}, "unknown")
    assert klass == "not_assessable"
    assert conf == 0.2


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
