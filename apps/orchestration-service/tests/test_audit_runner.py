from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.audit_runner import (
    _article_int,
    _enforce_substantive_citation_gate,
    _evidence_sufficient,
    _is_legally_relevant_citation,
    _is_not_applicable,
    _paragraph_ref_compatible,
    _rerank_chunks_for_mode,
    _retry_needed,
    _runtime_budget_exceeded,
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
