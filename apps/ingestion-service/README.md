# Ingestion Service (Port 8001)

FastAPI service for document upload, parsing, section detection, and persistence.

## Endpoints

- `POST /documents` (multipart file upload, PDF only)
- `GET /documents/{id}`
- `GET /documents/{id}/sections`
- `GET /health`

## Run (with compose)

```bash
docker compose up -d --build postgres ingestion-service
```
