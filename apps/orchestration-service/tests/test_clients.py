from pathlib import Path
import sys

import httpx

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.clients import IngestionClient, KnowledgeClient


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_ingestion_retries_request_errors(monkeypatch):
    calls = {"n": 0}

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("connection refused", request=httpx.Request(method, url))
        return _StubResponse(
            [
                {
                    "id": "s1",
                    "section_order": 1,
                    "section_title": "Retention",
                    "content": "We retain data.",
                    "page_start": 1,
                    "page_end": 2,
                }
            ]
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr("app.services.clients.time.sleep", lambda _seconds: None)

    client = IngestionClient("http://ingestion-service:8001")
    rows = client.get_sections("doc-1")

    assert len(rows) == 1
    assert calls["n"] == 3


def test_knowledge_retries_then_returns_results(monkeypatch):
    calls = {"n": 0}

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused", request=httpx.Request(method, url))
        return _StubResponse(
            {
                "results": [
                    {
                        "chunk_id": "c1",
                        "article_number": "5",
                        "article_title": "Principles",
                        "paragraph_ref": "1(e)",
                        "content": "Personal data shall be kept no longer than necessary.",
                        "score": 0.8,
                    }
                ]
            }
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    monkeypatch.setattr("app.services.clients.time.sleep", lambda _seconds: None)

    client = KnowledgeClient("http://knowledge-service:8002")
    rows = client.search("retention", k=5)

    assert len(rows) == 1
    assert rows[0].chunk_id == "c1"
    assert calls["n"] == 2
