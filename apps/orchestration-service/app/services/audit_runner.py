from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Iterable

from prometheus_client import Counter, Histogram
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import Audit, Finding, FindingCitation
from app.services.clients import IngestionClient, KnowledgeClient, LlmCitation, LlmFinding, RetrievalChunk, SectionData
from app.services.llm import run_llm_classification


retrieval_retry_total = Counter("retrieval_retry_total", "Retries triggered by frozen threshold")
evidence_gate_failure_total = Counter("evidence_gate_failure_total", "Sections failing evidence gate")
citation_validation_failure_total = Counter("citation_validation_failure_total", "Rejected citations")
llm_inference_latency_seconds = Histogram("llm_inference_latency_seconds", "LLM inference latency")


ADMIN_PATTERNS = {
    "scope",
    "purpose of this document",
    "definitions",
    "terms",
    "introduction",
    "overview",
    "document control",
    "version history",
    "amendment history",
    "references",
    "contact us",
    "contacts",
}

PROCESSING_SIGNALS = {
    "personal data",
    "data subject",
    "process",
    "collect",
    "store",
    "retain",
    "share",
    "transfer",
    "consent",
    "sensitive data",
    "recipient",
    "controller",
    "processor",
}

OBLIGATION_WORDS = {"shall", "must", "required", "obligation", "necessary", "appropriate"}

DOCUMENT_MODE_HINTS: dict[str, set[str]] = {
    "privacy_notice": {
        "privacy notice",
        "privacy policy",
        "data subject rights",
        "legal basis",
        "recipients",
        "international transfers",
    },
    "internal_policy": {
        "policy purpose",
        "roles and responsibilities",
        "incident response",
        "security controls",
        "retention schedule",
    },
}

MODE_ARTICLE_HINTS: dict[str, str] = {
    "privacy_notice": "prioritize GDPR Articles 12, 13, 14, and Article 5 principles",
    "internal_policy": "prioritize GDPR Articles 5, 24, 25, 30, 32 and accountability obligations",
}

PRIVACY_NOTICE_PREFERRED_ARTICLES = {5, 6, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 44, 45, 46, 47, 49}
PRIVACY_NOTICE_DISCOURAGED_ARTICLES = {30, 88}
INTERNAL_POLICY_PREFERRED_ARTICLES = {5, 24, 25, 30, 32, 35}

EMPLOYMENT_SIGNALS = {"employee", "employment", "worker", "staff", "hr", "human resources"}
ROPA_SIGNALS = {"record of processing", "ropa", "processing register", "register of processing"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _is_not_applicable(section: SectionData) -> bool:
    title = re.sub(r"[^a-z0-9\s]", "", _norm(section.section_title))
    if title not in ADMIN_PATTERNS:
        return False
    content = _norm(section.content)
    return not any(k in content for k in PROCESSING_SIGNALS)


def _infer_topic(section: SectionData) -> str:
    title = _norm(section.section_title)
    content = _norm(section.content)[:1200]
    if "retention" in title or "retain" in content:
        return "data retention storage limitation"
    if "rights" in title or "data subject" in content:
        return "data subject rights access rectification erasure"
    if "transfer" in title or "international" in title:
        return "international transfer safeguards"
    if "security" in title or "incident" in title:
        return "security of processing technical organizational measures"
    if "consent" in title or "lawful" in title:
        return "lawful basis consent processing"
    return section.section_title


def _infer_document_mode(sections: list[SectionData]) -> str:
    scores = {mode: 0 for mode in DOCUMENT_MODE_HINTS}
    for section in sections:
        haystack = _norm(f"{section.section_title} {section.content[:500]}")
        for mode, hints in DOCUMENT_MODE_HINTS.items():
            scores[mode] += sum(1 for hint in hints if hint in haystack)
    best_mode = max(scores, key=scores.get)
    if scores[best_mode] == 0:
        return "internal_policy"
    return best_mode


def _build_retrieval_query(section: SectionData, topic: str, document_mode: str) -> str:
    article_hint = MODE_ARTICLE_HINTS.get(document_mode, "prioritize directly applicable GDPR obligations")
    snippet = section.content[:700]
    return f"GDPR obligations for {topic}. Context: {article_hint}. Section text: {snippet}"


def _article_int(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    return int(m.group(0))


def _contains_any(text: str, signals: Iterable[str]) -> bool:
    return any(signal in text for signal in signals)


def _section_context_signals(section: SectionData) -> str:
    return _norm(f"{section.section_title} {section.content[:1200]}")


def _preferred_articles_for_section(section: SectionData, document_mode: str) -> set[int]:
    topic = _norm(_infer_topic(section))
    if document_mode == "privacy_notice":
        preferred = set(PRIVACY_NOTICE_PREFERRED_ARTICLES)
        if "transfer" in topic or "international" in topic:
            preferred |= {13, 14, 44, 45, 46, 47, 49}
        if "rights" in topic or "data subject" in topic:
            preferred |= {12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}
        if "retention" in topic:
            preferred |= {5, 13, 14}
        return preferred
    return set(INTERNAL_POLICY_PREFERRED_ARTICLES)


def _rerank_chunks_for_mode(section: SectionData, chunks: list[RetrievalChunk], document_mode: str) -> list[RetrievalChunk]:
    if not chunks:
        return chunks
    section_ctx = _section_context_signals(section)
    preferred = _preferred_articles_for_section(section, document_mode)
    allows_employment = _contains_any(section_ctx, EMPLOYMENT_SIGNALS)
    allows_ropa = _contains_any(section_ctx, ROPA_SIGNALS)

    scored: list[tuple[float, RetrievalChunk]] = []
    for ch in chunks:
        article = _article_int(ch.article_number)
        adjusted = ch.score
        if article in preferred:
            adjusted += 0.12
        if document_mode == "privacy_notice":
            if article == 88 and not allows_employment:
                adjusted -= 0.20
            if article == 30 and not allows_ropa:
                adjusted -= 0.15
            if article in PRIVACY_NOTICE_DISCOURAGED_ARTICLES:
                adjusted -= 0.05
        scored.append((adjusted, ch))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [ch for _score, ch in scored]


def _topic_keywords(topic: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", _norm(topic)) if len(w) > 3}


def _retry_needed(chunks: list[RetrievalChunk], topic: str) -> bool:
    if not chunks:
        return True
    top1 = chunks[0].score
    keys = _topic_keywords(topic)
    overlap_hits = 0
    for ch in chunks[:5]:
        txt = _norm(ch.content)
        if any(k in txt for k in keys):
            overlap_hits += 1
    return top1 < 0.45 or overlap_hits < 2


def _evidence_sufficient(chunks: list[RetrievalChunk]) -> bool:
    strong = [c for c in chunks[:5] if c.score >= 0.50]
    if len(strong) < 2:
        return False
    for c in chunks[:5]:
        txt = _norm(c.content)
        if any(k in txt for k in OBLIGATION_WORDS):
            return True
    return False


def _paragraph_ref_compatible(citation_ref: str | None, chunk_ref: str | None) -> bool:
    if not citation_ref or not chunk_ref:
        return True
    a = _norm(citation_ref)
    b = _norm(chunk_ref)
    return a == b or a in b or b in a


def _is_legally_relevant_citation(citation: LlmCitation, section: SectionData, document_mode: str) -> bool:
    article = _article_int(citation.article_number)
    if article is None:
        return False
    section_ctx = _section_context_signals(section)
    if document_mode == "privacy_notice":
        if article == 88 and not _contains_any(section_ctx, EMPLOYMENT_SIGNALS):
            return False
        if article == 30 and not _contains_any(section_ctx, ROPA_SIGNALS):
            return False
    preferred = _preferred_articles_for_section(section, document_mode)
    if article in preferred:
        return True
    if document_mode == "internal_policy":
        return True
    return article in {1, 2, 3, 4}


def _validate_citations(citations: list[LlmCitation], retrieved: list[RetrievalChunk], section: SectionData, document_mode: str) -> list[LlmCitation]:
    by_chunk = {c.chunk_id: c for c in retrieved}
    valid: list[LlmCitation] = []
    for cit in citations:
        chunk = by_chunk.get(cit.chunk_id)
        if not chunk:
            citation_validation_failure_total.inc()
            continue
        if str(cit.article_number).strip() != str(chunk.article_number).strip():
            citation_validation_failure_total.inc()
            continue
        if not _paragraph_ref_compatible(cit.paragraph_ref, chunk.paragraph_ref):
            citation_validation_failure_total.inc()
            continue
        if not cit.chunk_id:
            citation_validation_failure_total.inc()
            continue
        if not _is_legally_relevant_citation(cit, section, document_mode):
            citation_validation_failure_total.inc()
            continue

        if not cit.excerpt:
            cit.excerpt = chunk.content[:180]
        if not cit.article_title:
            cit.article_title = chunk.article_title
        valid.append(cit)

    return valid


def _coerce_finding(f: LlmFinding | None) -> LlmFinding:
    if f is None:
        return LlmFinding(status="needs review", severity=None, gap_note="LLM parse failure", remediation_note=None, citations=[])

    if f.status in {"gap", "partial"}:
        if not f.severity:
            f.severity = "medium"
        if not f.gap_note:
            f.gap_note = "Insufficient policy coverage against retrieved GDPR obligations."
        if not f.remediation_note:
            f.remediation_note = "Add explicit policy language to address the cited GDPR obligations."
    else:
        f.severity = None
        if f.status in {"compliant", "needs review"}:
            if f.status != "needs review":
                f.gap_note = None
                f.remediation_note = None
    return f


def _enforce_substantive_citation_gate(f: LlmFinding, valid_citations: list[LlmCitation]) -> LlmFinding:
    if f.status in {"gap", "partial"} and not valid_citations:
        return LlmFinding(
            status="needs review",
            severity=None,
            gap_note="Substantive finding rejected: no validated GDPR citation evidence.",
            remediation_note=None,
            citations=[],
        )
    return f


def _runtime_budget_exceeded(started_monotonic: float, now_monotonic: float, budget_seconds: int) -> bool:
    return (now_monotonic - started_monotonic) > budget_seconds


def _effective_llm_budget(section_count: int, configured_cap: int) -> int:
    if section_count <= 0:
        return configured_cap
    if section_count <= configured_cap:
        return configured_cap
    scaled_budget = max(12, round(section_count * 0.85))
    return min(configured_cap, scaled_budget)


def run_audit(db: Session, audit: Audit) -> Audit:
    ingestion = IngestionClient(settings.ingestion_service_url)
    knowledge = KnowledgeClient(settings.knowledge_service_url)

    audit.status = "running"
    audit.model_provider = settings.model_provider
    audit.model_name = settings.model_name
    audit.model_temperature = settings.model_temperature
    audit.prompt_template_version = settings.prompt_template_version
    audit.embedding_model = settings.embedding_model
    audit.corpus_version = settings.corpus_version
    db.commit()

    sections = ingestion.get_sections(audit.document_id)
    document_mode = _infer_document_mode(sections)
    llm_budget_cap = _effective_llm_budget(len(sections), settings.max_llm_calls_per_audit)
    llm_rate_limited = False
    llm_calls_made = 0
    audit_started = time.monotonic()
    timeout_reached = False

    for section in sorted(sections, key=lambda s: s.section_order):
        if not timeout_reached and _runtime_budget_exceeded(audit_started, time.monotonic(), settings.max_audit_runtime_seconds):
            timeout_reached = True

        if timeout_reached:
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="needs review",
                    severity=None,
                    gap_note=f"Audit runtime budget exceeded ({settings.max_audit_runtime_seconds}s). Manual review required.",
                    remediation_note=None,
                )
            )
            db.commit()
            continue

        if _is_not_applicable(section):
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="not applicable",
                    severity=None,
                    gap_note=None,
                    remediation_note=None,
                )
            )
            db.commit()
            continue

        topic = _infer_topic(section)
        query = _build_retrieval_query(section, topic, document_mode)
        chunks = _rerank_chunks_for_mode(section, knowledge.search(query=query, k=8), document_mode)[:5]

        if _retry_needed(chunks, topic):
            retrieval_retry_total.inc()
            query_retry = _build_retrieval_query(section, f"{topic} legal requirements", document_mode)
            chunks_retry = _rerank_chunks_for_mode(section, knowledge.search(query=query_retry, k=8), document_mode)[:5]
            if chunks_retry:
                chunks = chunks_retry

        if not _evidence_sufficient(chunks):
            evidence_gate_failure_total.inc()
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="needs review",
                    severity=None,
                    gap_note="Evidence sufficiency gate failed.",
                    remediation_note=None,
                )
            )
            db.commit()
            continue

        if llm_rate_limited or llm_calls_made >= llm_budget_cap:
            gate_reason = (
                "LLM rate limit reached earlier in this audit. Manual review required."
                if llm_rate_limited
                else f"LLM call budget reached ({llm_budget_cap}). Manual review required."
            )
            llm_finding = LlmFinding(
                status="needs review",
                severity=None,
                gap_note=gate_reason,
                remediation_note=None,
                citations=[],
            )
        else:
            with llm_inference_latency_seconds.time():
                llm_calls_made += 1
                llm_finding, raw = run_llm_classification(
                    section_title=section.section_title,
                    section_content=section.content,
                    chunks=chunks,
                    model_provider=settings.model_provider,
                    model_name=settings.model_name,
                    temperature=settings.model_temperature,
                    groq_api_key=settings.groq_api_key,
                    gemini_api_key=settings.gemini_api_key,
                    fallback_provider=settings.fallback_model_provider,
                    fallback_model=settings.fallback_model_name,
                )
            if raw == "__rate_limited__":
                llm_rate_limited = True

        f = _coerce_finding(llm_finding)
        valid_citations = _validate_citations(f.citations, chunks, section, document_mode)
        f = _enforce_substantive_citation_gate(f, valid_citations)

        finding_row = Finding(
            audit_id=audit.id,
            section_id=section.id,
            status=f.status,
            severity=f.severity,
            gap_note=f.gap_note,
            remediation_note=f.remediation_note,
        )
        db.add(finding_row)
        db.flush()

        for cit in valid_citations:
            db.add(
                FindingCitation(
                    finding_id=finding_row.id,
                    chunk_id=cit.chunk_id,
                    article_number=cit.article_number,
                    paragraph_ref=cit.paragraph_ref,
                    article_title=cit.article_title,
                    excerpt=cit.excerpt,
                )
            )

        db.commit()

    audit.status = "complete"
    audit.completed_at = datetime.utcnow()
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit
