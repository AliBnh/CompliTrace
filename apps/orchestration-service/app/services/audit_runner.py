from __future__ import annotations

import re
import time
from datetime import datetime

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


def _validate_citations(citations: list[LlmCitation], retrieved: list[RetrievalChunk]) -> list[LlmCitation]:
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
        if cit.paragraph_ref and chunk.paragraph_ref and cit.paragraph_ref != chunk.paragraph_ref:
            citation_validation_failure_total.inc()
            continue
        if not cit.chunk_id:
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
        query = f"GDPR obligations for {topic}: {section.content[:700]}"
        chunks = knowledge.search(query=query, k=5)

        if _retry_needed(chunks, topic):
            retrieval_retry_total.inc()
            query_retry = f"GDPR legal requirements and obligations for {topic}"
            chunks_retry = knowledge.search(query=query_retry, k=5)
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

        if llm_rate_limited or llm_calls_made >= settings.max_llm_calls_per_audit:
            gate_reason = (
                "LLM rate limit reached earlier in this audit. Manual review required."
                if llm_rate_limited
                else f"LLM call budget reached ({settings.max_llm_calls_per_audit}). Manual review required."
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
        valid_citations = _validate_citations(f.citations, chunks)
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
