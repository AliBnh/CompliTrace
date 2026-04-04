import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer


class SearchRequest(BaseModel):
    query: str = Field(min_length=2)
    k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    chunk_id: str
    article_number: str
    article_title: str
    paragraph_ref: str | None
    subpoint_range: str | None
    content: str
    source_pdf: str
    score: float


class SearchResponse(BaseModel):
    query: str
    k: int
    results: list[SearchResult]


class ChunkResponse(BaseModel):
    chunk_id: str
    article_number: str
    article_title: str
    chapter_number: str | None
    chapter_number_int: int | None
    chapter_title: str | None
    paragraph_ref: str | None
    subpoint_range: str | None
    subchunk_index: int | None
    subchunk_count: int | None
    content: str
    page_start: int | None
    page_end: int | None
    word_count: int
    source_pdf: str


QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "gdpr_chunks")
GDPR_CHUNKS_PATH = os.getenv("GDPR_CHUNKS_PATH", "/app/data/processed/gdpr_chunks.jsonl")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
FORCE_REINDEX = os.getenv("FORCE_REINDEX", "false").lower() == "true"


app = FastAPI(title="CompliTrace Knowledge Service", version="0.1.0")
embedder: SentenceTransformer | None = None
qdrant: QdrantClient | None = None


def chunk_point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"complitrace:{chunk_id}"))


def load_chunks(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"GDPR chunks file not found: {path}")

    chunks: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def ensure_collection(vector_size: int) -> None:
    assert qdrant is not None
    collections = {c.name for c in qdrant.get_collections().collections}
    if COLLECTION_NAME not in collections:
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )


def reindex_if_needed(chunks: list[dict[str, Any]]) -> dict[str, int]:
    assert qdrant is not None
    assert embedder is not None

    count = qdrant.count(collection_name=COLLECTION_NAME, exact=True).count
    if count > 0 and not FORCE_REINDEX:
        return {"indexed": 0, "existing": count}

    if FORCE_REINDEX and count > 0:
        qdrant.delete_collection(COLLECTION_NAME)
        ensure_collection(vector_size=embedder.get_sentence_embedding_dimension())

    texts = [c["content"] for c in chunks]
    vectors = embedder.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)

    points = []
    for chunk, vector in zip(chunks, vectors):
        payload = dict(chunk)
        payload["point_id"] = chunk_point_id(chunk["chunk_id"])
        points.append(
            models.PointStruct(
                id=payload["point_id"],
                vector=vector.tolist(),
                payload=payload,
            )
        )

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
    return {"indexed": len(points), "existing": 0}


@app.on_event("startup")
def startup() -> None:
    global qdrant, embedder

    qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    ensure_collection(vector_size=embedder.get_sentence_embedding_dimension())
    chunks = load_chunks(GDPR_CHUNKS_PATH)
    stats = reindex_if_needed(chunks)
    app.state.index_stats = stats


@app.get("/health")
def health() -> dict[str, Any]:
    stats = getattr(app.state, "index_stats", {"indexed": 0, "existing": 0})
    return {"status": "ok", "collection": COLLECTION_NAME, **stats}


@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    assert qdrant is not None
    assert embedder is not None

    query_vector = embedder.encode(req.query, normalize_embeddings=True).tolist()
    response = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=req.k,
        with_payload=True,
    )

    results: list[SearchResult] = []
    for point in response.points:
        payload = point.payload or {}
        results.append(
            SearchResult(
                chunk_id=str(payload.get("chunk_id")),
                article_number=str(payload.get("article_number", "")),
                article_title=str(payload.get("article_title", "")),
                paragraph_ref=payload.get("paragraph_ref"),
                subpoint_range=payload.get("subpoint_range"),
                content=str(payload.get("content", "")),
                source_pdf=str(payload.get("source_pdf", "")),
                score=float(point.score or 0.0),
            )
        )

    return SearchResponse(query=req.query, k=req.k, results=results)


@app.get("/chunks/{chunk_id}", response_model=ChunkResponse)
def get_chunk(chunk_id: str) -> ChunkResponse:
    assert qdrant is not None

    response = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="chunk_id", match=models.MatchValue(value=chunk_id))]
        ),
        with_payload=True,
        limit=1,
    )

    points = response[0]
    if not points:
        raise HTTPException(status_code=404, detail="Chunk not found")

    payload = points[0].payload or {}
    return ChunkResponse(**payload)
