# Day 6–8 Ingestion Service Gate

## Service scope

- `POST /documents`
- `GET /documents/{id}`
- `GET /documents/{id}/sections`
- `GET /health`

## Run stack for this gate

```bash
docker compose up -d --build postgres ingestion-service
```

## Validate

1. Health
```bash
curl -s http://localhost:8001/health
```

2. Upload a PDF
```bash
curl -s -X POST http://localhost:8001/documents \
  -F "file=@data/raw/SRS.pdf"
```

3. Check document status
```bash
curl -s http://localhost:8001/documents/<DOCUMENT_ID>
```

4. Check extracted sections
```bash
curl -s http://localhost:8001/documents/<DOCUMENT_ID>/sections
```

## Gate pass conditions

- Upload succeeds for a valid PDF.
- Document status is `parsed`.
- Sections list is non-empty and ordered.
- `page_start` / `page_end` fields are present when extractable.
