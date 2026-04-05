# CompliTrace — GDPR Privacy Policy Pre-Audit Copilot

## Concise Description

| #   | Item                                         | Answer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| --- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **One-sentence concept**                     | A bounded agentic RAG system that reviews a company's internal privacy or data-handling policy section by section against GDPR and produces a traceable pre-audit gap report with exact article citations, severity levels, remediation notes, and programmatically validated citation traceability.                                                                                                                                                                                                                                |
| 2   | **Target user**                              | Junior compliance analyst, IT auditor, or consultant doing a first-pass GDPR review on a company policy document before manual validation or formal audit.                                                                                                                                                                                                                                                                                                                                                                          |
| 3   | **Core workflow**                            | Upload policy PDF → frozen rule-set section detection → agent applies not-applicable pre-check per section → retrieves top-5 GDPR chunks with similarity scores → frozen retry threshold → evidence sufficiency gate → classifies with frozen rubric → validates citations (3 checks) → persists findings with provenance → generates PDF gap report.                                                                                                                                                                               |
| 4   | **Final output**                             | Downloadable PDF gap report: section-level findings, one of five statuses per section (`compliant`, `partial`, `gap`, `needs_review`, `not_applicable`), severity (non-null only for gap/partial), matched GDPR article citations with Qdrant chunk IDs, remediation notes, executive summary with `not_applicable` sections listed separately.                                                                                                                                                                                     |
| 5   | **Why easy to pitch to HR**                  | "Upload your privacy policy, get a GDPR gap report with exact article citations in minutes." Everyone knows GDPR. The output is a professional PDF. The Moroccan company example makes it immediately concrete. No technical explanation needed.                                                                                                                                                                                                                                                                                    |
| 6   | **Why impressive to technical interviewers** | Three justified microservices with meaningful service boundaries; bounded agent loop with frozen decision rules (retry threshold, evidence sufficiency gate, classification rubric); genuine RAG with three-check citation validation; `not_applicable` pre-classification preventing noise findings; audit provenance persisted per run; Prometheus + Grafana observability; rerun stability criterion (≥80%); deliberate scope cuts you can defend.                                                                               |
| 7   | **Why microservices are justified**          | Three clean splits: ingestion (CPU-bound parsing, isolated failure mode, no knowledge of GDPR); knowledge service (different data lifecycle, owns Qdrant vector store, different update cadence); orchestration (workflow state, agent logic, evidence gate, citation validation, findings, reporting). Modular monolith would also have been valid — this split was chosen for independent observability and failure isolation. Report generation merged into orchestration deliberately to avoid a fourth unjustifiable boundary. |
| 8   | **Why AI agent is justified**                | Section content dynamically determines the retrieval query, the retry decision (frozen threshold: top-1 score < 0.45 or <2 keyword matches), the evidence sufficiency evaluation, and the final classification. None of these are predetermined. A fixed pipeline with hardcoded queries would produce wrong or irrelevant citations. The workflow is bounded but the key decisions are genuinely adaptive at runtime.                                                                                                              |
| 9   | **Why RAG is justified**                     | Legal citations are load-bearing. An LLM citing article numbers from parametric memory will hallucinate paragraph references. CompliTrace enforces three programmatic citation checks before any citation is persisted: article number must exist in the retrieved top-k, paragraph ref must match chunk metadata, and a Qdrant chunk ID must be traceable. A wrong legal citation is worse than no citation — it creates false assurance.                                                                                          |
| 10  | **Why NOT replaced by existing software**    | OneTrust, TrustArc, and similar platforms manage control frameworks, workflows, and governance processes — they do not analyze arbitrary uploaded policy documents with transparent per-section GDPR citations and traceable chunk-level retrieval evidence. No commercial tool in this category offers this specific pre-audit citation-grounded document analysis workflow with programmatic citation validation.                                                                                                                 |
| 11  | **Why NOT replaced by one good prompt**      | ChatGPT cannot enforce an evidence gate, cannot programmatically validate citations against retrieved chunks, cannot silently skip administrative sections, cannot produce a persistent structured audit trail across database tables, cannot guarantee coverage of every section, and cannot produce comparable output across repeated runs. One prompt produces unstructured text. This system produces a persistent, provenance-tracked, citation-validated, coverage-guaranteed audit record.                                   |
| 12  | **Data source**                              | GDPR full text from EUR-Lex — free, public, English, structured by article and paragraph, ~250–350 chunks after paragraph-level splitting. Embeddable on CPU in under an hour. Similarity score distribution validated during days 1–2 to calibrate frozen thresholds (0.45 retry, 0.50 gate). Zero sourcing risk.                                                                                                                                                                                                                  |
| 13  | **Model/compute feasibility**                | Groq API (Llama 3.1 8B) or Gemini Flash as primary — no GPU needed. `sentence-transformers/all-MiniLM-L6-v2` for CPU embeddings. Qdrant and PostgreSQL in Docker. Ollama documented as local fallback. Fully runnable on a 16 GB RAM laptop.                                                                                                                                                                                                                                                                                        |
| 14  | **20-day build feasibility**                 | High with strict scope. GDPR corpus ready in 1–2 days. Three services are sequential and independently testable. Frozen rules reduce ambiguity during agent implementation. Report generation is an internal module, not a fourth service. Gold-set document is pre-authored. Timeline is tight but realistic.                                                                                                                                                                                                                      |
| 15  | **Main risks / weaknesses**                  | Section parsing quality on arbitrary PDFs (mitigated by pre-authored demo document); LLM classification inconsistency (mitigated by frozen rubric, low temperature, rerun stability testing on gold set); frozen threshold calibration (validated during days 1–2 against embedding score distribution); agent framing requires precise language under interview pressure.                                                                                                                                                          |
| 16  | **Scope reduction if needed**                | Merge ingestion into orchestration, keep only the knowledge service separate (two services). Alternatively, drop the not-applicable pre-classification and evidence gate to a single simpler conditional. Both still leave a defensible system. The frozen citation validation must be kept regardless — it is the core credibility claim.                                                                                                                                                                                          |
| 17  | **Demo scenario**                            | Upload pre-authored 5-page Employee Data Handling Policy (gold-set document). Show extracted sections including one `not_applicable` (Definitions). Open Data Retention finding: Gap → Article 5(1)(e) retrieved and cited with chunk ID. Show full PDF with frozen report schema. Show Grafana: retrieval latency, audit duration, findings by all five statuses. Total: under 5 minutes.                                                                                                                                          |
| 18  | **Resume impact score**                      | **9/10** — Specific, technical, domain-relevant for Big 4 and consulting, non-generic stack, professional output artifact with traceable provenance, observable system with frozen decision rules, deliberate scope discipline with documented tradeoffs.                                                                                                                                                                                                                                                                           |
| 19  | **Overall strategic score**                  | **8.5/10** — Focused, valuable, pitchable, technically defensible with frozen rules that close the main interview vulnerabilities, feasible in 20 days, strong for every target employer type. Half point deducted for the agent framing requiring precise language under pressure and the need for a perfectly controlled demo environment.                                                                                                                                                                                        |

# CompliTrace — GDPR Privacy Policy Pre-Audit Copilot

## Concise Build Plan

---

## 1. Final Product Name

**CompliTrace** — GDPR Privacy Policy Pre-Audit Copilot

---

## 2. Elevator Pitch

CompliTrace is a bounded agentic RAG system that reviews a company's internal privacy or data-handling policy against GDPR section by section, and produces a traceable pre-audit gap report with exact article citations, severity levels, and remediation notes — with programmatically validated citation traceability — in minutes instead of hours.

---

## 3. Problem Statement

First-pass GDPR review of an internal privacy policy is manual, slow, citation-heavy, and error-prone. A junior analyst must read the full document, locate relevant GDPR articles for each section, compare coverage by hand, and write documented findings. A missed article or wrong citation makes the entire report unreliable. CompliTrace automates and grounds this first-pass review with structured, citation-validated findings ready for analyst validation.

---

## 4. Target User

Junior compliance analyst, junior IT auditor, or junior consultant preparing a pre-audit GDPR gap review on a company's internal privacy or data-handling policy document.

---

## 5. User Pain Point

_"I need to check whether this privacy policy covers the main GDPR requirements before an audit. Manually it takes hours, I have to find every article myself, and I need traceable findings I can defend — not just my own notes."_

---

## 6. Exact Core Workflow

1. User uploads one internal privacy or data-handling policy PDF.
2. System applies frozen section detection rule set (heading check, paragraph fallback, 50-word minimum).
3. User reviews extracted sections before triggering the audit.
4. Agent iterates through sections one at a time:
   - Applies not-applicable pre-check (administrative title + no processing signals → skip retrieval).
   - Infers GDPR topic, formulates retrieval query, calls Knowledge Service (top-5 chunks + scores).
   - Applies frozen retry threshold (top-1 score < 0.45 or <2 keyword matches → reformulate once).
   - Applies evidence sufficiency gate (<2 chunks ≥0.50 or no obligation keyword → `needs_review`).
   - Classifies using frozen rubric (`compliant` / `partial` / `gap` / `needs_review`).
   - Validates citations (3 checks: article number in top-k, paragraph ref match, chunk ID traceable).
   - Persists finding with audit provenance metadata.
5. System generates structured PDF gap report with frozen mandatory schema.

One input. One loop. One output.

---

## 7. Final Output

A **structured pre-audit gap report** containing: document title, audit timestamp, audit provenance (model, embedding model, corpus version), executive summary (counts by all five statuses, `not_applicable` listed separately), per-section findings (status, severity, gap note, remediation note, citations with article number + paragraph ref + Qdrant chunk ID), and report generation metadata. Delivered as web summary + downloadable PDF.

---

## 8. Architecture

```
[React Frontend]
       |
       | HTTP
       v
[Document Ingestion Service : 8001]  →  PostgreSQL (documents, sections + page spans)
       |
       v
[Agent Orchestration Service : 8003] →  PostgreSQL (audits + provenance, findings,
       |                                             finding_citations + chunk_id, reports)
       | HTTP
       v
[Regulatory Knowledge Service : 8002] → Qdrant (GDPR vectors + scores)

[Prometheus] ← /metrics from all 3 services → [Grafana]
```

Three services. One frontend. One relational DB. One vector store. Report generation is an internal module of the Orchestration Service — not a fourth service.

---

## 9. Microservices

**Document Ingestion Service (8001):** PDF upload, text extraction, frozen section detection, page span storage, PostgreSQL persistence. Isolated failure mode (bad PDF must not crash the agent).

**Regulatory Knowledge Service (8002):** GDPR corpus in Qdrant (≤350 chunks), semantic retrieval with similarity scores, citation metadata. Different data lifecycle, storage backend, and update cadence from everything else — the most independently justified service.

**Agent Orchestration Service (8003):** Full audit lifecycle, bounded agent loop (not-applicable check, frozen retry threshold, evidence sufficiency gate, frozen classification rubric, citation validation), finding and provenance persistence, PDF report generation (internal module). A modular monolith would also have been valid — this split was chosen for independent observability and failure isolation.

---

## 10. Endpoints

| Service       | Method | Path                           | Purpose                                    |
| ------------- | ------ | ------------------------------ | ------------------------------------------ |
| Ingestion     | POST   | `/documents`                   | Upload PDF, trigger parsing                |
| Ingestion     | GET    | `/documents/{id}`              | Document status                            |
| Ingestion     | GET    | `/documents/{id}/sections`     | Sections with page spans                   |
| Knowledge     | POST   | `/search`                      | Semantic retrieval → chunks + scores       |
| Knowledge     | GET    | `/chunks/{id}`                 | Full chunk content                         |
| Orchestration | POST   | `/audits`                      | Start audit                                |
| Orchestration | GET    | `/audits/{id}`                 | Audit status + provenance                  |
| Orchestration | GET    | `/audits/{id}/findings`        | Findings with nested citations + chunk IDs |
| Orchestration | POST   | `/audits/{id}/report`          | Trigger PDF generation                     |
| Orchestration | GET    | `/audits/{id}/report`          | Report metadata                            |
| Orchestration | GET    | `/audits/{id}/report/download` | PDF download                               |

---

## 11. Agent Workflow

```
FOR each section in order:

  STEP 0 — not_applicable pre-check
  IF administrative title AND no processing signal keywords:
    → classify not_applicable, null severity, no citations, advance

  STEP 1–3. Infer topic → formulate query → call search_regulation(query, k=5)

  STEP 4 — Frozen retry threshold
  IF top-1 score < 0.45 OR <2 of top-5 match inferred topic keyword:
    → reformulate → call search_regulation once more

  STEP 5 — Evidence sufficiency gate
  IF <2 chunks ≥0.50 OR no chunk contains obligation keyword:
    → classify needs_review, null severity, advance

  STEP 6 — LLM evaluation using frozen rubric
  compliant / partial / gap assigned based on evidence vs. section content

  STEP 7 — Frozen citation validation (3 checks per citation)
  article_number in top-k | paragraph_ref matches metadata | chunk_id non-null
  → reject any citation failing any check

  STEP 8 — Persist finding + citations + audit provenance
```

**Dynamic decisions:** GDPR topic inference, query formulation, retry trigger, evidence sufficiency judgment, status classification, citation selection. All driven by section content at runtime — not predetermined.

**Agent tools:** `search_regulation(query, k)`, `get_chunk(chunk_id)`, `mark_finding(...)`, `next_section()`

---

## 12. RAG Ingestion Plan

**Corpus:** GDPR full text (EUR-Lex, English). 99 articles. Public. Bounded.

**Ingestion:** Download → clean → split by article/paragraph → store metadata (article_number, article_title, paragraph_ref, content, source) → embed with sentence-transformers → load into Qdrant.

**Chunking:** Paragraph-level chunks within each article. 150–300 tokens each. 250–350 total. No cross-article chunks. Full metadata on every chunk.

**Retrieval:** Top-5 semantic retrieval with cosine similarity scores. Metadata filter `source=GDPR`. Scores returned with every chunk and used by frozen retry threshold and evidence gate.

**Citation validation:** Every citation must pass 3 checks: article number present in retrieved top-k, paragraph ref matching chunk metadata (null if unresolvable), Qdrant chunk ID non-null and traceable. Enforced programmatically after LLM parse, before database write.

**Threshold calibration:** Validate that expected score distribution is compatible with 0.45 retry threshold and 0.50 gate during days 1–2 retrieval testing. Adjust if needed (TBD-6).

---

## 13. Data Schema

**`documents`:** id, title, filename, status (`pending`/`parsed`/`failed`), created_at

**`sections`:** id, document_id, section_order, section_title, content, page_start (nullable), page_end (nullable)

**`audits`:** id, document_id, status (`pending`/`running`/`complete`/`failed`), started_at, completed_at, model_provider, model_name, model_temperature, prompt_template_version, embedding_model, corpus_version

**`findings`:** id, audit_id, section_id, status (5 values), severity (null for compliant/needs_review/not_applicable; required for gap/partial), gap_note (null except gap/partial), remediation_note (null except gap/partial)

**`finding_citations`:** id, finding_id, chunk_id (Qdrant point ID — required), article_number, paragraph_ref (nullable), article_title, excerpt

**`reports`:** id, audit_id, status (`pending`/`ready`/`failed`), pdf_path, created_at

---

## 14. Tech Stack

| Component      | Choice                                         | Reason                                                           |
| -------------- | ---------------------------------------------- | ---------------------------------------------------------------- |
| Backend        | Python + FastAPI (all 3 services)              | Async, fast to build, trivial Prometheus integration             |
| Agent          | Custom Python loop (`run_audit()`)             | No LangChain — bounded workflow, fully explainable in interviews |
| LLM            | Groq (Llama 3.1 8B) primary / Gemini Flash alt | No GPU, fast, cheap, structured JSON output                      |
| Embeddings     | `all-MiniLM-L6-v2` (or multilingual)           | CPU-friendly, sufficient for GDPR domain                         |
| Vector store   | Qdrant (Docker)                                | Production-grade, metadata filtering, similarity scores          |
| Database       | PostgreSQL (Docker)                            | Relational audit trail, FK enforcement, UUID keys                |
| Frontend       | React + Vite + Tailwind                        | 4 views, no state management library                             |
| PDF generation | WeasyPrint                                     | HTML-to-PDF, minimal setup                                       |
| Observability  | Prometheus + Grafana + JSON logs               | 8 metrics, 3 Grafana panels, Docker stdout logs                  |
| Deployment     | Docker Compose (7 services)                    | One command starts everything                                    |
| CI/CD          | GitHub Actions                                 | Lint + tests on push, image build on merge                       |

---

## 15. 20-Day Roadmap

**Days 1–2 — Data Foundation**
Download and clean GDPR text. Write ingestion script (paragraph-level chunks, metadata). Embed with sentence-transformers. Load into Qdrant. Validate 10–15 retrieval queries manually. Calibrate frozen thresholds (0.45/0.50) against actual score distribution. Write gold-set demo document (Employee Data Handling Policy, 10 sections, intentional gaps matching Appendix 14.5 of SRS). Define PostgreSQL schema.
_Gate: retrieval returns correct articles. Thresholds validated. Demo document ready._

**Days 3–5 — Regulatory Knowledge Service**
FastAPI service with `POST /search` (returns chunks + scores) and `GET /chunks/{id}`. Connect to Qdrant. Return full citation metadata including similarity scores. 5 unit tests for retrieval correctness. Prometheus: retrieval latency histogram, query counter, retry counter.
_Gate: `/search` returns ranked chunks with scores for any GDPR topic._

**Days 6–8 — Document Ingestion Service**
FastAPI service with upload, status, and sections endpoints. Text extraction via `pdfplumber`/`pymupdf`. Frozen section detection: heading rule (2-condition check), paragraph fallback (>200 words), 50-word minimum merge, page span storage where available. Prometheus: documents processed, parse failures.
_Gate: upload demo document → correctly parsed sections returned via API._

**Days 9–12 — Agent Orchestration Service**
`AuditAgent` class with `run_audit(document_id)`. Full bounded loop: not-applicable pre-check → topic inference → retrieval → frozen retry threshold → evidence sufficiency gate → frozen classification rubric → LLM call → JSON parse → 3-check citation validation → `mark_finding()`. Audit provenance persisted on record creation. HTTP connection to Knowledge Service. Test on gold-set document: verify all 10 expected findings match. Prometheus: audit duration, findings by status, evidence gate failures, citation validation failures.
_Gate: audit on gold-set document produces all 10 expected findings with correct statuses._

**Days 13–14 — Report Generation**
Report module inside Orchestration Service. HTML template: provenance header, executive summary cards (all 5 statuses), per-section finding blocks with citations. WeasyPrint PDF export. Frozen report schema enforced: all mandatory fields present. Expose `POST /audits/{id}/report` and `GET /audits/{id}/report/download`.
_Gate: PDF generated from completed audit contains all frozen schema fields._

**Days 15–16 — Frontend**
4 pages: Upload, Sections Review (with page spans if available), Findings (table with 5-status badges; `not_applicable` distinct badge; detail panel: section text + gap note + remediation note + GDPR evidence + chunk ID), Report (summary cards with `not_applicable` separate, PDF download). Polling for audit status.
_Gate: full workflow completable browser end-to-end._

**Days 17–18 — Docker Compose + Observability**
`docker-compose.yml`: ingestion (8001), knowledge (8002), orchestration (8003), postgres, qdrant, prometheus, grafana. Health checks and `depends_on`. Prometheus scrape config (15s interval). Grafana dashboard: 3 panels (retrieval latency histogram, audit duration gauge, findings by status bar chart — all 5 values). JSON logging on all services.
_Gate: `docker-compose up` → full stack live → Grafana shows live data after one audit._

**Day 19 — CI/CD + Testing**
GitHub Actions: lint (`ruff`), unit tests on push; Docker image build on merge. Smoke tests: upload demo document, trigger audit, verify finding count and statuses, verify PDF download. Rerun stability check: run gold-set document 3 times, verify ≥80% status agreement.
_Gate: pipeline green. Rerun stability criterion passed._

**Day 20 — Demo Polish**
Run full demo 3 times, fix awkward moments. Seed demo database with pre-run audit. Write README with architecture diagram and setup instructions. Record 3-minute walkthrough video if needed.

---

## 16. MVP Scope

Must work: single PDF upload → frozen section detection → not-applicable pre-classification → agent loop (frozen retry threshold + evidence gate + frozen rubric) → 3-check citation validation → audit provenance persistence → findings with all 5 statuses → PDF report with frozen schema → 4-page frontend → Docker Compose → Prometheus (8 metrics) + Grafana (3 panels) → GitHub Actions pipeline. Gold-set document with known expected findings.

---

## 17. Non-MVP Cuts

Do not build: multi-standard support, regulation upload UI, authentication, multi-user, admin panel, WebSockets/streaming, document version comparison, compliance score percentage, notifications, analytics beyond 3 Grafana panels, OCR for scanned PDFs, chatbot interface, regulation update tracking, multi-tenant architecture, export formats other than PDF, human override / analyst disposition fields, document-level synthesis pass.

---

## 18. What Can Be Simplified Safely

**Safe:** pre-authored gold-set demo document only (never unknown PDFs in demo), WeasyPrint HTML-to-PDF, polling for audit status, one retry max, 3 Grafana panels only, seed demo database before presentations, null page spans when parser doesn't provide them.

**Must be real:** PDF text extraction, semantic retrieval from Qdrant against actual GDPR chunks, frozen threshold and gate logic, LLM-driven per-section classification, 3-check citation validation, finding persistence with chunk IDs, audit provenance fields, report generation from real audit data, Prometheus metrics scraped and displayed.

---

## 19. Demo Script

**Step 1 (30s):** Pitch — "CompliTrace reviews a privacy policy against GDPR and produces a gap report with exact article citations validated against the actual GDPR text — not from model memory."

**Step 2 (60s):** Upload demo policy. Show sections page including `not_applicable` Definitions section. Say: "Administrative sections are excluded from gap counts automatically."

**Step 3 (90s — the key moment):** Open Data Retention finding. Show split panel: section text left; Gap / High / gap note / remediation note / Article 5(1)(e) retrieved evidence right. Say: "This citation passed three programmatic checks — article number, paragraph ref, and Qdrant chunk ID — before it was persisted. It cannot be a hallucinated reference."

**Step 4 (45s):** Report page — summary cards (all 5 statuses, `not_applicable` separate). Download PDF, show frozen schema structure.

**Step 5 (30s — technical):** Grafana — 3 panels. Say: "Evidence gate failures and citation validation rejections are tracked as separate metrics."

**Step 6 (technical only):** Architecture diagram — 3 services, frozen rules, why a modular monolith would also have been valid.

---

## 20. Interview Defense Points

**Why microservices:** Three genuinely different concerns — ingestion (CPU-bound, isolated failure), knowledge (different data lifecycle, owns Qdrant, different update cadence), orchestration (workflow state, agent logic, provenance, reporting). A modular monolith would also have been valid. Report generation deliberately merged into orchestration to avoid a fourth unjustifiable boundary.

**Why agent:** Query formulation, retry trigger (frozen threshold), evidence sufficiency evaluation, and classification are all determined dynamically from section content at runtime. A fixed pipeline cannot do this. The workflow is bounded, but the decisions are genuinely adaptive.

**Why RAG:** Legal citations are load-bearing. An LLM citing article numbers from memory will hallucinate paragraph references. CompliTrace enforces 3 programmatic citation checks. A wrong citation in a compliance report creates false assurance — worse than no citation.

**Why not one prompt:** Cannot produce persistent findings in a database, cannot enforce an evidence gate, cannot guarantee section coverage, cannot validate citations programmatically, cannot produce comparable output across repeated runs, cannot persist audit provenance.

**Why not existing software:** OneTrust-class tools manage control frameworks and governance workflows — they do not analyze arbitrary uploaded policy documents with per-section citation-grounded retrieval evidence.

**Tradeoffs:** GDPR only, clean PDFs only, one retry max, no auth, no WebSockets, pre-authored demo document, polling, 3 Grafana panels. Every cut was deliberate and documented.

---

## 21. Final Resume Bullet

**Built CompliTrace**, a bounded agentic RAG system that audits internal privacy policy documents against GDPR using a frozen classification rubric, programmatic citation validation, and an evidence sufficiency gate — implemented as three microservices using FastAPI, Qdrant, and PostgreSQL, with Docker Compose deployment, Prometheus observability, and a gold-set rerun stability criterion.
