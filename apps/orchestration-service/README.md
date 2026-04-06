# CompliTrace Orchestration Service

Owns audit lifecycle, bounded agent loop, findings persistence, and PDF report generation hooks.

## Endpoints

- `POST /audits`
- `GET /audits/{id}`
- `GET /audits/{id}/findings`
- `POST /audits/{id}/report`
- `GET /audits/{id}/report`
- `GET /audits/{id}/report/download`
- `GET /health`
- `GET /metrics`

## Local run

```bash
uvicorn app.main:app --reload --port 8003
```
