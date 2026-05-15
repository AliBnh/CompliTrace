# CompliTrace Repository Analysis (Exhaustive, Code-Aligned Deep Dive)

**Verification date:** 2026-04-21 (UTC)
**Scope:** Full repository (`apps/*`, `scripts/*`, `infra/*`, `data/*`, root compose/config/docs)

---

## 0) Purpose and framing

This document provides a deeply detailed, implementation-centric analysis of how CompliTrace currently works end-to-end.

It focuses on what the code actually does now:

- architecture and service boundaries,
- runtime wiring,
- DB models and persistence semantics,
- per-service API contracts,
- parser logic,
- retrieval flow,
- orchestration control flow,
- deterministic legal/publication gates,
- review and export projections,
- report generation internals,
- frontend normalization and UI flow,
- observability and invariant tests.

This is intentionally not a product pitch; it is an engineering map of the current behavior.

---

## 1) Repository topology and role of each area

### 1.1 Top-level layout

- `apps/auth-service/`
  - FastAPI service for user registration, login, JWT token generation, and token verification.
  - Manages user credentials (email/password with bcrypt hashing) and JWT lifecycle.
  - Required dependency for all protected orchestration endpoints.
- `apps/ingestion-service/`
  - FastAPI service for document upload, PDF parse, section extraction, and persistence of `Document` + `Section` rows.
- `apps/knowledge-service/`
  - FastAPI retrieval service backed by Qdrant and FastEmbed.
  - Responsible for loading/indexing GDPR chunks and serving semantic search/chunk lookup.
- `apps/orchestration-service/`
  - FastAPI service implementing audit lifecycle, section-by-section legal assessment, gating, publication controls, review datasets, export contract, and PDF report workflows.
  - All endpoints protected by auth verification against auth-service.
  - Routes scoped to user_id from token claims.
- `apps/frontend/`
  - React + Vite UI with authentication flows (login/signup) and pages for upload, section review, findings/review/analysis workspace, remediation, and report management.
  - Token-based session management with localStorage persistence.
- `scripts/`
  - GDPR ingest/validation and benchmark scripts.
- `infra/prometheus/`, `infra/grafana/`
  - Monitoring scrape config + dashboard provisioning assets.
- `infra/loki/`, `infra/promtail/`
  - Centralized logging configuration and log collection setup.
- `infra/alertmanager/`
  - Alert routing and email notification configuration.
- `.github/workflows/`
  - GitHub Actions CI/CD pipeline for automated testing, linting, and building.
- `data/raw/`, `data/processed/`
  - Input PDFs and processed corpus chunks (`gdpr_chunks.jsonl`).

### 1.2 Runtime composition (`docker-compose.yml`)

Services and default ports:

- Postgres (`5432`)
- Qdrant (`6333`)
- Auth service (`8004`)
- Ingestion service (`8001`)
- Knowledge service (`8002`)
- Orchestration service (`8003`)
- Prometheus (`9090`)
- Grafana (`3001` by default host mapping)
- Alertmanager (`9093`)
- Loki (`3100`)
- Promtail (no external port, internal log collection)
- Frontend (`5173`)

Notable configuration boundaries:

- Auth service manages JWT generation/verification with configurable secret (`AUTH_JWT_SECRET`), algorithm, and expiry.
- Orchestration depends on auth-service for `get_current_user()` verification; all audit/group operations require valid bearer token.
- Orchestration owns LLM provider routing (`MODEL_PROVIDER`, `FALLBACK_MODEL_PROVIDER`) and model names.
- Knowledge service has independent embedding runtime (`EMBEDDING_MODEL`, default `BAAI/bge-small-en-v1.5`).
- Report artifact output path is controlled by `REPORTS_DIR`.
- CORS is configured separately per service.
- Frontend uses environment variables for service base URLs (`VITE_AUTH_URL`, `VITE_ORCHESTRATION_URL`, `VITE_INGESTION_URL`).

### 1.3 Plane separation

- **Authentication plane:** auth-service handles user credentials, JWT generation, and token verification for all protected endpoints.
- **Document content plane:** ingestion produces canonical sections; orchestration consumes them.
- **Legal evidence plane:** knowledge service returns GDPR chunks + scores; orchestration validates and projects citations.
- **Decision/publication plane:** orchestration applies deterministic gates that can downgrade/suppress internal artifacts even after LLM output.

---

## 2) Auth service deep dive (`apps/auth-service`)

### 2.1 API endpoints

- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `GET /auth/verify`

### 2.2 User model and schema (`app/models/user.py`, `app/schemas/user.py`)

`User` ORM model:

- `id` (UUID, primary key)
- `first_name`, `last_name` (String)
- `email` (String, unique, indexed)
- `password_hash` (String, bcrypt-hashed)
- `organization_name` (String, required)
- `created_at` (DateTime)

Request/response schemas:

- `UserRegisterRequest`: first_name, last_name, email, password, organization_name
- `UserLoginRequest`: email, password
- `AuthResponse`: access_token, token_type, user (UserOut)
- `UserOut`: id, first_name, last_name, email, organization_name

### 2.3 Authentication flow

`POST /auth/register`:

1. validate email uniqueness and password strength
2. hash password with bcrypt
3. persist user row
4. return AuthResponse with JWT token and user profile

`POST /auth/login`:

1. lookup user by email
2. verify password against stored hash
3. generate JWT token with claims: `sub` (user_id), `email`, `organization_name`, `iat`, `exp`
4. return AuthResponse

`GET /auth/verify`:

1. extract bearer token from Authorization header
2. decode JWT; on failure return 401
3. return `VerifyResponse` with `valid`, `user_id`, `email`, `organization_name`
4. used as dependency injection point `get_current_user()` in orchestration routes

### 2.4 JWT configuration

Environment variables:

- `AUTH_JWT_SECRET`: HS256 symmetric key (required)
- `AUTH_JWT_ALGORITHM`: default "HS256"
- `AUTH_JWT_EXPIRY_HOURS`: default 24

Token claims structure:

```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "organization_name": "org-name",
  "iat": 1234567890,
  "exp": 1234654290
}
```

### 2.5 Service bootstrap (`app/main.py`)

- structured JSON logging formatter at startup
- CORS middleware with configurable origins
- `Base.metadata.create_all(bind=engine)` on startup
- database connection pool via SQLAlchemy

---

## 3) Ingestion service deep dive (`apps/ingestion-service`)

### 3.1 API endpoints

- `GET /health`
- `POST /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/sections`
- `GET /metrics`

### 3.2 Upload behavior (`app/api/routes.py`)

`POST /documents` accepts two upload modes:

1. multipart upload (`file` field)
2. raw body upload when content type is `application/pdf` or `application/octet-stream`
   - optional filename via `X-Filename`

Validation and rejection behavior:

- 422 if no valid file payload is detected.
- 400 if filename is missing/invalid or not `.pdf`.
- file is written to `UPLOADS_DIR` using basename sanitization (`Path(...).name`).

Instrumentation:

- `documents_upload_total`
- `documents_parsed_total`
- `documents_parse_failed_total`
- `document_parse_duration_seconds`

Failure persistence model:

- on parse exception, persists `Document(status="failed", error_message=...)` and returns HTTP 422.

### 3.3 Parser internals (`app/services/parser.py`)

Core strategy:

- Uses PyMuPDF (`fitz`) to extract page text.
- Cleans lines and removes common noise:
  - page markers,
  - path-like strings,
  - punctuation-only fragments,
  - too-short noise lines.

Heading logic:

- multiple regexes for section headings, subsections, and numeric-only subsection stubs.
- heuristics reject likely sentence lines (to prevent false heading detection).
- handles inline numbered heading clusters and heading/body composites.

Structural normalization:

- attempts split of numbered heading + body.
- detects repeated short lines across many pages as boilerplate headers/footers.
- removes/normalizes boilerplate phrases.
- tracks section page ranges (`page_start`, `page_end`).
- includes fallback section if structure extraction is weak.

### 3.4 Ingestion persistence schema (`app/models/document.py`)

`Document`

- `id`, `title`, `filename`, `status`, `error_message`, `created_at`

`Section`

- `id`, `document_id`, `section_order`, `section_title`, `content`, `page_start`, `page_end`

### 2.5 Service bootstrap (`app/main.py`)

- structured JSON logging formatter at startup.
- CORS middleware from settings.
- `Base.metadata.create_all(bind=engine)` on startup.
- metrics endpoint via `prometheus_client.generate_latest()`.

---

## 4) Knowledge service deep dive (`apps/knowledge-service`)

### 4.1 Startup lifecycle (`app/main.py`)

Startup order:

1. initialize Qdrant client.
2. initialize FastEmbed `TextEmbedding`.
3. ensure collection exists with cosine vector params.
4. load chunks from JSONL file.
5. index if needed (`count == 0` or `FORCE_REINDEX=true`).

Indexing details:

- point IDs are deterministic UUID5 using `chunk_id`.
- vector size probed from embedder at startup.
- payload is stored with chunk metadata (plus `point_id`).

### 4.2 API endpoints

- `GET /health`
- `POST /search`
- `GET /chunks/{chunk_id}`
- `GET /metrics`

`/search` contract:

- input: `query` (min length 2), `k` (`1..20`)
- execution: embed query → `query_points` in Qdrant
- output includes: `chunk_id`, `article_number`, `article_title`, `paragraph_ref`, `subpoint_range`, `content`, `source_pdf`, `score`

`/chunks/{chunk_id}` contract:

- payload-filtered Qdrant scroll lookup by `chunk_id`.
- returns rich chunk payload (chapter/page/subchunk metadata if present).

### 4.3 Metrics

- `retrieval_query_total`
- `retrieval_latency_seconds`
- `retrieval_results_returned_total`
- `chunk_lookup_total`

### 4.4 Service characteristics

- No cross-service DB dependency; knowledge state is vector collection + source JSONL.
- Retrieval is synchronous HTTP call style from orchestration.
- Operational correctness depends on chunk corpus consistency and embedding model alignment.

---

## 5) Orchestration service architecture (`apps/orchestration-service`)

### 5.1 Startup and schema evolution (`app/main.py`)

On startup:

1. `Base.metadata.create_all(...)`
2. additive schema guards for `findings`
3. additive schema guards for `audit_analysis_items`
4. additive schema guards for `evidence_records`
5. attempt `findings.section_id` widening to `VARCHAR(128)`

These guards support upgrade-in-place behavior across partially migrated environments.

### 5.2 Public API surface (`app/api/routes.py`)

- `GET /health`
- `POST /audits` (protected; user_id from token)
- `GET /audits/{audit_id}` (protected; user_id verification)
- `GET /audits/{audit_id}/findings` (protected; user_id-scoped)
- `GET /audits/{audit_id}/analysis` (protected; user_id-scoped)
- `GET /audits/{audit_id}/review` (protected; user_id-scoped)
- `GET /audits/{audit_id}/review/grouped` (protected; user_id-scoped)
- `GET /audits/{audit_id}/final-decision-ledger` (protected; user_id-scoped)
- `GET /audits/{audit_id}/export-contract` (protected; user_id-scoped)
- `POST /audits/{audit_id}/report` (protected; user_id-scoped)
- `GET /audits/{audit_id}/report` (protected; user_id-scoped)
- `GET /audits/{audit_id}/report/download` (protected; user_id-scoped)
- `POST /audits/{audit_id}/remediation` (protected; user_id-scoped)
- `GET /audits/{audit_id}/remediation` (protected; user_id-scoped)
- `GET /audits/{audit_id}/remediation/status` (protected; user_id-scoped)
- `POST /groups` (protected; user_id from token)
- `GET /groups` (protected; user_id-scoped)
- `PATCH /groups/{group_id}` (protected; user_id verification)
- `DELETE /groups/{group_id}` (protected; user_id verification)
- `POST /groups/{group_id}/versions` (protected; user_id verification)
- `GET /metrics`

Query/filter specifics:

- `/analysis` supports filters: `status`, `issue_type`, `artifact_role`, `section_id`, `analysis_stage`, `debug`.
- `/review` and `/review/grouped` support `debug` toggling of ledger/internal suppression visibility.
- `/remediation` returns user_id-scoped remediation items with LLM-generated suggestions.
- All protected endpoints validate `user_id` via bearer token verification with auth-service.

### 5.3 Canonical DB model (`app/models/audit.py`)

#### 5.3.1 `Audit`

- run identity + lifecycle (`status`, `started_at`, `completed_at`)
- user ownership and grouping:
  - `user_id` (UUID, indexed, from JWT claims)
  - `document_group_id` (optional, FK to document_groups)
  - `version_number` (for group versioning)
- provenance fields:
  - `model_provider`, `model_name`, `model_temperature`
  - `prompt_template_version`
  - `embedding_model`
  - `corpus_version`

#### 5.3.2 `Finding`

High-density outcome row with:

- outcome/status/severity/classification
- confidence decomposition fields (`confidence_*`)
- publication controls (`publish_flag`, `artifact_role`, `finding_level`, `publication_state`)
- scope/visibility controls (`missing_from_section`, `missing_from_document`, `source_scope`, `source_scope_confidence`, `assertion_level`, etc.)
- legal narrative fields (`policy_evidence_excerpt`, `legal_requirement`, `gap_reasoning`, `severity_rationale`)
- anchor/evidence metadata (`primary_legal_anchor`, `secondary_legal_anchors`, `document_evidence_refs`, `citation_summary_text`)

#### 5.3.3 `FindingCitation`

- citation linkage to GDPR chunk evidence (`chunk_id`, article fields, excerpt).

#### 5.3.4 `AuditAnalysisItem` + `AnalysisCitation`

- internal pipeline materialization for provisional and diagnostic artifacts.
- includes stage/type/outcome, issue typing, candidate statuses, suppression reasoning, confidence fields, and citation candidates.

#### 5.3.5 `EvidenceRecord`

- canonical evidence index by `evidence_id` with source refs, excerpts, derivation links, and legal metadata.

#### 5.3.6 `Report`

- report row with generation status and stored PDF path.

---

## 6) Full audit lifecycle (`services/audit_runner.py`)

### 6.1 Entry and failure semantics

`POST /audits`:

1. persist pending audit row,
2. run `run_audit(db, audit)` synchronously,
3. on exception: rollback/mark audit failed.

### 6.2 `run_audit` initialization

At execution start:

- audit status set to `running`
- model/corpus metadata stamped from config
- sections fetched via ingestion client
- runtime and counter state initialized

Global pre-loop computations include:

- `_extract_notice_cross_references(...)`
- `_source_scope_qualification(...)`
- `_infer_document_mode(...)`
- `_document_posture_agent(...)`
- `_document_wide_duty_validation(...)`
- `_build_document_obligation_map(...)`
- `_effective_llm_budget(...)`

### 6.3 Per-section processing phases

For each section in order:

1. **Runtime budget guard**
   - hard cap using `MAX_AUDIT_RUNTIME_SECONDS`.
2. **Applicability/auditability filtering**
   - `_is_not_applicable`, `_section_auditability_type`.
3. **Issue spotting**
   - collection mode inference,
   - `_spot_candidate_issues` generation,
   - obligation-first injections and suppressions when doc-wide evidence already satisfies conditions.
4. **Legal fact extraction + qualification**
   - `_extract_legal_facts`, `_legal_qualification_for_issue`.
5. **Retrieval + reranking**
   - mode-aware retrieval query construction,
   - top-k retrieval from knowledge service,
   - reranking and bounded retry under weak relevance signals.
6. **Evidence sufficiency gating**
   - score/obligation-language checks,
   - deterministic fallback to review paths when insufficient.
7. **LLM gate + invocation**
   - call only if budget and runtime conditions permit,
   - deterministic review fallback if rate-limited/exhausted.
8. **LLM output normalization**
   - strict JSON coercion into `LlmFinding`,
   - status normalization and candidate publishability demotion hooks.
9. **Applicability/specialized passes**
   - family-specific checks (transfer/profiling/role ambiguity/special category/etc.).
10. **Citation validation and salvage**
    - retrieved-universe validation,
    - article fit checks and salvage attempts from retrieved pool.
11. **Deterministic override stack**
    - explicit violation patterns,
    - consistency/quality controls,
    - publishability/diagnostic demotions.
12. **Duplicate suppression**
    - signature-based dedupe across sections.
13. **Persistence**
    - write final `Finding` row,
    - write `FindingCitation` rows,
    - optional split-finding generation for combined obligation situations.

### 6.4 Post-loop synthesis and control plane

After section loop:

1. `_add_notice_level_synthesis`
2. `_add_systemic_issue_synthesis`
3. `_build_systemic_support`
4. `_enforce_core_and_specialist_completeness`
5. `_build_final_disposition_map`
6. `_final_publication_validator`
7. `_enforce_review_publish_invariant`
8. `_record_suppression_ledger`
9. `_partner_review_pass`
10. `_upsert_evidence_records`
11. `_state_invariant_validator`
12. `_snapshot_analysis_items`
13. audit terminal state update (`complete` or gate-adjusted state)

### 6.5 Deterministic vs model-driven responsibility split

Deterministic-heavy layers:

- candidate taxonomy baselines,
- legal family/article mapping,
- retrieval sufficiency gates,
- citation fit validation,
- publication hydration/completeness enforcement,
- review/publish invariant enforcement,
- export dataset contracts.

Model-driven layer (bounded):

- textual synthesis/classification proposals inside strict prompt and schema constraints, then post-validated by deterministic controls.

---

## 7) LLM subsystem details (`services/llm.py`)

### 7.1 Prompt contract

`SYSTEM_PROMPT` requires strict JSON output keys including:

- status/severity
- gap/remediation notes
- legal requirement + reasoning
- confidence/assessment fields
- citations

Policy constraints in prompt include:

- allowed status values,
- citation must come from retrieved chunks,
- weak evidence should output `needs review`,
- notice-priority guidance and transfer article guidance.

### 7.2 Prompt construction

`_build_user_prompt(...)` includes:

- section title/content,
- compact retrieval chunk lines with metadata and score,
- optional section guidance text,
- frozen rubric reminders.

### 7.3 Provider routing and fallback

- primary provider path from env (`groq` or `gemini` based on configuration and key presence)
- fallback provider path similarly configured
- 429 retry behavior on both provider adapters
- returns sentinel `__rate_limited__` when all attempts fail specifically by rate limit

### 7.4 Parsing and coercion

- raw response JSON block extraction and repair attempts,
- normalization map for status variants,
- citation coercion validates minimum citation fields,
- output projected into `LlmFinding` schema.

---

## 8) Retrieval and legal fit controls

### 8.1 Retrieval flow in orchestration

- retrieval query built from topic/mode/section context.
- top-k from knowledge service then reranked.
- retries on weak score/overlap paths.

### 8.2 Evidence sufficiency

- requires minimum support strength and obligation language signals.
- when support is insufficient, flow chooses deterministic `needs review` or scoped omission-style fallbacks per duty context.

### 8.3 Citation validation matrix

- citation must map to retrieved chunk universe.
- article parsing and issue-family rules applied.
- disallowed article combinations can trigger demotion.
- salvage logic attempts to recover valid chain from retrieved evidence.

### 8.4 Issue family and normalization behavior

Observed issue families include (non-exhaustive):

- controller identity/contact
- legal basis
- retention
- rights notice
- complaint right
- transfer notice / safeguards
- profiling disclosure
- recipient categories
- purpose specificity
- role ambiguity
- special category conditions
- article 14 source/timing family

Normalization aliases exist in code to bridge legacy naming variants (e.g., rights/retention aliases) into canonical output families.

---

## 9) Publication, review, and ledger projections (`app/api/routes.py`)

### 9.1 `/audits/{id}/findings` (published projection boundary)

Behavior highlights:

- returns 404 if audit missing.
- returns 409 when audit is `review_required`.
- sources rows from canonical dataset function `final_exported_findings`.
- sanitizes internal tokens/markers.
- enforces canonical issue key/label mapping; unmapped rows are downgraded to internal/support states.
- validates evidence linkage and citation projection into public response structures.

### 9.2 `/audits/{id}/analysis`

- returns analysis artifacts with optional filters and stage slicing.
- hides ledger-prefixed rows unless `debug=true`.

### 9.3 `/audits/{id}/review`

- merges findings (publishable + selected blocked/internal) and selected analysis records.
- appends review blocks synthesized from final disposition ledger snapshot.
- debug mode controls suppression of ledger/internal traces.

### 9.4 `/audits/{id}/review/grouped`

Partitions review stream into:

- `publication_blockers`
- `core_duty_resolution`
- `specialist_family_resolution`
- `publishable_findings`
- `internal_unresolved_items`
- `diagnostics`

### 9.5 `/audits/{id}/final-decision-ledger`

- emits canonical issue-key rows with scope metadata,
- status/severity,
- legal anchor set,
- evidence refs,
- visibility flags (`published_visible`, `report_visible`, `export_visible`),
- blocker reason codes.

---

## 10) Export contract and reporting (`services/reports.py`)

### 10.1 Canonical dataset selector

`final_exported_findings(...)` enforces:

- `artifact_role == "publishable_finding"`
- `publication_state == "publishable"`
- exclusion of ledger/system rows

This same canonical dataset underpins published findings and report/export surfaces.

### 10.2 Export contract

`build_export_contract(...)` returns structured export metadata such as:

- report type / schema version,
- dataset source,
- allow/block state + blocker reasons,
- counts by status,
- finding IDs and split sets (document-wide vs section).

### 10.3 Report text and PDF builder

Report generation pipeline:

- loads canonical publishable findings,
- applies user-safe text sanitization (internal token stripping),
- synthesizes narrative/report sections,
- writes PDF using custom lightweight object/stream writer.

PDF engine characteristics:

- explicit page layout/margins,
- wrapped text estimation,
- bullet handling,
- safe character replacement,
- multipage object/xref assembly.

---

## 11) Frontend architecture (`apps/frontend/src`)

### 11.1 Route map (`app/App.tsx`)

- `/login` → user login
- `/signup` → user registration
- `/` → upload (protected)
- `/sections` → section review + audit start (protected)
- `/findings` → findings workspace (protected)
- `/remediation` → remediation plan (protected)
- `/report` → report center (protected)

### 11.2 API layer (`lib/api.ts`)

- auth, ingestion, and orchestration base URLs via env (`VITE_AUTH_URL`, `VITE_INGESTION_URL`, `VITE_ORCHESTRATION_URL`)
- auth operations: register, login, token management in localStorage
- upload performed with XHR for progress events (no token required for upload itself; scoped later)
- wrapper functions for auth verification, all major orchestration endpoints, group management, remediation workflows, and report download URL helper
- bearer token injected automatically on all protected orchestration/auth calls
- 401 responses trigger session clear and redirect to login

### 11.3 Presentation normalization (`lib/presentation.ts`)

Frontend applies aggressive normalization/sanitization to:

- issue labels/keys,
- evidence text rendering,
- status/severity mapping,
- internal token suppression,
- dataset parity checks used by contract/presentation tests.

### 11.3.5 Frontend authentication and state management (`app/state.tsx`)

`AppState` context provides:

- `token: string | null` - JWT access token persisted to localStorage
- `user: AuthUser | null` - User profile (id, email, first_name, last_name, organization_name)
- `signIn(token, user)` - Persist authenticated state to context and storage
- `signOut()` - Clear token and user, redirect to login
- `auditId`, `documentId`, `groupId` selection state
- `authLoading` flag for initial token validation on mount

Protected routes use a `ProtectedApp` wrapper component; the root `App.tsx` checks `token` and `authLoading` state and redirects unauthenticated traffic to `/login` via `<Navigate>`.

### 11.4 UI feature areas

- authentication workflows (`features/auth/`): login, signup, session management
- upload workflow (`features/upload`)
- sections review/start audit (`features/sections`)
- findings/review/analysis views (`features/findings`)
- remediation plan (`features/remediation`)
- report create/status/download (`features/report`)

---

## 11.5) Service-to-service communication and authentication

### 11.5.1 Orchestration ↔ Auth verification

On each protected orchestration endpoint (`/audits`, `/groups`, `/reports`, etc.):

1. Frontend sends `Authorization: Bearer <jwt_token>` header.
2. Orchestration extracts token via `get_current_user()` dependency.
3. Orchestration calls `GET {AUTH_SERVICE_URL}/auth/verify` with bearer token.
4. Auth-service decodes JWT; returns user_id on success or 401 on failure.
5. Orchestration uses returned user_id to scope queries/mutations.
6. All audit/group rows are filtered by `user_id` match before return.

### 11.5.2 Frontend ↔ Auth service

Login/signup workflow:

1. User submits credentials to `POST {AUTH_URL}/auth/login` or `POST {AUTH_URL}/auth/signup`.
2. Auth-service validates, generates JWT, returns token + user profile.
3. Frontend stores token in `localStorage` under key `auth_token`.
4. Frontend calls `getMe()` to populate `AppState.user` context.
5. Protected routes mount and check `token` presence; redirect to login if absent.

### 11.5.3 Orchestration ↔ Ingestion

Orchestration calls ingestion directly (no auth needed; ingestion is internal-only):

- `GET {INGESTION_SERVICE_URL}/documents/{document_id}`
- `GET {INGESTION_SERVICE_URL}/documents/{document_id}/sections`

### 11.5.4 Orchestration ↔ Knowledge

Orchestration calls knowledge service for retrieval:

- `POST {KNOWLEDGE_SERVICE_URL}/search` (no auth; internal-only)
- `GET {KNOWLEDGE_SERVICE_URL}/chunks/{chunk_id}` (no auth; internal-only)

---

## 12) Infrastructure and observability

### 12.1 Metrics endpoints

- all four backend services expose `/metrics`.

### 12.2 Ingestion metrics

- upload count,
- parse success/failure,
- parse duration.

### 12.3 Knowledge metrics

- query count,
- retrieval latency,
- results returned,
- chunk lookups.

### 12.4 Orchestration metrics (selected)

- `retrieval_retry_total`
- `evidence_gate_failure_total`
- `citation_validation_failure_total`
- `llm_inference_latency_seconds`
- `audit_duration_seconds`
- section counters (`audit_sections_total`, `audit_sections_auditable_total`, `audit_sections_filtered_total`)
- pass counters (`issue_spotting_calls_total`, `applicability_calls_total`, `legal_qualification_calls_total`, etc.)
- publication counters (`publishable_findings_total`, `local_findings_published_total`, `systemic_findings_published_total`, `not_assessable_findings_published_total`)

### 12.5 Dashboard stack

- Prometheus scrape config in `infra/prometheus/prometheus.yml`
- Grafana datasource + dashboard provisioning in `infra/grafana/*`

---

## 13) Tests and policy contracts

Repository tests include strong policy-contract style coverage, especially in orchestration:

- dataset consistency/parity checks,
- publication-guard behavior,
- report/export contract invariants,
- route projection safety,
- evidence/ledger consistency assertions,
- backend pipeline invariant tests.

Notable test files include:

- `apps/orchestration-service/tests/test_backend_pipeline_invariants.py`
- `apps/orchestration-service/tests/test_published_dataset_consistency.py`
- `apps/orchestration-service/tests/test_final_exported_findings_contract.py`
- `apps/orchestration-service/tests/test_routes_publication_guards.py`
- plus service-level parser/client/report/llm tests

Ingestion and frontend include targeted parser/upload and presentation contract tests.

---

## 14) Status and publication semantics (observed values)

### 14.1 Audit status values

- `pending`
- `running`
- `complete`
- `failed`
- `review_required`
- `audit_incomplete`

### 14.2 Finding status values

- `compliant`
- `partial`
- `gap`
- `needs review`
- `not applicable`

### 14.3 Publication state values

- `publishable`
- `blocked`
- `internal_only`

### 14.4 Artifact role values (representative)

- `publishable_finding`
- `support_only`
- analysis-oriented candidate roles (e.g., `analysis_candidate`)

---

## 15) Scripts and data pipeline utilities

### 15.1 Data preparation scripts

- `scripts/ingest_gdpr.py` for corpus chunk preparation.
- `scripts/benchmark.py` for benchmark audit runs.
- `scripts/benchmark_regression.py` for regression gate validation.

### 15.2 Corpus assets

- raw PDFs under `data/raw/`
- processed chunk corpus under `data/processed/gdpr_chunks.jsonl`

Operationally, the knowledge service startup behavior assumes this processed corpus is present and readable.

---

## 16) Practical end-to-end chronology (multi-user audit run)

1. User navigates to frontend and registers/logs in via auth-service endpoints.
2. Frontend receives JWT token and user profile; stores token in localStorage and user context.
3. User uploads PDF in frontend.
4. Ingestion stores file, parses sections, persists document + sections.
5. Frontend displays sections and triggers `POST /audits` with bearer token in header.
6. Orchestration extracts token, verifies via auth-service, extracts user_id from JWT claims.
7. Orchestration starts audit, stamps run metadata and user_id ownership.
8. Global scope/mode/posture/obligation precomputation executes.
9. For each section:
   - applicability filtering,
   - issue spotting,
   - legal qualification,
   - retrieval/rerank from knowledge service,
   - evidence sufficiency gate,
   - optional LLM classify,
   - deterministic validation/override,
   - finding + citation persist.
10. Post-loop synthesis/completeness/disposition map execute.
11. Final publication validator and review/publish invariants run.
12. Evidence records + analysis snapshots materialize.
13. Audit enters terminal state.
14. `/findings`, `/review`, and `/review/grouped` endpoints return user_id-scoped results only.
15. Report endpoint generates PDF from canonical publishable dataset (user_id-scoped).
16. User downloads report or views grouped findings per their audit ownership.

---

## 17) Constraints and caveats

1. Purpose-built for GDPR transparency audit workflows; not general legal reasoning.
2. Clean text-extractable PDFs expected; no OCR pipeline for scanned/image docs.
3. LLM output is constrained and heavily post-gated; deterministic controls are primary decision layer.
4. Publication model is intentionally conservative and may suppress borderline findings into internal/review tracks.
5. Operational quality depends on corpus indexing health and external LLM provider availability/limits.

---

## 18) Final conclusion

CompliTrace is best described as a **deterministic compliance pipeline with bounded model assistance**, not as a free-form assistant.

Its architecture combines:

- structured document ingestion,
- retrieval-backed legal evidence,
- constrained model proposal,
- deterministic legal/publication gates,
- explicit review and export contracts,
- strong projection sanitization,
- invariant-oriented tests and observability.

That design choice is visible in every major subsystem: generation is allowed, but publication is earned through deterministic controls.
