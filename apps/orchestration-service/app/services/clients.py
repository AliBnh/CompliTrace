from __future__ import annotations

import time

import httpx
from pydantic import BaseModel, Field


class SectionData(BaseModel):
    id: str
    section_order: int
    section_title: str
    content: str
    page_start: int | None = None
    page_end: int | None = None


class DocumentData(BaseModel):
    id: str
    title: str
    filename: str
    status: str
    section_count: int | None = None


class RetrievalChunk(BaseModel):
    chunk_id: str
    article_number: str
    article_title: str
    paragraph_ref: str | None
    content: str
    score: float


class IngestionClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.max_attempts = 4
        self.retry_delay_seconds = 0.4

    def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        last_exc: httpx.RequestError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return httpx.request(method, f"{self.base_url}{path}", **kwargs)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    raise
                time.sleep(self.retry_delay_seconds * attempt)
        assert last_exc is not None
        raise last_exc

    def get_sections(self, document_id: str) -> list[SectionData]:
        resp = self._request_with_retry("GET", f"/documents/{document_id}/sections", timeout=30)
        resp.raise_for_status()
        return [SectionData.model_validate(x) for x in resp.json()]

    def get_document(self, document_id: str) -> DocumentData:
        resp = self._request_with_retry("GET", f"/documents/{document_id}", timeout=30)
        resp.raise_for_status()
        return DocumentData.model_validate(resp.json())


class KnowledgeClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.max_attempts = 4
        self.retry_delay_seconds = 0.4

    def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        last_exc: httpx.RequestError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return httpx.request(method, f"{self.base_url}{path}", **kwargs)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    raise
                time.sleep(self.retry_delay_seconds * attempt)
        assert last_exc is not None
        raise last_exc

    def search(self, query: str, k: int = 5) -> list[RetrievalChunk]:
        resp = self._request_with_retry("POST", "/search", json={"query": query, "k": k}, timeout=45)
        resp.raise_for_status()
        payload = resp.json()
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        return [RetrievalChunk.model_validate(x) for x in results]

    def get_chunk(self, chunk_id: str) -> dict:
        resp = self._request_with_retry("GET", f"/chunks/{chunk_id}", timeout=30)
        resp.raise_for_status()
        return resp.json()


class LlmCitation(BaseModel):
    chunk_id: str
    article_number: str
    paragraph_ref: str | None = None
    article_title: str = ""
    excerpt: str = ""


class LlmFinding(BaseModel):
    status: str = Field(pattern=r"^(compliant|partial|gap|needs review)$")
    severity: str | None = None
    gap_note: str | None = None
    remediation_note: str | None = None
    citations: list[LlmCitation] = Field(default_factory=list)
