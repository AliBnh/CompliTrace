# Knowledge Service (Port 8002)

FastAPI service that indexes GDPR chunks into Qdrant and exposes retrieval APIs.

## Endpoints

- `POST /search`
  - Input: `{ "query": "...", "k": 5 }`
  - Output: top-k chunks with similarity score and citation metadata.
- `GET /chunks/{chunk_id}`
  - Output: full chunk record for one GDPR chunk.
- `GET /health`
  - Output: basic service/indexing status.

## Run with Docker Compose

```bash
docker compose up -d --build
```

## Example calls

```bash
curl -s http://localhost:8002/health

curl -s -X POST http://localhost:8002/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"data retention period", "k":5}'

curl -s http://localhost:8002/chunks/gdpr-art-1-p-1-2-seg-1-c44b808c9158
```
