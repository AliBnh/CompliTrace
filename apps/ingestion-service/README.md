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

## Upload notes (Postman / VS Code clients)

- Preferred: `multipart/form-data` with key exactly `file` and a `.pdf` file.
- Do **not** force `Content-Type: application/json` for upload requests.
- Fallback supported: raw PDF body with header `Content-Type: application/pdf` and optional `X-Filename: your-file.pdf`.
