# CompliTrace Repository Deep Technical Analysis

This document provides a full-system engineering analysis of CompliTrace’s current codebase as checked into this repository.

## 1) Project Structure

## 1.1 Repository topology

- `apps/frontend`: React + Vite SPA with four routed workflow pages (Upload, Sections, Findings, Report) and a deterministic presentation-normalization layer that sanitizes/internal-filters backend outputs before rendering/exporting.
- `apps/ingestion-service`: FastAPI service for PDF upload, parsing, section extraction, and persistence to PostgreSQL (`documents`, `sections`).
- `apps/knowledge-service`: FastAPI service for GDPR chunk retrieval. On startup it loads `gdpr_chunks.jsonl`, embeds chunk text, and indexes/searches in Qdrant.
- `apps/orchestration-service`: FastAPI service that owns audit lifecycle, LLM + retrieval orchestration, persistence of findings/analysis/citations/evidence records, publication guards, and PDF report generation.
- `data/raw`: regulatory/document source PDFs used for corpus preparation.
- `data/processed`: chunked GDPR JSONL used by knowledge-service indexing.
- `infra/prometheus` and `infra/grafana`: observability provisioning for service metrics and dashboard wiring.
- `scripts`: corpus ingestion/validation utilities for GDPR chunk production and retrieval quality gates.
- `docs`: SRS and sample PDFs used for demo/testing fixtures.

## 1.2 Runtime composition (Docker Compose)

`docker-compose.yml` defines 8 primary runtime containers:
1. Postgres
2. Qdrant
3. ingestion-service
4. knowledge-service
5. orchestration-service
6. Prometheus
7. Grafana
8. frontend

Inter-service links are synchronous HTTP calls from orchestration to ingestion + knowledge and from frontend to ingestion/orchestration. Storage volumes persist Postgres/Qdrant plus uploaded documents and generated reports.

## 1.3 Service entrypoints and internal module boundaries

### Ingestion service
- Entrypoint `app/main.py` configures JSON logging, CORS, DB metadata creation, routers, and `/metrics`.
- `api/routes.py` provides upload/document/sections HTTP surface and parsing counters/histogram.
- `services/parser.py` performs text cleanup, heading detection, boilerplate stripping, sectionization/refinement, and PDF parsing.
- `models/document.py`, `schemas/document.py`, and `repositories/documents.py` define persistence and DTO transformation.

### Knowledge service
- Single-file architecture in `app/main.py`.
- Startup path: initialize Qdrant + embedding model, ensure collection, load JSONL chunks, and optionally (re)index vectors.
- Runtime path: `/search` for semantic retrieval and `/chunks/{id}` for exact payload lookup.

### Orchestration service
- Entrypoint `app/main.py` configures JSON logging, CORS, metadata creation, and dynamic schema-hardening ALTERs for legacy DBs.
- `services/clients.py` wraps ingestion/knowledge HTTP clients with retry.
- `services/llm.py` encapsulates prompting, provider fallback (Groq/Gemini), JSON extraction, and finding coercion.
- `services/audit_runner.py` implements the bounded audit engine and publication-state synthesis.
- `api/routes.py` exposes audit, findings, analysis, review, grouped-review, and report endpoints with multiple publication/reconciliation validators.
- `services/reports.py` builds user-facing PDF report content and renders raw PDF bytes without external PDF libs.
- `models/audit.py` + `schemas/audit.py` provide data model and API contracts.

## 1.4 Frontend module boundaries

- `src/app/App.tsx` defines route graph.
- `src/app/state.tsx` stores cross-page workflow IDs (`documentId`, `auditId`).
- `src/lib/api.ts` centralizes API calls.
- `src/lib/types.ts` defines DTO contracts from backend.
- `src/lib/presentation.ts` is a critical domain layer converting heterogeneous published/review/analysis rows into stable UI rows; it also enforces sanitization/invariant checks used by Findings + Report pages.
- `src/features/*` implements page-level views and polling behavior.

## 2) End-to-End Flow

## 2.1 User journey (happy path)

1. **Upload PDF** (frontend Upload page):
   - User selects a `.pdf` and clicks “Upload & parse”.
   - Frontend sends multipart `POST /documents` to ingestion service.
2. **Ingestion parse + persist**:
   - Ingestion validates input mode (multipart or raw PDF body), enforces `.pdf` extension, stores file on disk, parses sections from PDF text, writes `Document + Section[]` rows, returns `DocumentOut` including section count.
3. **Section review**:
   - Frontend calls `GET /documents/{id}/sections` and displays extracted structure/preview and page ranges.
   - User triggers audit.
4. **Audit run**:
   - Frontend calls `POST /audits` with `document_id`.
   - Orchestration creates `Audit` row then synchronously executes `run_audit`.
   - `run_audit` fetches sections from ingestion service, runs candidate issue spotting + retrieval + LLM evaluation per section, validates citations/consistency, persists findings/citations/analysis, runs document-wide synthesis and publication validators, snapshots analysis/evidence records, and marks audit complete.
5. **Findings workspace**:
   - Frontend polls `GET /audits/{id}`, `GET /audits/{id}/findings`, `GET /audits/{id}/review`, `GET /audits/{id}/analysis`.
   - UI builds three datasets (published/review/analysis), with automatic fallback to review if publication is blocked.
6. **Report generation**:
   - Frontend computes export-readiness invariants locally; if valid, it calls `POST /audits/{id}/report`.
   - Orchestration generates a new report row + PDF file, then frontend polls `GET /audits/{id}/report` until status is `ready` and offers `/report/download` link.

## 2.2 Data transformations along path

- Raw PDF bytes -> extracted line stream -> cleaned lines -> heading/body chunks -> refined section records (`ParsedSection`) -> DB `Section` rows.
- Section text + retrieval chunks + guidance -> LLM JSON output -> typed `LlmFinding` + validated `LlmCitation[]` -> persisted `Finding + FindingCitation` with confidence/classification/publication fields.
- Published/review/analysis backend rows -> frontend normalized `Issue`/`SectionFinding` rows with deterministic sanitization and canonical issue mapping.
- Findings rows -> report-safe text blocks -> handwritten PDF object stream.

## 3) Backend APIs (complete)

## 3.1 Ingestion-service endpoints

- `GET /health`
  - Purpose: liveness.
  - Output: `{"status":"ok"}`.

- `POST /documents`
  - Purpose: upload + parse + persist document/sections.
  - Inputs:
    - Preferred: multipart form key `file` with `.pdf`.
    - Fallback: raw PDF body with `Content-Type: application/pdf` (or octet-stream), optional `X-Filename`.
  - Output: `DocumentOut` (`id,title,filename,status,error_message,created_at,section_count`).
  - Internal flow: validate, store file, parse sections, persist parsed rows; on parse failure persist failed doc and return 422.

- `GET /documents/{document_id}`
  - Purpose: document metadata.
  - Output: `DocumentOut`.

- `GET /documents/{document_id}/sections`
  - Purpose: ordered extracted sections.
  - Output: `SectionOut[]` with title/content/page range.

## 3.2 Knowledge-service endpoints

- `GET /health`
  - Purpose: liveness/indexing state.
  - Output: `status`, collection name, and index stats.

- `POST /search`
  - Purpose: semantic retrieval against chunk vectors.
  - Input: `{"query": string>=2 chars, "k": 1..20}`.
  - Output: `SearchResponse` with ranked chunk metadata and score.

- `GET /chunks/{chunk_id}`
  - Purpose: fetch one chunk payload by logical chunk id.
  - Output: full chunk payload (`article_number`, title, paragraph/subpoint/page refs, content, source PDF).

## 3.3 Orchestration-service endpoints

- `GET /health` — liveness.
- `POST /audits` — create and execute audit for `document_id`.
- `GET /audits/{audit_id}` — audit status + model/corpus provenance.
- `GET /audits/{audit_id}/findings` — publication-facing findings projection with strict reconciliation + release validation gates.
- `GET /audits/{audit_id}/analysis` — internal analysis candidates (filterable by status/issue/role/section/stage).
- `GET /audits/{audit_id}/review` — reviewer dataset combining findings + selected analysis artifacts + core/specialist review blocks from final disposition map.
- `GET /audits/{audit_id}/review/grouped` — grouped review buckets (`publication_blockers`, `core_duty_resolution`, etc.).
- `POST /audits/{audit_id}/report` — trigger PDF generation (requires audit `complete`; blocked for `review_required`).
- `GET /audits/{audit_id}/report` — latest report metadata.
- `GET /audits/{audit_id}/report/download` — report PDF file stream.

## 4) AI System (critical)

## 4.1 Models/providers and deterministic controls

- Primary/fallback LLM providers are configured in orchestration settings (`MODEL_PROVIDER`, `MODEL_NAME`, `FALLBACK_MODEL_PROVIDER`, `FALLBACK_MODEL_NAME`) and keyed by `GROQ_API_KEY` / `GEMINI_API_KEY`.
- `run_llm_classification` builds one frozen prompt, attempts primary then fallback, with 429 retry handling and rate-limit sentinel.
- Parsed LLM output is constrained to a strict JSON schema and normalized into `LlmFinding`/`LlmCitation`.
- Deterministic controls (non-LLM) heavily post-process outputs: citation compatibility, article-family matrices, contradiction checks, not-assessable gates, explicit violation library promotion, consistency gating, duplicate signature suppression, publication validators, and final disposition reconciliation.

## 4.2 Prompting design

`SYSTEM_PROMPT` imposes:
- required JSON keys,
- allowed statuses,
- citation constraints to retrieved chunks only,
- uncertainty policy (`needs review`),
- notice-specific article prioritization and forbidden primary citations for external transparency gaps.

`_build_user_prompt` injects section title/content, retrieval snippets with chunk/article/paragraph/score, optional section guidance, and additional rubric reminders.

## 4.3 Retrieval/RAG design

- Retrieval index source: `data/processed/gdpr_chunks.jsonl` loaded into Qdrant with embeddings (`EMBEDDING_MODEL`, default BAAI bge-small in knowledge service).
- Query flow in audit-runner:
  - infer topic/document mode,
  - generate retrieval query,
  - retrieve top-k via knowledge service,
  - optional retry/re-ranking,
  - evidence sufficiency checks,
  - citation validation by chunk-id/article/paragraph compatibility and issue-specific article matrix.
- Retrieval can be filtered and post-ranked based on notice/policy context, claim types, and source-scope reasoning.

## 4.4 Agentic architecture inside `audit_runner`

The audit engine is rule-heavy and multi-stage:
1. Section auditability/not-applicable gating.
2. Candidate issue spotting and legal-fact extraction.
3. Applicability memo + decision (direct/indirect/mixed collection mode and allowed notice articles).
4. Retrieval query and chunk acquisition (with retries/re-ranking).
5. LLM classification call (budget/rate-limit aware).
6. Citation compatibility + legal relevance checks.
7. Quality classification (`clear_non_compliance`, `probable_gap`, `not_assessable`, internal-only classes).
8. Persist local findings + citations + confidence components.
9. Document-wide synthesis (`systemic:*` findings), support linking, completeness enforcement.
10. Final publication validation + suppression ledger + partner review pass + state invariant validator.

## 4.5 Deterministic vs non-deterministic behavior

- Non-deterministic: provider LLM responses and embedding similarity scores.
- Deterministic: prompt construction, fallback order, regex/fact extraction heuristics, article gating matrices, publication/reconciliation validators, report sanitization, frontend normalization and invariant checks.
- Net effect: model variability is bounded by extensive deterministic post-processing before publication/export.

## 5) Data Flow & Processing

## 5.1 Collection

- User uploads document via frontend to ingestion service.
- Knowledge service ingests preprocessed GDPR chunk corpus at startup (not via user input).

## 5.2 Parsing and sectionization

- Parser removes noise (file paths, page numbers, punctuation-only lines, tiny tokens), splits inline numbered headings, detects headings vs sentence-like lines, detects repeated boilerplate lines, and refines section boundaries including embedded subheadings.
- It preserves page start/end where possible and emits fallback single-body section if no headings are found.

## 5.3 Transformation

- Ingestion transforms parsed sections into relational rows.
- Orchestration transforms section + retrieval + LLM into rich finding records including confidence decomposition, legal anchors, publication metadata, and explanation fields.
- Frontend transforms heterogeneous backend records into canonical UI issues with canonical labels, severity mapping, and banned-token sanitization.

## 5.4 Storage and retrieval

- PostgreSQL: documents/sections/audits/findings/citations/analysis/reports/evidence.
- Qdrant: vectorized GDPR chunks and payload metadata.
- Filesystem volumes: uploaded PDFs and generated report PDFs.

## 6) Report Generation

## 6.1 Inputs

- Audit + findings + selected analysis rows from DB.
- Section labels/page ranges fetched from ingestion service.

## 6.2 Processing pipeline

1. Create pending report row.
2. Gather findings and decide dataset mode:
   - final publishable findings, or
   - review-visible fallback when publication blocked.
3. Deduplicate by section with worst-status precedence.
4. Remove internal/diagnostic terms via sanitizer and export-safe checks.
5. Build text blocks: header, executive summary counts, document-wide findings, section findings, citations, recommended actions.
6. Render PDF via custom low-level PDF writer.
7. Persist ready status + path.

## 6.3 Output semantics

- Status labels intentionally user-facing (`Non-compliant`, `Partially compliant`, etc.)
- Includes source dataset label indicating whether export used published or review fallback.
- Evidence lines prefer citation excerpts; otherwise produce scoped absence statement.

## 7) Auditing & Logging

## 7.1 Structured logging

All services configure JSON log formatting with `timestamp`, `level`, `service`, `message` and emit to stdout.

## 7.2 Metrics and monitoring

- Every service exposes `/metrics` and `/health`.
- Ingestion metrics track upload attempts/success/failure and parse duration.
- Knowledge metrics track retrieval count/latency/results and chunk lookups.
- Orchestration metrics track retries, evidence/citation gate failures, inference latency, audit duration, status counts, pass counters, and publication counters.
- Prometheus scrapes all three backend services; Grafana is provisioned with Prometheus datasource and dashboard provider.

## 7.3 Audit provenance and publication safety

- Audit rows store model/corpus/prompt provenance.
- Findings include publication metadata (`publish_flag`, `artifact_role`, `finding_level`, `publication_state`) and many evidence/applicability fields.
- Suppression/final-disposition logic and reconciliation validators in routes/audit_runner block unsafe publication and can force `audit_incomplete` or review-required states.

## 8) Frontend UI/UX (all pages)

## 8.1 Upload page

- Elements: file chooser drop area, upload button, progress bar, error banner, 4-step guidance panel.
- Depends on: `uploadDocument` API and app-state setters.
- Actions: choose file, upload, route to Sections on success.

## 8.2 Sections page

- Elements: section metrics (count/avg length/page refs), list of parsed sections, start-audit button.
- Depends on: `getSections(documentId)` and `createAudit(documentId)`.
- Actions: inspect extraction quality, launch audit, route to Findings.

## 8.3 Findings page (detailed)

- Polling: every 3.5s fetches audit status + published/review/analysis datasets.
- View modes: `published`, `review`, `analysis` toggle pills.
- Header state:
  - audit status string,
  - dataset label per mode,
  - blocking warning when final publication unavailable.
- Metrics row (unless published blocked): counts by compliant/partial/non-compliant/not-applicable/total based on active section-level dataset.
- Document-wide panel: renders systemic findings summary cards.
- Section table:
  - columns: Section, Issues, Status badge, Severity,
  - click selects row for side detail panel.
- Detail panel:
  - section title + status + severity badge,
  - dataset origin,
  - per-issue cards with Why this matters, Recommended action, Legal anchors, Evidence.
- Sanitization and canonicalization are done by presentation layer before render.

## 8.4 Report page

- Loads published/review/analysis datasets and sections.
- Calculates report dataset selection + status counts + invariant readiness.
- “Generate PDF” disabled if invariants fail.
- Polls report status every 2.5s during generation.
- Provides report download link and export preview (top findings).

## 9) Database Schema (complete from models)

## 9.1 Ingestion DB tables

### `documents`
- `id` PK (uuid string)
- `title`, `filename`
- `status` (`pending|parsed|failed`)
- `error_message`
- `created_at`

### `sections`
- `id` PK
- `document_id` FK -> `documents.id` (indexed, cascade delete)
- `section_order`
- `section_title`
- `content`
- `page_start`, `page_end`

Relationship: one document -> many sections.

## 9.2 Orchestration DB tables

### `audits`
- `id` PK
- `document_id` (indexed)
- lifecycle fields: `status`, `started_at`, `completed_at`
- provenance: `model_provider`, `model_name`, `model_temperature`, `prompt_template_version`, `embedding_model`, `corpus_version`

### `findings`
- `id` PK
- `audit_id` FK -> `audits.id` (indexed)
- `section_id` (indexed, width widened to 128 for systemic/ledger ids)
- core finding: `status`, `severity`, `classification`, `gap_note`, `remediation_note`
- publication and artifact fields: `finding_type`, `publish_flag`, `artifact_role`, `finding_level`, `publication_state`
- confidence vector fields and many legal/applicability/scope/anchor/support fields.

### `finding_citations`
- `id` PK
- `finding_id` FK -> `findings.id` (indexed)
- `chunk_id`, `article_number`, `paragraph_ref`, `article_title`, `excerpt`

### `audit_analysis_items`
- candidate/internal analysis artifacts per section with status/classification candidates, legal/retrieval summaries, confidence, and outcome fields.

### `analysis_citations`
- citations attached to analysis items.

### `reports`
- `id` PK
- `audit_id` FK -> `audits.id` (indexed)
- `status`, `pdf_path`, `created_at`

### `evidence_records`
- `evidence_id` PK
- `audit_id` FK
- `evidence_type`, `source_ref`, `text_excerpt`, derived-linkage fields, `article_number`, `paragraph_ref`, `created_at`

## 9.3 Relationship summary

- One `audit` has many `findings`, `reports`, `analysis_items`, and `evidence_records`.
- One `finding` has many `finding_citations`.
- One `analysis_item` has many `analysis_citations`.

## 9.4 Indexing notes

Explicit indexes exist on major FK / lookup keys (`document_id`, `audit_id`, `section_id`, citation parent keys, evidence type). Qdrant indexes vectors implicitly by collection configuration.

## 10) System Logic & Decision-Making

## 10.1 Scenario behavior

- **Administrative/non-auditable section**: short-circuits to not-applicable/filtered path with counters.
- **Weak retrieval evidence**: retry + evidence gate; can produce internal/review-only artifacts instead of publishable finding.
- **Missing/invalid citations**: citations dropped; may downgrade or block publication classification.
- **Explicit violation pattern**: deterministic library can promote to high-severity gap irrespective of model hesitation.
- **Contradiction with positive disclosure**: contradiction controls can block publication and mark internal-only.
- **Family completeness gap**: final publication validator may block findings or set audit incomplete when publishable family is unmaterialized.
- **Publication blocked**: Findings endpoint may return 409 and frontend automatically uses review dataset for report/export mode.

## 10.2 Conditional branching highlights

- Route-layer publication gates in `/audits/{id}/findings` combine:
  - audit status guard,
  - final decision map allowance,
  - hydration/projection of publishable families,
  - reconciliation blockers,
  - release validator.
- Report generation is blocked unless audit is `complete` and not `review_required`.
- Frontend report export is blocked unless invariant checks pass for dataset identity/counts/statuses and sanitized human-readable content.

## 11) File-by-file inventory (excluding dependencies)

- Top-level runtime/infrastructure: `docker-compose.yml`, `readme.md`.
- Data/corpus: `data/raw/*.pdf`, `data/processed/gdpr_chunks.jsonl`.
- Docs/demo assets: `docs/*.pdf`, `docs/srs.md`, `docs/SRS.pdf`.
- Ingestion service code + tests + Docker + requirements under `apps/ingestion-service`.
- Knowledge service code + docs + Docker + requirements under `apps/knowledge-service`.
- Orchestration service code + tests + Docker + requirements under `apps/orchestration-service`.
- Frontend app code/config/scripts under `apps/frontend`.
- Observability configs under `infra/prometheus` and `infra/grafana`.
- Utility scripts under `scripts/`.
- Local lightweight `prometheus_client/` shim module.

(Third-party `node_modules` is intentionally excluded from this technical walkthrough as generated dependency content, not authored repository logic.)

