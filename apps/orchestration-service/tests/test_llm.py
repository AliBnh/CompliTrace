from pathlib import Path
import sys

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services import llm
from app.services.clients import RetrievalChunk


def _chunks() -> list[RetrievalChunk]:
    return [
        RetrievalChunk(
            chunk_id="c1",
            article_number="5",
            article_title="Principles",
            paragraph_ref="1(e)",
            content="controller shall apply storage limitation",
            score=0.8,
        )
    ]


def test_fallback_used_when_primary_rate_limited(monkeypatch):
    def fake_groq(*_args, **_kwargs):
        raise httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
            response=httpx.Response(429),
        )

    def fake_gemini(*_args, **_kwargs):
        return '{"status":"needs review","severity":null,"gap_note":"rate limited","remediation_note":null,"citations":[]}'

    monkeypatch.setattr(llm, "_groq_chat", fake_groq)
    monkeypatch.setattr(llm, "_gemini_chat", fake_gemini)

    finding, raw = llm.run_llm_classification(
        section_title="Retention",
        section_content="We keep records.",
        chunks=_chunks(),
        model_provider="groq",
        model_name="primary-model",
        temperature=0.1,
        groq_api_key="gk",
        gemini_api_key="gem",
        fallback_provider="gemini",
        fallback_model="fallback-model",
    )

    assert finding is not None
    assert finding.status == "needs review"
    assert "needs review" in raw


def test_returns_none_when_all_providers_fail(monkeypatch):
    def always_fail(*_args, **_kwargs):
        raise httpx.HTTPStatusError(
            "provider failure",
            request=httpx.Request("POST", "https://example.com"),
            response=httpx.Response(503),
        )

    monkeypatch.setattr(llm, "_groq_chat", always_fail)
    monkeypatch.setattr(llm, "_gemini_chat", always_fail)

    finding, raw = llm.run_llm_classification(
        section_title="Retention",
        section_content="We keep records.",
        chunks=_chunks(),
        model_provider="groq",
        model_name="primary-model",
        temperature=0.1,
        groq_api_key="gk",
        gemini_api_key="gem",
        fallback_provider="gemini",
        fallback_model="fallback-model",
    )

    assert finding is None
    assert raw == ""


def test_groq_retries_429_and_succeeds(monkeypatch):
    calls = {"n": 0}

    class StubResponse:
        def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}
            self.headers = headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{self.status_code}",
                    request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
                    response=httpx.Response(self.status_code, headers=self.headers),
                )

        def json(self):
            return self._payload

    def fake_post(url, headers, json, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return StubResponse(429, headers={"retry-after": "0"})
        return StubResponse(
            200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": '{"status":"compliant","severity":null,"gap_note":null,"remediation_note":null,"citations":[]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr("app.services.llm.time.sleep", lambda _seconds: None)

    raw = llm._groq_chat(
        api_key="gk",
        model="primary-model",
        temperature=0.1,
        user_prompt="prompt",
    )

    assert calls["n"] == 2
    assert "compliant" in raw
