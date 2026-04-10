from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import httpx

from app.services.clients import LlmCitation, LlmFinding, RetrievalChunk


SYSTEM_PROMPT = (
    "You are a GDPR compliance analyst. Return strict JSON with keys: "
    "status, severity, gap_note, remediation_note, citations, candidate_publishability. "
    "Allowed status: compliant, partial, gap, needs review. "
    "Citations must only reference provided chunks and include chunk_id + article_number. "
    "If status is partial or gap, include at least one concrete citation. "
    "If evidence is weak, return needs review instead of speculating. "
    "For privacy notices prioritize disclosure obligations under Articles 12-14 before internal governance articles. "
    "Do not use Articles 24, 25, 33, 34, or 70 as primary citations for missing external privacy-notice disclosures. "
    "For transfer transparency use Articles 13(1)(f)/14(1)(f) and Chapter V (44-49). "
    "Do not use Article 18 as transfer-safeguard evidence."
)

STATUS_MAP = {
    "compliant": "compliant",
    "partial": "partial",
    "partially compliant": "partial",
    "partially": "partial",
    "gap": "gap",
    "non-compliant": "gap",
    "non compliant": "gap",
    "needs review": "needs review",
    "needs_review": "needs review",
    "need review": "needs review",
}
MAX_RETRY_AFTER_SECONDS = 5.0


def _extract_json_block(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        return m.group(0)
    return "{}"


def _build_user_prompt(section_title: str, section_content: str, chunks: list[RetrievalChunk], guidance: str | None = None) -> str:
    chunk_lines = []
    for c in chunks:
        chunk_lines.append(
            f"chunk_id={c.chunk_id} | article={c.article_number} | paragraph={c.paragraph_ref} | score={c.score:.3f} | text={c.content[:550]}"
        )
    joined = "\n".join(chunk_lines)
    return (
        f"Section title: {section_title}\n"
        f"Section content:\n{section_content[:5000]}\n\n"
        f"Retrieved GDPR chunks:\n{joined}\n\n"
        f"Section-specific legal guidance: {guidance or 'None'}\n\n"
        "Apply frozen rubric. If uncertain, return needs review. "
        "For gap/partial provide non-empty gap_note and remediation_note with at least one citation tied to a retrieved chunk. "
        "Do not cite GDPR articles not present in retrieved chunks."
    )


def _normalize_status(value: Any) -> str:
    if value is None:
        return "needs review"
    key = str(value).strip().lower()
    return STATUS_MAP.get(key, "needs review")


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _coerce_citations(raw_citations: Any) -> list[LlmCitation]:
    if not isinstance(raw_citations, list):
        return []
    out: list[LlmCitation] = []
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        chunk_id = _safe_text(item.get("chunk_id"))
        article_number = _safe_text(item.get("article_number"))
        if not chunk_id or not article_number:
            continue
        out.append(
            LlmCitation(
                chunk_id=chunk_id,
                article_number=article_number,
                paragraph_ref=_safe_text(item.get("paragraph_ref")),
                article_title=_safe_text(item.get("article_title")) or "",
                excerpt=_safe_text(item.get("excerpt")) or "",
            )
        )
    return out


def _coerce_finding_from_parsed(parsed: dict[str, Any]) -> LlmFinding:
    return LlmFinding(
        status=_normalize_status(parsed.get("status")),
        severity=_safe_text(parsed.get("severity")),
        gap_note=_safe_text(parsed.get("gap_note")),
        remediation_note=_safe_text(parsed.get("remediation_note")),
        citations=_coerce_citations(parsed.get("citations")),
        candidate_publishability=_safe_text(parsed.get("candidate_publishability")),
    )


def _groq_chat(api_key: str, model: str, temperature: float, user_prompt: str) -> str:
    last_error: httpx.HTTPStatusError | None = None
    for attempt in range(3):
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=60,
        )
        try:
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code != 429 or attempt == 2:
                raise
            retry_after_raw = exc.response.headers.get("retry-after")
            try:
                retry_after = float(retry_after_raw) if retry_after_raw is not None else 2.0
            except ValueError:
                retry_after = 2.0
            time.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
    assert last_error is not None
    raise last_error


def _gemini_chat(api_key: str, model: str, temperature: float, user_prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
        "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}]}],
    }
    last_error: httpx.HTTPStatusError | None = None
    for attempt in range(3):
        resp = httpx.post(url, json=payload, timeout=60)
        try:
            resp.raise_for_status()
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code != 429 or attempt == 2:
                raise
            time.sleep(2.0)
    assert last_error is not None
    raise last_error


def run_llm_classification(
    section_title: str,
    section_content: str,
    chunks: list[RetrievalChunk],
    guidance: str | None,
    model_provider: str,
    model_name: str,
    temperature: float,
    groq_api_key: str | None,
    gemini_api_key: str | None,
    fallback_provider: str,
    fallback_model: str,
) -> tuple[LlmFinding | None, str]:
    prompt = _build_user_prompt(section_title, section_content, chunks, guidance)
    raw = ""
    attempts: list[tuple[str, str, Callable[[], str]]] = []
    saw_rate_limit = False

    if model_provider == "groq" and groq_api_key:
        attempts.append(("primary", "groq", lambda: _groq_chat(groq_api_key, model_name, temperature, prompt)))
    elif model_provider == "gemini" and gemini_api_key:
        attempts.append(("primary", "gemini", lambda: _gemini_chat(gemini_api_key, model_name, temperature, prompt)))

    if fallback_provider == "gemini" and gemini_api_key:
        attempts.append(("fallback", "gemini", lambda: _gemini_chat(gemini_api_key, fallback_model, temperature, prompt)))
    elif fallback_provider == "groq" and groq_api_key:
        attempts.append(("fallback", "groq", lambda: _groq_chat(groq_api_key, fallback_model, temperature, prompt)))

    for _role, _provider, call in attempts:
        try:
            raw = call()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                saw_rate_limit = True
            continue
        except httpx.HTTPError:
            continue
        if raw:
            break

    if not raw:
        if saw_rate_limit:
            return None, "__rate_limited__"
        return None, ""

    block = _extract_json_block(raw)
    try:
        parsed: dict[str, Any] = json.loads(block)
        finding = _coerce_finding_from_parsed(parsed)
        return finding, raw
    except Exception:
        repaired = block.replace("“", '"').replace("”", '"').replace("’", "'")
        try:
            parsed = json.loads(repaired)
            finding = _coerce_finding_from_parsed(parsed)
            return finding, raw
        except Exception:
            return None, raw
