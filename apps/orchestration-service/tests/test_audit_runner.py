from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.audit_runner import (
    _enforce_substantive_citation_gate,
    _evidence_sufficient,
    _is_not_applicable,
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
