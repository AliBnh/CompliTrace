# Software Requirements Specification

**CompliTrace**

**GDPR Privacy Policy Pre-Audit Copilot**

Version 2.0

Status: Final

May 12, 2026

---

**CompliTrace SRS**

## Contents

1. Introduction
   - 1.1 Purpose
   - 1.2 Scope
   - 1.3 Stakeholders & Intended Audience
   - 1.4 Definitions, Acronyms, Abbreviations
   - 1.5 References
2. Product Overview
   - 2.1 Product Perspective
   - 2.2 Document Scope and Real-World Usage Context
   - 2.3 Problem Statement
   - 2.4 Solution Overview
   - 2.5 Rationale for a Dedicated System vs. General-Purpose LLM Chat
   - 2.6 Objectives / Goals
   - 2.7 Users & Roles
   - 2.8 Assumptions & Dependencies
   - 2.9 Constraints
3. System Features (High-Level)
4. AI System Requirements
   - 4.1 AI System Overview
   - 4.2 AI Functional Capabilities
   - 4.3 Agent Behavior & Workflow
   - 4.4 RAG Requirements
   - 4.5 Prompting & Context Management
   - 4.6 AI Non-Functional Requirements
   - 4.7 AI Observability & Evaluation
   - 4.8 AI Failure Handling
5. Functional Requirements
   - 5.1 Authentication & User Management
   - 5.2 Document Upload & Ingestion
   - 5.3 GDPR Audit Execution
   - 5.4 Findings Display
   - 5.5 Remediation Planning
   - 5.6 Report Generation
   - 5.7 Document Groups & Versioning
   - 5.8 Observability & Operations
6. Non-Functional Requirements
   - 6.1 Performance
   - 6.2 Security
   - 6.3 Usability
   - 6.4 Reliability & Availability
   - 6.5 Scalability
   - 6.6 Maintainability & Observability
7. External Interfaces
   - 7.1 User Interface
   - 7.2 APIs & External Services
   - 7.3 System Interfaces (Service-to-Service)
8. Data Requirements
   - 8.1 Data Model Overview
   - 8.2 Data Validation Rules
   - 8.3 Data Storage & Persistence
   - 8.4 Data Lifecycle
9. System Architecture & Service Model
   - 9.1 Architectural Style
   - 9.2 Service Overview
   - 9.3 Inter-Service Communication
   - 9.4 API Contracts & Boundaries
   - 9.5 Data Ownership & Isolation
   - 9.6 Scalability Strategy
   - 9.7 Fault Tolerance & Failure Scenarios
   - 9.8 Deployment & Infrastructure Constraints
   - 9.9 Observability & Monitoring
10. Acceptance Criteria (System-Level)
11. Traceability
12. Risks, Constraints & Limitations
    - 12.1 Technical Risks
    - 12.2 AI-Specific Risks
    - 12.3 Operational Risks
    - 12.4 Known Limitations
13. Versioning & Change Log
14. Appendices
    - 14.1 Diagrams
    - 14.2 Sample Data
    - 14.3 Glossary
    - 14.4 TBD List (Resolved)
    - 14.5 Gold-Set Evaluation Reference

---

## 1 Introduction

### 1.1 Purpose

This Software Requirements Specification (SRS) document defines the functional requirements, non-functional requirements, AI system behavior, architecture constraints, and acceptance criteria for CompliTrace, a GDPR Privacy Policy Pre-Audit Copilot.  
The document is intended to serve as the primary reference for the design, implementation, testing, and validation of CompliTrace. It is written in accordance with the IEEE 830 and ISO/IEC/IEEE 29148 standards for software requirements documentation.  
The system is scoped to a single regulatory standard (GDPR) and a single document-analysis workflow. Requirements in this document reflect that scope deliberately. Features outside the system boundary are explicitly excluded.

### 1.2 Scope

**System Name**

CompliTrace GDPR Privacy Policy Pre-Audit Copilot.

**System Architecture**

The system comprises four backend services and a web frontend:

• `auth-service` — user registration, login, JWT generation and verification.  
• `ingestion-service` — PDF upload, text extraction, section detection and persistence.  
• `knowledge-service` — GDPR corpus embedding and semantic retrieval over Qdrant vectors.  
• `orchestration-service` — audit orchestration, findings generation, compliance scoring, remediation planning, and PDF report generation.  
• `frontend` — React/TypeScript single-page application for all user interactions.

**In-Scope**

• User registration, login, and JWT-based authentication.  
• Multi-user support with per-user audit isolation and document grouping.  
• Upload and ingestion of privacy or data-handling policy documents (PDF).  
• Automatic extraction and sectioning of document content.  
• Section-by-section GDPR gap analysis driven by a bounded AI agent.  
• Semantic retrieval of GDPR article chunks from a pre-indexed regulatory corpus (Qdrant vector store) using the BAAI/bge-small-en-v1.5 embedding model.  
• Per-section finding generation: status, severity, gap note, remediation note, and article citations.  
• Compliance scoring: each completed audit produces a `compliance_score` reflecting the overall compliance posture of the audited document.  
• Remediation planning: LLM-generated suggested clause text, prioritization by severity, per-item status tracking, and progress queries.  
• Document grouping and version control for organizing multiple audits across revisions.  
• Persistence of audit results and user data in a relational database.  
• Generation and download of a structured PDF gap report.  
• A web frontend covering: authentication, document upload, sections review, findings view, remediation workspace, and report management.  
• System observability: structured logging via Loki and Promtail, Prometheus metrics, Grafana dashboards, and Alertmanager for alert routing.  
• Containerised deployment via Docker Compose.  
• A CI/CD pipeline via GitHub Actions.

**Out-of-Scope**

• Support for regulatory standards other than GDPR (e.g., ISO 27001, CCPA, Moroccan Law 09-08).  
• Admin panel or regulation management UI.  
• Real-time streaming agent output (WebSockets).  
• OCR support for scanned or image-based PDFs.  
• Chatbot or conversational Q&A interface.  
• True multi-tenant architecture (shared infrastructure per org).  
• Export formats other than PDF.  
• Role-based access control (RBAC) beyond per-user isolation.

### 1.3 Stakeholders & Intended Audience

| Stakeholder                 | Role                                                        | Interest in this Document                             |
| --------------------------- | ----------------------------------------------------------- | ----------------------------------------------------- |
| End User (Primary)          | Junior compliance analyst, IT auditor, or junior consultant | System capabilities, auth workflow, audit outputs     |
| End User (Secondary)        | Compliance manager, policy owner                            | Multi-audit tracking, remediation planning            |
| Developer                   | System builder / maintainer                                 | Full technical reference for implementation           |
| Technical Interviewer       | Reviewer of architectural and AI design decisions           | Architecture, auth flow, and trade-off justifications |
| HR / Non-Technical Reviewer | Evaluates project value and demo quality                    | Product overview, goals, and user workflows           |
| Future Contributor          | Potential maintainer or extension developer                 | Requirements baseline and backlog                     |

### 1.4 Definitions, Acronyms, Abbreviations

| Term                 | Definition                                                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| GDPR                 | General Data Protection Regulation (EU) 2016/679                                                                                                       |
| RAG                  | Retrieval-Augmented Generation — a technique where relevant documents are retrieved from a corpus and injected into an LLM prompt to ground the response |
| Agent                | A software component that selects from a bounded set of actions at runtime based on the current section content and retrieved evidence                 |
| Bounded Agent        | An agent whose decision space and tool access are deliberately constrained to a well-defined workflow                                                  |
| LLM                  | Large Language Model                                                                                                                                   |
| Vector Store         | A database optimised for storing and querying high-dimensional embedding vectors (Qdrant in this system)                                               |
| Embedding            | A numerical vector representation of text, used for semantic similarity search                                                                         |
| Gap Finding          | A documented instance where a policy section fails to meet a GDPR requirement                                                                          |
| Citation             | A reference to a specific GDPR article, paragraph, and excerpt retrieved from the corpus                                                               |
| Section              | A logical subdivision of an uploaded policy document, identified by heading or paragraph structure                                                     |
| Audit                | A single end-to-end execution of the gap analysis workflow on one document                                                                             |
| Compliance Score     | A numeric score (0–100) computed per audit reflecting the ratio of satisfied duties to applicable duties                                               |
| Obligation Taxonomy  | The canonical 19-entry dictionary defining all tracked GDPR obligations, their families, articles, and anchors                                         |
| SRS                  | Software Requirements Specification                                                                                                                    |
| CI/CD                | Continuous Integration / Continuous Deployment                                                                                                         |
| EUR-Lex              | Official EU law publication portal (source of GDPR text)                                                                                               |
| PDF                  | Portable Document Format                                                                                                                               |
| API                  | Application Programming Interface                                                                                                                      |
| REST                 | Representational State Transfer                                                                                                                        |
| UUID                 | Universally Unique Identifier                                                                                                                          |
| Processing Signal    | A keyword indicating personal data processing activity; defined in Section 4.2                                                                         |
| Evidence Sufficiency | A condition on retrieved chunks that must be met before a substantive compliance classification is assigned; defined in Section 4.3                    |

### 1.5 References

• IEEE Std 830-1998 — IEEE Recommended Practice for Software Requirements Specifications.  
• ISO/IEC/IEEE 29148:2018 — Systems and software engineering — Life cycle processes — Requirements engineering.  
• Regulation (EU) 2016/679 (GDPR) — Official text via EUR-Lex: https://eur-lex.europa.eu/eli/reg/2016/679/oj  
• FastAPI Documentation: https://fastapi.tiangolo.com  
• Qdrant Documentation: https://qdrant.tech/documentation  
• fastembed Documentation: https://qdrant.github.io/fastembed  
• Prometheus Documentation: https://prometheus.io/docs  
• Grafana Documentation: https://grafana.com/docs

## 2 Product Overview

### 2.1 Product Perspective

CompliTrace is a standalone, self-contained web application with a microservice backend. It does not integrate with or extend any existing compliance management platform. It operates as an independent document analysis tool that augments the manual first-pass GDPR review process performed by compliance analysts.  
The system sits at the intersection of three technology domains: document processing, retrieval-augmented generation, and structured audit reporting. It is not a workflow management tool, a control framework, or a data mapping solution. It is a narrow, citation-grounded document analysis copilot for first-pass GDPR policy review.

### 2.2 Document Scope and Real-World Usage Context

CompliTrace is designed to process a specific subset of privacy and compliance documents: internal company privacy or data-handling policy or procedure documents that describe how the organization handles personal data in practice.

**What documents exist in real organizations?**

Organizations that process personal data often maintain several different kinds of documentation:

1. Internal policy/procedure documents — explain how the organization handles personal data internally (e.g., Employee Data Handling Policy, Data Retention Policy, Data Subject Rights Handling Procedure).
2. Privacy notices — notices provided to individuals whose data is collected.
3. Controller-processor contracts / DPAs — client-specific or vendor-specific legal documents.
4. Records of processing activities and related internal documentation.
5. DPIAs and risk assessments.

**Which document type does CompliTrace process?**

CompliTrace processes internal policy/procedure documents and privacy notices in clean PDF form.

**Which document types are out of scope?**

The system does not process: client-specific contracts or DPAs, DPIAs, records of processing spreadsheets, vendor questionnaires, scanned or image-based PDFs, or multi-document compliance programs.

**Why is CompliTrace useful if these documents are not reviewed every day?**

CompliTrace is a repeatable pre-audit review tool used when a policy is first drafted, revised, when an audit is approaching, when a client requests stronger privacy documentation, or when a consultant reviews multiple client documents. Its value increases across multiple documents, versions, or consulting engagements.

**Illustrative real-world example (Moroccan company)**

Consider a Moroccan HR software company preparing for EU-facing client audits.

1. The company maintains an internal Employee Data Handling Policy.
2. Before a client due-diligence review, a junior analyst uploads the policy to CompliTrace.
3. CompliTrace splits the policy into sections such as: Data Retention, Data Subject Rights, Vendor Sharing, and Security Measures.
4. The system evaluates each section against the 19-obligation GDPR taxonomy and produces findings such as: gap in retention periods, partial coverage of data subject rights, and vague processor obligations.
5. The analyst reviews the structured report with compliance score and remediation suggestions.
6. The analyst copies suggested clause text into the policy draft and re-audits the updated version.

### 2.3 Problem Statement

Performing a first-pass GDPR compliance review of a company's privacy or data-handling policy is a manual, time-consuming, and error-prone process. A junior analyst must:

1. Read the policy document in full.
2. Identify which GDPR articles apply to each section.
3. Compare the section's content against those articles.
4. Document findings with citations and remediation notes.

This process typically takes several hours per document, requires familiarity with all 99 GDPR articles, and produces findings whose quality depends heavily on the analyst's experience.

### 2.4 Solution Overview

CompliTrace automates the first-pass review by:

• Parsing the uploaded policy document into logical sections.  
• Running a bounded AI agent that evaluates each section against a pre-indexed GDPR corpus using semantic retrieval.  
• Generating per-section findings with exact article citations sourced from retrieved text, not from LLM memory.  
• Computing a compliance score per audit reflecting the overall document posture.  
• Producing remediation plans with suggested clause text, severity-based prioritization, and status tracking.  
• Producing a structured, downloadable PDF gap report suitable for analyst review.

The system is designed to support analyst review, not to provide legally conclusive compliance determinations.

### 2.5 Rationale for a Dedicated System vs. General-Purpose LLM Chat

A general-purpose LLM interface can assist with policy review tasks for one-off or ad hoc analysis. CompliTrace is justified by turning that analysis into a repeatable, structured, inspectable, and persistent review workflow.

The additional value over a general chat workflow:

1. System-enforced workflow — the analysis sequence is enforced by the application, not by prompt discipline.
2. Persistent application records — findings, citations, and reports are stored as application-level records, not conversation content.
3. Section-level traceability by design — each finding is linked to its originating section and to the retrieved GDPR evidence.
4. Citation grounding and validation as a system rule — citations are validated against retrieved chunks; the constraint is enforced programmatically.
5. Standardized output artifact — the same report structure is produced each time without depending on prompt quality.
6. Operational visibility — metrics, logs, and lifecycle state are exposed through the observability stack.
7. Suitability for repeated internal or consulting use — value increases when the task is performed repeatedly across documents, versions, or engagements.

### 2.6 Objectives / Goals

1. Speed: Reduce first-pass GDPR policy review time from hours to minutes.
2. Traceability: Every finding must cite the exact GDPR article and paragraph from which the assessment was derived.
3. Correctness grounding: Minimise hallucinated article citations by enforcing retrieval-grounded citation generation and output validation.
4. Structured output: Produce a professional, structured pre-audit gap report with per-section status, severity, and remediation notes.
5. Compliance scoring: Compute a per-audit compliance score that summarises the document's overall GDPR posture.
6. Observability: All system operations are logged and metriced so that retrieval and agent behavior can be monitored and debugged.
7. Deployability: The entire system runs with a single `docker-compose up` command on a standard developer laptop.

### 2.7 Users & Roles

| User Role            | Description                                          | Primary Actions                                                                                                                                      |
| -------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Analyst              | Junior compliance analyst, IT auditor, or consultant | Register/login, upload documents, review sections, trigger audit, inspect findings, view remediation, download PDF report, organize audits in groups |
| Compliance Manager   | Senior compliance professional or policy owner       | Access team member audit results, track remediation progress, manage document groups and versions                                                    |
| System Administrator | Developer / deployer of the system                   | Deploy via Docker Compose, monitor Grafana dashboard, manage auth secrets, re-index GDPR corpus                                                      |

**Authentication & Authorization**

• Users register with email, password, first name, last name, and organization name.  
• System generates JWT tokens (HS256, 24-hour expiry) on successful login.  
• All protected endpoints verify bearer token via auth service and scope results by user_id.  
• Each user can only view/modify their own audits, documents, and groups.  
• No role-based access control (RBAC) beyond per-user data isolation.

### 2.8 Assumptions & Dependencies

**Assumptions**

• The uploaded document is a clean, text-extractable PDF. Scanned or image-based PDFs are not supported.  
• The GDPR corpus (EUR-Lex English text) is pre-indexed into Qdrant at system setup time and does not require runtime updates.  
• An active internet connection or API key is available for the LLM inference service (Groq or Gemini Flash).  
• The system is deployed in a trusted environment with JWT secrets properly managed (AUTH_JWT_SECRET set via env).  
• Each user has a valid email address for registration and login.  
• PostgreSQL databases are provisioned on startup via init scripts.

**Dependencies**

• Auth service (FastAPI, PostgreSQL) for user registration, login, JWT generation/verification.  
• Groq API / Gemini Flash API — external LLM inference endpoint.  
• EUR-Lex — source of the authoritative GDPR text corpus.  
• Qdrant — vector database for embedding storage and retrieval.  
• PostgreSQL — relational database for structured data persistence.  
• Docker & Docker Compose — container runtime for all services.  
• fastembed — lightweight embedding library using BAAI/bge-small-en-v1.5 for corpus and query encoding.  
• python-jose — JWT encoding and decoding.  
• passlib with bcrypt — password hashing.  
• PyMuPDF (fitz) — PDF text extraction.  
• Loki & Promtail — centralized log aggregation.  
• Prometheus & Grafana — metrics collection and visualization.  
• Alertmanager — alert routing and notification.

### 2.9 Constraints

• Compute constraint: The system must be fully operable on a laptop with 16 GB RAM and no dedicated GPU.  
• Scope constraint: The system supports exactly one regulatory standard (GDPR) and one document type (clean text PDF).  
• Model constraint: The system must not depend on frontier models (GPT-4-class). It must be feasible on Groq-hosted models, Gemini Flash, or an equivalent.  
• Cost constraint: LLM inference costs must remain negligible for typical usage (10–15 sections per audit).  
• Data constraint: The GDPR corpus must remain under 350 chunks to ensure fast embedding and retrieval on the target hardware.  
• Embedding constraint: The embedding model is fixed to BAAI/bge-small-en-v1.5 via fastembed for deterministic retrieval behavior.


## 3 System Features (High-Level)

**Feature 1 User Registration and Authentication**

Description: Users register with email/password and log in to the system. The auth-service is a dedicated microservice running on port 8004 with its own `auth_db` PostgreSQL database. It issues JWT tokens for session management and enforces per-user data isolation on all protected operations.
Actors: Analyst.
High-Level Flow:

1. New user navigates to signup page and enters: first name, last name, email, password, organization name.
2. Frontend validates input (email format, all fields required).
3. Frontend calls auth-service `POST /auth/register` endpoint.
4. Auth-service hashes password with bcrypt, stores user record in `auth_db`, generates JWT token.
5. Auth-service returns `AuthResponse` containing `access_token` and user profile to frontend.
6. Frontend stores token in localStorage under key `auth_token` and redirects to upload page.
7. Existing users log in with email/password via `POST /auth/login`; auth-service verifies credentials and issues JWT.
8. Token expiry: 24 hours; users must re-login after expiry.
9. All protected orchestration endpoints verify bearer token by calling auth-service `GET /auth/verify`.
10. Invalid/expired tokens trigger 401 response; frontend clears session and redirects to login.

**Token Claims:**

```json
{
  "sub": "user-uuid",
  "email": "user@example.com",
  "organization_name": "Org Name",
  "iat": timestamp,
  "exp": timestamp + 24_hours
}
```

**Feature 2 Document Grouping and Version Control**

Description: Users can organize multiple audits into named groups and track versions within groups.
Actors: Analyst.
High-Level Flow:

1. Analyst creates a new group via `POST /groups` with name.
2. System creates document_groups row with user_id, name, created_at, updated_at.
3. Analyst uploads document and triggers audit; can specify group_id in audit creation.
4. Each audit in a group receives an auto-incremented version_number.
5. Analyst can view all groups (`GET /groups`), rename (`PATCH /groups/{id}`), and delete (`DELETE /groups/{id}`).
6. Deleting a group unlinks audits (sets document_group_id to null) but does not delete audits.
7. Frontend sidebar displays groups with their versions and compliance scores.

**Feature 3 Document Upload and Ingestion**

Description: The user uploads a PDF privacy policy document. The system extracts the text, detects logical section boundaries using regex-based heading detection, and persists the document and its sections.
Actors: Analyst.
High-Level Flow:

1. Analyst navigates to upload page (requires valid JWT token).
2. Analyst selects PDF file (optionally specifies target group).
3. Frontend calls ingestion service `POST /documents` with file upload.
4. Ingestion service receives the file, extracts text page-by-page using PyMuPDF (fitz).
5. Service detects section boundaries using the regex-based heading detection rule set.
6. Document metadata and sections are persisted to PostgreSQL; document status set to `parsed`.
7. Frontend navigates to sections review page.

**Section Detection Rule Set:**

- `HEADING_RE`: Matches title-case or uppercase lines (2-100 characters).
- `SECTION_NUM_RE`: Matches numbered section patterns (e.g., 1., 1.1, 1.1.2).
- `SUBSECTION_HEADING_RE`: Matches multi-level numbered headings with capitalized titles.
- Boilerplate detection: Lines repeated on >50% of pages are classified as headers/footers and excluded.
- Subsection grouping: Subsections (1.1, 1.2) are grouped under their parent heading (1.) to avoid over-fragmentation.
- Noise line filtering: Page numbers, file paths, punctuation-only lines, and short non-informative lines are removed.
- Fallback: If no headings are detected, the entire document becomes a single "Document Body" section.
- Page span storage: `page_start` and `page_end` are stored as nullable integers per section.

**Feature 4 Sections Review**

Description: Before triggering the audit, the user reviews the extracted sections.
Actors: Analyst.
High-Level Flow:

1. Analyst navigates to the Sections Review page.
2. Frontend fetches sections from ingestion service (`GET /documents/{id}/sections`).
3. Page displays: section count, average characters per section, sections with page references.
4. Each section shown as a card with title, page range, and full content.
5. Analyst confirms sectioning and clicks "Start Audit".

**Feature 5 GDPR Gap Audit**

Description: The core feature. A bounded AI agent evaluates each section against a 19-obligation GDPR taxonomy through 4 sequential deterministic gates, with LLM assistance bounded by call budgets and runtime limits. After per-section processing, post-loop synthesis generates systemic findings and computes a compliance score.
Actors: Analyst (trigger), AI Agent (execution).
High-Level Flow:

1. Analyst triggers audit via `POST /audits` with document_id and optional group_id.
2. Orchestration service verifies JWT via auth-service, creates audit record (status=pending).
3. Orchestration fetches sections from ingestion service.
4. Audit status set to `running`; model/corpus metadata stamped.
5. Document-level pre-computation: cross-reference extraction, source scope qualification, document mode inference (privacy_notice vs internal_policy), duty validation, obligation map construction.
6. For each section in order:
   - Applicability filtering (admin/meta sections skipped).
   - Issue spotting from 19-obligation taxonomy (max 6 candidates per section).
   - Collection mode inference (direct/indirect/mixed).
   - Legal qualification per issue (primary article, secondary articles, priority bucket).
   - Retrieval query construction and knowledge service search (top-5, cosine similarity).
   - Reranking via `_rerank_chunks_for_mode()`.
   - **Gate 1 (Applicability)**: Does the duty apply given collection mode and document type?
   - **Gate 2 (Sufficiency)**: ≥2 chunks with score ≥0.50 AND obligation keywords present?
   - LLM classification (if budget permits): structured JSON output with status, severity, citations.
   - **Gate 3 (Citations)**: chunk_id traceable? Article compatible with issue family? No contradictions?
   - Deterministic overrides: severity normalization, confidence scoring.
   - **Gate 4 (Publication)**: Invariants satisfied? No internal markers in user-facing text?
   - Finding + FindingCitation rows persisted.
7. Post-loop synthesis:
   - Systemic issue detection (document-wide gaps across multiple sections).
   - Specialist family gap detection (transfer, profiling, Article 14, etc.).
   - Final disposition map construction.
   - Publication validation and review/publish invariant enforcement.
   - Evidence record and analysis item snapshots.
   - Compliance score computation: `round(satisfied_duties / applicable_duties * 100)`.
8. Audit status set to `complete` (or `review_required` / `audit_incomplete` if gates flag issues).

**Feature 6 Findings Review**

Description: The analyst browses findings with compliance score, document-wide vs section-level separation, and a compliance checklist for fully compliant documents.
Actors: Analyst.
High-Level Flow:

1. Analyst navigates to Findings page.
2. Compliance score displayed prominently with color coding.
3. Status counts grid: Compliant, Partially compliant, Non-compliant, Not applicable, Total.
4. Document-wide findings (systemic issues) shown in a separate section.
5. Section findings shown in a table with columns: Section, Issues, Status, Severity.
6. Clicking a row opens a detail panel showing: issue label, why it matters, recommended action, legal anchors, evidence excerpt, citations.
7. For fully compliant documents (score=100%), a GDPR obligation checklist is displayed instead.
8. Frontend polls audit status every 3.5 seconds while audit is running.

**Feature 7 Remediation Planning**

Description: LLM-generated suggested clause text for each non-compliant finding, with severity-based prioritization and score impact estimation.
Actors: Analyst.
High-Level Flow:

1. After audit completion with score < 100%, remediation items are created automatically.
2. Each item includes: issue_key, issue_label, severity, score_impact_points, order_index.
3. Analyst navigates to Remediation page and triggers suggestion generation (`POST /audits/{id}/remediation`).
4. For each item, orchestration calls LLM with gap_note + legal_requirement to generate suggested clause text.
5. Items displayed sorted by severity (high → medium → low).
6. Each item shows: priority number, severity badge, issue label, score impact, suggested clause.
7. Copy-to-clipboard button for each suggested clause.
8. Score visualization: current score → projected score after all fixes.

**Feature 8 Gap Report Generation and Download**

Description: Structured PDF gap report generated by a custom pure-Python PDF writer with branded formatting.
Actors: Analyst.
High-Level Flow:

1. Analyst navigates to Report page.
2. Frontend displays status counts and export preview (top findings).
3. Analyst clicks "Generate PDF" (`POST /audits/{id}/report`).
4. Orchestration generates PDF using custom PDF 1.4 writer (Helvetica fonts, no external library).
5. Report includes: navy header band, executive summary with compliance score, document-wide findings, section findings with severity-colored left bars, recommended actions roadmap, remediation plan.
6. Frontend polls report status; when ready, "Download PDF" button appears.
7. PDF served via `GET /audits/{id}/report/download`.

**Feature 9 System Observability**

Description: All 4 backend services expose Prometheus metrics and emit structured JSON logs. Centralized logging via Loki/Promtail. Alertmanager with 7 rules. Grafana dashboards on port 3001.
Actors: System Administrator.
High-Level Flow:

1. All 4 services expose `/metrics` endpoint (Prometheus format).
2. Prometheus scrapes: auth-service:8004, ingestion-service:8001, knowledge-service:8002, orchestration-service:8003, postgres-exporter:9187, cadvisor:8080.
3. Grafana (port 3001) renders dashboards: retrieval latency P95, audit duration gauge, findings by status.
4. Loki (port 3100) aggregates logs from all containers via Promtail.
5. Promtail uses Docker service discovery to label logs by container/service name.
6. Alertmanager (port 9093) routes alerts via email. 7 rules: ServiceDown, KnowledgeServiceHighLatency, RemediationRequestErrors, AuditFailureRate, LongAuditDuration, HighPostgresConnectionUsage, HighMemoryUsage.
7. All services emit structured JSON logs to stdout.

## 4 AI System Requirements

### 4.1 AI System Overview

**Role of AI in CompliTrace**

CompliTrace is best described as a deterministic compliance pipeline with bounded model assistance. The system uses a bounded AI agent as one component within a multi-layer deterministic control system. The agent is responsible for:

- Pre-classifying sections as not applicable before retrieval where appropriate.
- Inferring the regulatory topic of each substantive policy section from its content.
- Formulating dynamic retrieval queries.
- Evaluating the quality of retrieved GDPR chunks.
- Classifying each section's compliance status using a structured JSON output format.
- Generating gap notes and remediation notes grounded in retrieved text.

Deterministic gates are the PRIMARY decision layer. The LLM provides bounded classification proposals that are then validated, overridden, or suppressed by programmatic controls. No LLM output reaches the user without passing through all 4 deterministic gates.

The system's canonical source of truth is the `OBLIGATION_TAXONOMY` — a 19-entry dictionary (15 unique obligation families) that defines every tracked GDPR obligation, its family, duty key, severity, applicable articles, legal anchors, and default gap text.

### 4.2 AI Functional Capabilities

**19-Obligation GDPR Taxonomy**

The system tracks 19 specific GDPR obligations organized into 15 families:

| Family | Obligations | Primary Articles |
|--------|------------|------------------|
| controller_identity_contact | missing_controller_identity, missing_controller_contact | Art. 13(1)(a), 14(1)(a) |
| legal_basis | missing_legal_basis | Art. 13(1)(c), 14(1)(c), 6 |
| retention | missing_retention_period | Art. 13(2)(a), 14(2)(a), 5(1)(e) |
| rights_notice | missing_rights_notice | Art. 13(2)(b)-(d), 14(2)(c)-(e) |
| complaint_right | missing_complaint_right | Art. 13(2)(d), 14(2)(e), 77 |
| transfer | missing_transfer_notice | Art. 13(1)(f), 14(1)(f), 44-46 |
| profiling | profiling_disclosure_gap | Art. 13(2)(f), 14(2)(g), 22 |
| recipients | recipients_disclosure_gap | Art. 13(1)(e), 14(1)(e) |
| purpose_mapping | purpose_specificity_gap | Art. 13(1)(c), 14(1)(c), 5(1)(b) |
| special_category | special_category_basis_unclear | Art. 9(2), 13(1)(c) |
| role_ambiguity | controller_processor_role_ambiguity | Art. 13(1)(a), 14(1)(a) |
| article14_source | article_14_indirect_collection_gap, article14_source_transparency_gap | Art. 14(2)(f), 14(3) |
| dpo_contact | dpo_contact_gap | Art. 13(1)(b), 14(1)(b), 37-39 |
| invalid_consent | invalid_consent_or_legal_basis | Art. 6(1)(a), 7(1) |
| cookies_tracking | cookies_tracking_consent_gap | Art. 6(1)(a), 13(1)(c) |

**Not-Applicable Pre-Classification**

Before retrieval is initiated, the agent applies `_is_not_applicable()` and `_section_auditability_type()` to identify administrative sections that contain no personal data processing content. Filtered sections skip the entire agent loop.

**Issue Spotting**

The function `_spot_candidate_issues()` generates candidate issues from the taxonomy for each section. Maximum 6 candidates per section, prioritized by relevance to section content.

**Collection Mode Inference**

The function `_collection_mode()` determines whether data collection described in the section is direct, indirect, or mixed. This affects which GDPR articles are applicable (Art. 13 vs Art. 14).

**Document Profiling**

Before per-section processing:
- `_infer_document_mode()`: Classifies document as `privacy_notice` or `internal_policy`.
- `_document_posture_agent()`: Determines triggered vs not-triggered duties.
- `_document_wide_duty_validation()`: Validates each GDPR duty across all sections.
- `_build_document_obligation_map()`: Boolean map of obligation presence.

**Legal Qualification**

The function `_legal_qualification_for_issue()` determines for each candidate issue: primary article, secondary articles, priority bucket, and disallowed article combinations.

### 4.3 Agent Behavior & Workflow

**Four Deterministic Gates**

| Gate | Name | Condition | Rejection Outcome |
|------|------|-----------|-------------------|
| 1 | Applicability | Does the duty apply given collection mode and document type? | Section skipped for this obligation |
| 2 | Sufficiency | >=2 of top-5 chunks have score >=0.50 AND at least 1 chunk contains obligation keywords (shall, must, required, obligation, necessary, appropriate)? | Finding set to needs_review |
| 3 | Citations | chunk_id traceable to retrieved universe? Article compatible with issue family? No contradictions with forbidden article matrix? | Citation rejected; finding may be demoted |
| 4 | Publication | Invariants satisfied? No internal markers (banned tokens) in user-facing text? Evidence present? | Finding suppressed to internal_only |

**Post-Loop Synthesis**

After all sections are processed:
1. `_add_systemic_issue_synthesis()` — Creates document-wide findings for patterns across sections.
2. `_add_corpus_driven_specialist_gaps()` — Specialist family gap detection (transfer, profiling, etc.).
3. `_enforce_core_and_specialist_completeness()` — Ensures all duties have outcomes.
4. `_build_final_disposition_map()` — Authoritative duty-level decision record.
5. `_final_publication_validator()` — Final quality gate on all findings.
6. `_enforce_review_publish_invariant()` — Ensures publish recommendations create findings.
7. Compliance score computation: `round(satisfied_duties / applicable_duties * 100)`.

**Tool Usage**

| Tool | Description |
|------|-------------|
| POST /search (knowledge service) | Retrieve top-k GDPR chunks with similarity scores |
| GET /chunks/{chunk_id} (knowledge service) | Fetch full chunk metadata |
| run_llm_classification | LLM inference with structured JSON output |
| persist finding + citations | Write Finding and FindingCitation rows to PostgreSQL |

**Autonomy Boundaries**

- Processes sections in order; does not reorder, skip, or group sections.
- Maximum of one retrieval retry per section.
- LLM call budget: MAX_LLM_CALLS_PER_AUDIT (default 20).
- Runtime budget: MAX_AUDIT_RUNTIME_SECONDS (default 180).
- Does not invoke external systems beyond knowledge service and LLM providers.
- Does not plan across sections or revise earlier findings based on later sections.
- Deterministic overrides can suppress or modify any LLM output.

### 4.4 RAG Requirements

**Retrieval Strategy**

- Top-k semantic retrieval with k = 5.
- Retrieval performed over the GDPR corpus only.
- Chunks ranked by cosine similarity.
- Reranking applied via `_rerank_chunks_for_mode()` based on document mode and collection type.
- Similarity scores used by the evidence sufficiency gate.

**Embedding Approach**

- Model: BAAI/bge-small-en-v1.5 via fastembed library.
- Vector dimensions: 384.
- Inference: CPU only, local (no external API calls for embedding).
- The GDPR corpus is embedded once at startup and stored in Qdrant.
- The same model is used at query time to embed retrieval queries.
- NOT sentence-transformers; fastembed is a lightweight alternative.

**Corpus Preparation**

- Source: CELEX_32016R0679_EN_TXT.pdf (official GDPR text from EUR-Lex).
- Chunking: Boundary-aware splitting with target 150 words per chunk.
- Never breaks legal cross-references mid-sentence.
- Deterministic chunk IDs via SHA-1 hash of content + metadata.
- Rich metadata per chunk: article_number, article_title, chapter, paragraph_ref, subpoint_range, page range, word count.

### 4.5 Prompting & Context Management

**Prompt Structure**

Each LLM inference call follows this structure:

1. System prompt: Defines the agent's role (GDPR compliance analyst), requires strict JSON output with fields: `status`, `severity`, `gap_note`, `remediation_note`, `policy_evidence_excerpt`, `legal_requirement`, `gap_reasoning`, `confidence_level`, `assessment_type`, `severity_rationale`, `citations`.
2. User prompt: Contains section title, section content, and retrieved GDPR evidence with similarity scores and chunk IDs.
3. Output format: Strict JSON parsed and coerced into `LlmFinding` schema.

**Provider Routing**

- Primary: Groq API (e.g., openai/gpt-oss-120b).
- Fallback: Google Gemini API (e.g., gemini-2.5-flash).
- 3 retries on HTTP 429 (rate limit) per provider.
- Returns sentinel `__rate_limited__` when all attempts fail.
- Configurable via MODEL_PROVIDER, MODEL_NAME, FALLBACK_MODEL_PROVIDER, FALLBACK_MODEL_NAME.

**Context Limits**

- LLM output parsed as JSON; if parsing fails, finding marked needs_review and raw output logged.
- Temperature: configurable, default 0.1 for deterministic behavior.

### 4.6 AI Non-Functional Requirements

| ID | Requirement | Target | Notes |
|----|-------------|--------|-------|
| AI-NFR-1 | Retrieval latency | <=500 ms per query | Measured at Knowledge Service |
| AI-NFR-2 | LLM inference latency | <=10 s per section | Using Groq API |
| AI-NFR-3 | Full audit duration | <=3 min for 10 sections | Bounded by MAX_AUDIT_RUNTIME_SECONDS=180 |
| AI-NFR-4 | Citation accuracy | 100% of citations pass all gate checks | No memory-sourced citations permitted |
| AI-NFR-5 | LLM call budget | <=20 calls per audit | Bounded by MAX_LLM_CALLS_PER_AUDIT |
| AI-NFR-6 | Output format compliance | >=95% valid JSON on first parse | Remainder handled by needs_review fallback |
| AI-NFR-7 | Rerun stability | >=80% status agreement on gold-set | Same model, prompt, temperature, corpus |

### 4.7 AI Observability & Evaluation

**Prometheus Metrics (Orchestration Service)**

Counters:
- `retrieval_retry_total`, `evidence_gate_failure_total`, `citation_validation_failure_total`
- `findings_by_status_total`, `audit_sections_total`, `audit_sections_auditable_total`, `audit_sections_filtered_total`
- `issue_spotting_calls_total`, `applicability_calls_total`, `legal_qualification_calls_total`
- `profiling_pass_total`, `transfer_pass_total`, `reviewer_pass_total`
- `publishable_findings_total`, `contradiction_fail_total`
- `local_findings_published_total`, `systemic_findings_published_total`

Histograms:
- `llm_inference_latency_seconds`
- `audit_duration_seconds`

**Structured Logging**

All services emit JSON logs with: timestamp, level, service name, and contextual fields (document_id, audit_id, section_id as applicable).

### 4.8 AI Failure Handling

**Rate Limit Handling**

- 3 retries per provider on HTTP 429.
- If primary provider exhausted, falls back to secondary provider.
- If both exhausted, returns `__rate_limited__` sentinel.
- Finding set to needs_review when rate-limited.

**Budget Exhaustion**

- MAX_LLM_CALLS_PER_AUDIT (default 20): When exhausted, remaining sections get deterministic-only assessment.
- MAX_AUDIT_RUNTIME_SECONDS (default 180): Hard timeout; audit marked audit_incomplete if exceeded.

**LLM Output Fallback**

- If LLM response cannot be parsed as valid JSON: finding set to needs_review, raw output logged.
- If LLM returns invalid status values: normalized via `_normalize_status()` mapping.

**Service Failure Handling**

- Knowledge service unreachable: audit fails with status `failed`.
- LLM API unreachable (both providers): audit continues with deterministic-only findings.
- Partial audit state is preserved; completed findings are not discarded.

## 5 Functional Requirements

### 5.1 Authentication & User Management

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-1 | Allow new users to register with first name, last name, email, password, and organization name. | POST /auth/register creates user record, returns JWT token + user profile. Duplicate email returns 409 Conflict. |
| FR-2 | Allow registered users to log in with email and password. | POST /auth/login with valid credentials returns JWT token + user profile. Invalid credentials return 401. |
| FR-3 | Verify JWT tokens and return authenticated user identity. | GET /auth/verify with valid Authorization header returns user_id, email, organization_name. Expired/invalid tokens return 401. |
| FR-4 | Allow authenticated users to retrieve their profile. | GET /auth/me with valid bearer token returns user profile (id, first_name, last_name, email, organization_name). |
| FR-5 | Scope all documents, audits, findings, remediation, and groups to the authenticated user. | A user can only access their own resources. Requests for other users' resources return 404. |
| FR-6 | Persist user session in the frontend across page refreshes. | Token stored in localStorage under key `auth_token`. On page load, token is validated via GET /auth/me; invalid tokens trigger sign-out. |
| FR-7 | Automatically sign out users on authentication failure. | Any 401 response from any API call clears the stored token and redirects to login page. |

### 5.2 Document Upload & Ingestion

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-8 | Accept the upload of a PDF file via the web UI with progress indication. | A PDF file can be uploaded. Frontend shows upload progress bar. System returns document ID and status pending. |
| FR-9 | Extract all readable text from the uploaded PDF using PyMuPDF. | Text is extracted page-by-page from all text-based PDF pages. Extraction failure sets document status to `failed` with error_message. |
| FR-10 | Detect and split the document into logical sections using regex-based heading detection. | Sections produced using HEADING_RE, SECTION_NUM_RE, subsection grouping, boilerplate filtering (50% page threshold), and noise line removal. Each section has a title (or null) and non-empty content. |
| FR-11 | Persist document metadata and all extracted sections to the database. | After parsing, document status is `parsed`. All sections queryable via GET /documents/{id}/sections with page_start/page_end where available. |
| FR-12 | Display extracted sections to the user before audit is triggered. | Sections Review page shows all sections with titles, content, page ranges, and extraction stats (section count, avg chars) within 3 seconds. |
| FR-13 | Reject non-PDF file uploads with appropriate error. | Files without .pdf extension are rejected with HTTP 400. |

### 5.3 GDPR Audit Execution

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-14 | Allow the user to trigger a GDPR gap audit on a parsed document. | POST /audits with valid document_id (and optional group_id) creates audit record with status `pending` and returns audit_id. |
| FR-15 | Perform document-level pre-computation before per-section analysis. | System infers document mode (privacy_notice/internal_policy), validates duties, builds obligation map, and extracts cross-references before section loop. |
| FR-16 | Apply not-applicable pre-classification for administrative sections. | Sections matching admin patterns with no processing signal keywords are classified not_applicable with no retrieval performed. |
| FR-17 | For each applicable section, infer relevant GDPR obligations from the 19-entry taxonomy. | Candidate issues generated per section via issue spotting; max 6 candidates per section, prioritized by relevance. |
| FR-18 | Determine collection mode (direct/indirect/mixed) for each section. | Collection mode inference affects which GDPR articles (Art. 13 vs Art. 14) are applicable. |
| FR-19 | Perform legal qualification for each candidate issue. | Each issue receives: primary article, secondary articles, priority bucket, and disallowed article combinations. |
| FR-20 | Retrieve top-5 semantically relevant GDPR chunks from Qdrant for each substantive section. | Each retrieval returns up to 5 chunks with article_number, paragraph_ref, chunk_id, content, and similarity score. Reranking applied via document mode. |
| FR-21 | Apply evidence sufficiency gate (Gate 2) before substantive classification. | If fewer than 2 top-5 chunks have score ≥0.50 or no chunk contains obligation keywords (shall, must, required, obligation, necessary, appropriate), finding set to needs_review. |
| FR-22 | Classify each section via LLM within call budget constraints. | LLM called with section text + retrieved chunks. Structured JSON output parsed into finding. Budget bounded by MAX_LLM_CALLS_PER_AUDIT (20) and MAX_AUDIT_RUNTIME_SECONDS (180). |
| FR-23 | Validate all citations against the 3-check citation gate (Gate 3). | Every citation passes: chunk_id traceable to retrieved universe, article compatible with issue family, no forbidden article matrix violations. |
| FR-24 | Apply publication gate (Gate 4) before any finding reaches the user. | No finding with internal markers, banned tokens, missing evidence, or failed invariants is visible to the user. Failed findings suppressed to internal_only. |
| FR-25 | Assign severity according to canonical rules. | gap/partial findings have non-null severity (low/medium/high). compliant/needs_review/not_applicable have null severity. No exceptions. |
| FR-26 | Generate gap note and remediation note for applicable findings. | Non-empty strings for gap/partial findings. Null for all other statuses. |
| FR-27 | Persist all findings and citations after each section's analysis. | All findings queryable via GET /audits/{id}/findings after audit completion. |
| FR-28 | Perform post-loop synthesis after all sections are processed. | System generates systemic (document-wide) findings, detects specialist family gaps, builds final disposition map, and enforces publication invariants. |
| FR-29 | Compute compliance score after all sections processed. | compliance_score = round(satisfied_duties / applicable_duties × 100). Stored on audit record as integer 0-100. |
| FR-30 | Transition audit to terminal status after processing. | Audit status set to `complete`, `review_required`, or `audit_incomplete` based on gate outcomes and budget exhaustion. |
| FR-31 | Persist audit provenance metadata. | Audit record includes non-null: model_provider, model_name, model_temperature, prompt_template_version, embedding_model, corpus_version. |
| FR-32 | Allow the user to poll audit status during execution. | GET /audits/{id} returns current status. Frontend polls every 3.5 seconds until terminal status reached. |

### 5.4 Findings Display

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-33 | Display findings with compliance score and status counts. | Findings page shows compliance score (color-coded), status counts grid (Compliant, Partial, Non-compliant, Not applicable, Total). |
| FR-34 | Separate document-wide findings from section-level findings. | Systemic findings (document-wide) displayed in a distinct section above section-level findings table. |
| FR-35 | Display finding detail on click with full evidence trace. | Detail panel shows: issue label, why it matters, recommended action, legal anchors, policy evidence excerpt, gap note, remediation note, citations with article/paragraph/excerpt. |
| FR-36 | Display compliance checklist for fully compliant documents. | When compliance_score = 100% and no non-compliant findings exist, a GDPR obligation checklist is displayed showing which duties were satisfied. |
| FR-37 | Provide analysis and review views for debugging. | GET /audits/{id}/analysis and GET /audits/{id}/review return internal pipeline data. Accessible via ?debug=true URL parameter in frontend. |

### 5.5 Remediation Planning

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-38 | Automatically create remediation items when audit completes with score < 100%. | Remediation items created for each non-compliant finding with issue_key, issue_label, severity, score_impact_points, order_index. |
| FR-39 | Generate LLM-based remediation suggestions on user request. | POST /audits/{id}/remediation triggers LLM generation of suggested clause text per item. System prompt instructs model GDPR-compliant clause with bracketed placeholders. |
| FR-40 | Display remediation items sorted by severity with score impact. | GET /audits/{id}/remediation returns items sorted by severity (high→medium→low). Each shows priority number, severity badge, issue label, score impact points. |
| FR-41 | Allow user to copy suggested clause text to clipboard. | Each remediation item with a completed suggestion displays a copy-to-clipboard button. |
| FR-42 | Display remediation generation progress. | GET /audits/{id}/remediation/status returns total, pending, complete, failed counts. |

### 5.6 Report Generation

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-43 | Generate a structured PDF gap report from a completed audit. | POST /audits/{id}/report triggers PDF generation using custom PDF writer. Report includes: navy header, executive summary with compliance score, document-wide findings, section findings with severity-colored bars, remediation roadmap. |
| FR-44 | Allow the user to check report generation status. | GET /audits/{id}/report returns report status (pending/ready/failed) and created_at. |
| FR-45 | Allow the user to download the generated PDF report. | GET /audits/{id}/report/download returns the PDF binary stream. Frontend constructs filename as `v{version} {title} audit {date}.pdf`. |

### 5.7 Document Groups & Versioning

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-46 | Allow users to create named document groups. | POST /groups with name creates group scoped to user_id. Returns group with id, name, timestamps. |
| FR-47 | Allow users to list all their document groups with versions. | GET /groups returns all groups for authenticated user with nested version arrays (document_id, audit_id, version_number, compliance_score). |
| FR-48 | Allow users to rename document groups. | PATCH /groups/{id} with new name updates the group. User_id ownership verified. |
| FR-49 | Allow users to delete document groups. | DELETE /groups/{id} removes the group and unlinks audits (sets document_group_id to null). Does not delete audits. |
| FR-50 | Assign audits to groups with automatic version numbering. | When audit is created with group_id, version_number is auto-incremented within that group. |
| FR-51 | Display document sidebar with group navigation. | Persistent sidebar shows groups with expandable versions, compliance scores per version, and click-to-navigate to findings. |

### 5.8 Observability & Operations

| ID | Requirement (The system shall...) | Acceptance Criteria |
|----|-----------------------------------|--------------------|
| FR-52 | Expose Prometheus metrics from all four backend services. | All four services return valid Prometheus format at /metrics. Prometheus scrapes all targets without error. |
| FR-53 | Display Grafana dashboards with system health data. | After one audit, dashboard panels show: retrieval latency P95, audit duration gauge (thresholds at 120s/180s), findings by status bar chart. |
| FR-54 | Emit structured JSON logs from all four services. | All log lines are valid JSON with at minimum: timestamp, level, service name, and message fields. |
| FR-55 | Aggregate logs from all services via Loki and Promtail. | Loki collects logs from all Docker containers via Promtail. Logs searchable and filterable by service name and log level. |
| FR-56 | Send automated email alerts for critical system events. | Alertmanager sends email notifications when alert rules fire. 7 rules configured: ServiceDown, KnowledgeServiceHighLatency, RemediationRequestErrors, AuditFailureRate, LongAuditDuration, HighPostgresConnectionUsage, HighMemoryUsage. |
| FR-57 | Start the complete system with a single docker-compose up command. | All services start; web UI reachable within 60 seconds. |
| FR-58 | Run automated CI/CD pipeline on every push and pull request. | GitHub Actions executes: Ruff lint, pytest (auth/ingestion/orchestration), ESLint, Vite build, Playwright E2E. Pipeline fails on any error. |

## 6 Non-Functional Requirements

### 6.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-P-1 | Retrieval latency per query | <=500 ms at Knowledge Service |
| NFR-P-2 | Document parsing time | <=10 s for a 10-page PDF |
| NFR-P-3 | Full audit duration | <=3 minutes for 10 sections (Groq API) |
| NFR-P-4 | PDF report generation | <=15 s from trigger to file-ready |
| NFR-P-5 | Frontend page load | <=3 s for all pages |

### 6.2 Security

- LLM API keys stored as environment variables, never in version control.
- File upload restricted to PDF. Non-PDF rejected with 400.
- Uploaded files stored in isolated Docker volume.
- JWT authentication (HS256, 24h expiry) via dedicated auth-service.
- All protected endpoints verify bearer token by calling auth-service GET /auth/verify.
- All data scoped to authenticated user_id at query layer.
- Inter-service communication on Docker internal network only.

### 6.3 Usability

- Complete workflow (register -> login -> upload -> sections -> audit -> findings -> remediation -> report) completable without documentation.
- All status indicators use color AND label differentiation.
- Error states communicated with human-readable messages.
- Not-applicable findings visually distinguished throughout UI.

### 6.4 Reliability & Availability

- System must complete full audit on benchmark documents without failure.
- Service failures must transition audit/document to failed status, not corrupt data.
- Auth-service must remain available independently of other services.

### 6.5 Scalability

- System supports multiple concurrent users with isolated data.
- Architecture supports future horizontal scaling: stateless services, externalized state.
- GDPR corpus capped at 350 chunks for target hardware performance.

### 6.6 Maintainability & Observability

- All services use structured JSON logging.
- All services expose /health endpoint returning HTTP 200.
- Prometheus metrics cover: retrieval, LLM inference, audit lifecycle, parsing, gate failures, citation validation.
- Grafana dashboards provisioned from code.
- Loki aggregates logs from all services via Promtail.
- Alertmanager routes alerts with 7 configured rules.
- Code separated into distinct service directories with Pydantic-defined contracts.

## 7 External Interfaces

### 7.1 User Interface

The web frontend is a React + Vite + Tailwind CSS single-page application with seven pages and a persistent document sidebar:

1. Login Page: Email/password input, login button, link to signup.
2. Signup Page: Registration form (first_name, last_name, email, password, organization_name).
3. Upload Page: File input with drag-to-browse, group selector with autocomplete, upload progress bar.
4. Sections Review Page: Ordered sections with titles, content, page ranges. Stats (count, avg chars). Start Audit button.
5. Findings Page: Compliance score, status counts grid, document-wide findings, section findings table, detail panel on click, compliance checklist for score=100%.
6. Remediation Page: Score visualization (current -> projected), items sorted by severity, suggested clause text, copy-to-clipboard.
7. Report Page: Status counts, export preview, Generate PDF button, Download PDF button.

Document Sidebar: Groups with versions, compliance scores per version, create/rename/delete groups.

Polling: 3.5s for audit status, 2.5s for report generation, 10s for sidebar group updates.

### 7.2 APIs & External Services

| External Service | Integration Point | Purpose |
|-----------------|-------------------|----------|
| Groq API (primary) | Orchestration Service | LLM inference for classification |
| Gemini Flash API (fallback) | Orchestration Service | LLM inference fallback |
| EUR-Lex | Offline ingestion script | Source of GDPR text |

### 7.3 System Interfaces (Service-to-Service)

| Caller | Callee | Interface |
|--------|--------|----------|
| Frontend | Auth Service (8004) | POST /auth/register, POST /auth/login, GET /auth/me |
| Frontend | Ingestion Service (8001) | POST /documents, GET /documents/{id}, GET /documents/{id}/sections |
| Frontend | Orchestration Service (8003) | POST /audits, GET /audits/{id}, GET /audits/{id}/findings, POST /audits/{id}/report, GET /audits/{id}/report/download, POST /audits/{id}/remediation, GET /audits/{id}/remediation, GET /groups, POST /groups, PATCH /groups/{id}, DELETE /groups/{id} |
| Orchestration | Auth Service | GET /auth/verify (token validation) |
| Orchestration | Ingestion Service | GET /documents/{id}/sections |
| Orchestration | Knowledge Service (8002) | POST /search, GET /chunks/{id} |
| Prometheus (9090) | All 4 services | GET /metrics |
| Promtail | All containers | Docker log collection |
| Promtail | Loki (3100) | Push API |
| Alertmanager (9093) | Prometheus | Receives firing alerts |
| Alertmanager | SMTP | Email delivery |

## 8 Data Requirements

### 8.1 Data Model Overview

The relational data model consists of 13 tables across two PostgreSQL databases:

| Database | Table | Purpose |
|----------|-------|----------|
| auth_db | users | User accounts and credentials |
| complitrace | documents | Uploaded document metadata and parsing status |
| complitrace | sections | Extracted sections with order, title, content, page span |
| complitrace | document_groups | Named groups for organizing audits |
| complitrace | audits | Audit lifecycle, status, provenance, compliance score |
| complitrace | findings | Per-section compliance findings with publication controls |
| complitrace | finding_citations | GDPR article citations linked to findings |
| complitrace | audit_analysis_items | Internal pipeline analysis artifacts |
| complitrace | analysis_citations | Citations linked to analysis items |
| complitrace | evidence_records | Canonical evidence index with traceability |
| complitrace | remediation_items | Remediation tasks linked to findings |
| complitrace | remediation_suggestions | LLM-generated suggested clause text |
| complitrace | reports | Report generation status and PDF path |

Vector data (GDPR chunk embeddings) is stored in Qdrant.

**users** (auth_db)

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| first_name | String(120) | Not null |
| last_name | String(120) | Not null |
| email | String(255) | Unique, indexed, not null |
| password_hash | String(255) | bcrypt hash, not null |
| organization_name | String(255) | Not null |
| created_at | DateTime | Not null |

**documents**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| title | String(255) | |
| filename | String(255) | |
| status | String(32) | pending, parsed, failed |
| error_message | Text | Nullable |
| created_at | DateTime | |

**sections**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| document_id | String(36) | FK -> documents, indexed, CASCADE |
| section_order | Integer | Position in document |
| section_title | String(255) | |
| content | Text | Not null |
| page_start | Integer | Nullable |
| page_end | Integer | Nullable |

**document_groups**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| user_id | String(36) | Indexed, not null |
| name | String(255) | Not null |
| created_at | DateTime | |
| updated_at | DateTime | Auto-updated |

**audits**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| document_id | String(36) | Indexed |
| user_id | String(36) | Nullable, indexed |
| document_group_id | String(36) | FK -> document_groups, nullable, SET NULL |
| version_number | Integer | Nullable |
| status | String(32) | pending, running, complete, failed, review_required, audit_incomplete |
| started_at | DateTime | |
| completed_at | DateTime | Nullable |
| model_provider | String(64) | |
| model_name | String(128) | |
| model_temperature | Float | Default 0.1 |
| prompt_template_version | String(32) | |
| embedding_model | String(128) | |
| corpus_version | String(64) | |
| compliance_score | Integer | Nullable, 0-100 |

**findings**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| audit_id | String(36) | FK -> audits, indexed, CASCADE |
| section_id | String(128) | Indexed |
| status | String(32) | compliant, partial, gap, needs_review, not_applicable |
| severity | String(16) | Nullable (low, medium, high) |
| classification | String(32) | Nullable |
| confidence | Float | Nullable |
| confidence_evidence | Float | Nullable |
| confidence_applicability | Float | Nullable |
| confidence_article_fit | Float | Nullable |
| confidence_synthesis | Float | Nullable |
| confidence_overall | Float | Nullable |
| finding_type | String(32) | Default: local |
| publish_flag | String(8) | Default: yes |
| artifact_role | String(32) | Default: publishable_finding |
| finding_level | String(16) | Default: local |
| publication_state | String(16) | Default: publishable |
| obligation_under_review | String(64) | Nullable |
| collection_mode | String(32) | Nullable |
| applicability_status | String(32) | Nullable |
| policy_evidence_excerpt | Text | Nullable |
| legal_requirement | Text | Nullable |
| gap_reasoning | Text | Nullable |
| severity_rationale | Text | Nullable |
| primary_legal_anchor | Text | Nullable |
| secondary_legal_anchors | Text | Nullable |
| document_evidence_refs | Text | Nullable |
| citation_summary_text | Text | Nullable |
| source_scope | String(32) | Nullable |
| gap_note | Text | Nullable |
| remediation_note | Text | Nullable |

Note: The findings table contains 40+ columns total. Only key columns are shown above.

**finding_citations**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| finding_id | String(36) | FK -> findings, indexed, CASCADE |
| chunk_id | String(128) | Not null |
| article_number | String(32) | Not null |
| paragraph_ref | String(64) | Nullable |
| article_title | String(512) | Default: empty |
| excerpt | Text | Default: empty |

**audit_analysis_items**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| audit_id | String(36) | FK -> audits, indexed, CASCADE |
| section_id | String(128) | Indexed |
| analysis_stage | String(64) | Default: section_processing |
| analysis_type | String(64) | Default: provisional_local |
| issue_type | String(128) | Nullable |
| status_candidate | String(32) | Nullable |
| artifact_role | String(32) | Default: analysis_candidate |
| analysis_outcome | String(64) | Default: candidate_gap |
| confidence | Float | Nullable |
| gap_note | Text | Nullable |
| remediation_note | Text | Nullable |
| created_at | DateTime | |

**analysis_citations**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| analysis_item_id | String(36) | FK -> audit_analysis_items, indexed, CASCADE |
| chunk_id | String(128) | Not null |
| article_number | String(32) | Not null |
| paragraph_ref | String(64) | Nullable |
| article_title | String(512) | Default: empty |
| excerpt | Text | Default: empty |

**evidence_records**

| Column | Type | Notes |
|--------|------|-------|
| evidence_id | String(191) | Primary key |
| audit_id | String(36) | FK -> audits, indexed, CASCADE |
| evidence_type | String(48) | Indexed |
| source_ref | String(191) | Nullable |
| text_excerpt | Text | Nullable |
| derived_from_evidence_ids | Text | Nullable |
| article_number | String(32) | Nullable |
| paragraph_ref | String(64) | Nullable |
| created_at | DateTime | |

**remediation_items**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| audit_id | String(36) | FK -> audits, indexed, CASCADE |
| finding_id | String(36) | FK -> findings, CASCADE |
| issue_key | String(128) | Not null |
| issue_label | String(256) | Not null |
| severity | String(16) | Not null |
| score_impact_points | Integer | Not null |
| order_index | Integer | Not null |
| section_id | Text | Nullable |
| created_at | DateTime | |

**remediation_suggestions**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| remediation_item_id | String(36) | FK -> remediation_items, unique, CASCADE |
| suggested_fix_text | Text | Nullable |
| generation_status | String(16) | Default: pending (pending/complete/failed) |
| created_at | DateTime | |

**reports**

| Column | Type | Notes |
|--------|------|-------|
| id | String(36) | Primary key, UUID |
| audit_id | String(36) | FK -> audits, indexed, CASCADE |
| status | String(32) | Default: pending (pending/ready/failed) |
| pdf_path | Text | Nullable |
| created_at | DateTime | |

### 8.2 Data Validation Rules

- documents.status must be one of: pending, parsed, failed.
- audits.status must be one of: pending, running, complete, failed, review_required, audit_incomplete.
- findings.status must be one of: compliant, partial, gap, needs_review, not_applicable.
- findings.severity must be null when status is compliant, needs_review, or not_applicable; non-null (low/medium/high) when status is gap or partial.
- audits.compliance_score must be an integer between 0 and 100 (inclusive) or null.
- finding_citations.chunk_id must be non-null and reference a point ID present in the Qdrant collection.
- finding_citations.article_number must be a non-empty string matching a valid GDPR article identifier.
- sections.content must be non-empty.
- All primary keys are UUIDs (String(36)), generated server-side.
- Foreign key relationships enforced at the database level with CASCADE delete.
- remediation_suggestions.remediation_item_id has a unique constraint (one suggestion per item).

### 8.3 Data Storage & Persistence

- Two PostgreSQL databases: `complitrace` (ingestion + orchestration data) and `auth_db` (user accounts).
- Both databases run in a single PostgreSQL 16 container with a named volume for persistence.
- Vector embeddings stored in Qdrant with a named volume.
- Uploaded PDF files stored in a Docker volume mounted to ingestion service (`ingestion_storage`).
- Generated PDF reports stored in a Docker volume mounted to orchestration service (`orchestration_storage`).
- No data stored exclusively in memory; all state survives service restarts.

### 8.4 Data Lifecycle

- The GDPR corpus is loaded into Qdrant at service startup from pre-processed JSONL. It is not modified at runtime.
- Uploaded documents and derived data persist indefinitely (no TTL or deletion policy).
- Deleting a document group unlinks audits but does not delete them.
- No data purge or archival mechanism is implemented.


## 9 System Architecture & Service Model

### 9.1 Architectural Style

CompliTrace uses a microservice architecture with synchronous REST communication between services. Four independent FastAPI services handle distinct bounded concerns. All services are containerised with Docker and orchestrated locally via Docker Compose.

The microservice split was chosen because the four concerns — user authentication, document ingestion, regulatory knowledge retrieval, and agent orchestration — have meaningfully different responsibilities, storage backends, performance profiles, and failure modes that benefit from independent observability and deployment boundaries.

### 9.2 Service Overview

| Service | Port | Responsibility |
|---------|------|----------------|
| Auth Service | 8004 | User registration, login, JWT generation/verification. Owns users table in auth_db. |
| Document Ingestion Service | 8001 | Accept PDF upload; extract text; detect and split sections; persist document and sections to PostgreSQL. |
| Regulatory Knowledge Service | 8002 | Store GDPR embeddings in Qdrant; serve semantic retrieval queries with similarity scores; return ranked chunks with citation metadata. |
| Agent Orchestration Service | 8003 | Own audit lifecycle; run bounded agent loop with 4 gates; persist findings and provenance; compute compliance score; generate remediation items; generate PDF reports. |

Report generation is an internal module of the Agent Orchestration Service using a custom pure-Python PDF writer.

### 9.3 Inter-Service Communication

All inter-service communication is synchronous HTTP/REST. No message broker or event stream is used.

- Frontend -> Auth Service: Registration, login, profile retrieval.
- Frontend -> Ingestion Service: Document upload and sections retrieval.
- Frontend -> Orchestration Service: Audit management, findings, remediation, groups, reports.
- Orchestration Service -> Auth Service: Token verification (GET /auth/verify).
- Orchestration Service -> Ingestion Service: Fetch sections at audit start.
- Orchestration Service -> Knowledge Service: Semantic retrieval during agent loop.
- Prometheus -> All 4 services: Metrics scraping via /metrics.
- Promtail -> All containers: Log collection.

### 9.4 API Contracts & Boundaries

All service APIs defined using FastAPI with Pydantic request/response models. Contracts auto-documented via OpenAPI at /docs on each service.

| Service | Key Endpoints |
|---------|---------------|
| Auth | POST /auth/register, POST /auth/login, GET /auth/me, GET /auth/verify, GET /health, GET /metrics |
| Ingestion | POST /documents, GET /documents/{id}, GET /documents/{id}/sections, GET /health, GET /metrics |
| Knowledge | POST /search, GET /chunks/{chunk_id}, GET /health, GET /metrics |
| Orchestration | POST /audits, GET /audits/{id}, GET /audits/{id}/findings, GET /audits/{id}/analysis, GET /audits/{id}/review, GET /audits/{id}/review/grouped, GET /audits/{id}/final-decision-ledger, GET /audits/{id}/export-contract, POST /audits/{id}/report, GET /audits/{id}/report, GET /audits/{id}/report/download, POST /audits/{id}/remediation, GET /audits/{id}/remediation, GET /audits/{id}/remediation/status, POST /groups, GET /groups, PATCH /groups/{id}, DELETE /groups/{id}, POST /groups/{id}/versions, GET /health, GET /metrics |

### 9.5 Data Ownership & Isolation

- Auth Service owns the `users` table in `auth_db`.
- Ingestion Service owns `documents` and `sections` tables in `complitrace`.
- Knowledge Service owns the Qdrant collection (`gdpr_chunks`).
- Orchestration Service owns `audits`, `findings`, `finding_citations`, `audit_analysis_items`, `analysis_citations`, `evidence_records`, `remediation_items`, `remediation_suggestions`, `reports`, and `document_groups` in `complitrace`.
- Ingestion and Orchestration share the `complitrace` database instance.

### 9.6 Scalability Strategy

The system supports multiple concurrent users with isolated data. The architecture supports future scaling:

- Persistent state externalized to PostgreSQL and Qdrant.
- Horizontal scaling of Knowledge Service feasible without changes.
- Orchestration Service can be made asynchronous using a task queue for concurrent audits.
- Auth Service is stateless (JWT-based) and horizontally scalable.

### 9.7 Fault Tolerance & Failure Scenarios

| Failure Scenario | Detection | Response |
|-----------------|-----------|----------|
| PDF parse failure | Ingestion exception | Document status -> failed; error returned |
| Knowledge Service unreachable | HTTP connection error | Audit status -> failed; error logged |
| LLM API unreachable (both providers) | HTTP error after retries | Audit continues with deterministic-only findings |
| LLM output parse failure | JSON parse error | Finding -> needs_review; raw output logged |
| LLM rate limited | 429 after 3 retries | Fallback provider attempted; if both fail, sentinel returned |
| Evidence sufficiency gate failure | Gate evaluation | Finding -> needs_review; metric incremented |
| Citation validation failure | Post-parse check | Invalid citation rejected; finding persisted with valid citations only |
| Report generation failure | PDF writer exception | Report status -> failed; error logged |
| Auth service unreachable | HTTP error from orchestration | 401 returned to frontend; user redirected to login |
| Budget exhaustion (LLM calls) | Counter check | Remaining sections get deterministic-only assessment |
| Runtime timeout | Clock check | Audit marked audit_incomplete |

### 9.8 Deployment & Infrastructure Constraints

- All services containerised using Docker.
- Full stack orchestrated via single docker-compose.yml.
- System must start on machine with 16 GB RAM, no GPU.
- Service ports: auth (8004), ingestion (8001), knowledge (8002), orchestration (8003), postgres (5432), qdrant (6333), prometheus (9090), grafana (3001), alertmanager (9093), loki (3100), cadvisor (8081), postgres-exporter (9187), frontend (5173).
- Environment variables passed via .env file excluded from version control.
- PostgreSQL init script creates auth_db on first startup.

### 9.9 Observability & Monitoring

- Prometheus: Scrapes /metrics from all 4 services + postgres-exporter + cadvisor. Interval: 15s.
- Grafana (port 3001): Two provisioned dashboards (overview + extended). Panels: retrieval latency P95, audit duration gauge, findings by status.
- Loki (port 3100): Log aggregation from all containers via Promtail.
- Promtail: Docker service discovery, labels by container/service name.
- Alertmanager (port 9093): 7 alert rules (ServiceDown, KnowledgeServiceHighLatency, RemediationRequestErrors, AuditFailureRate, LongAuditDuration, HighPostgresConnectionUsage, HighMemoryUsage). Email routing.
- Health checks: All services expose GET /health returning HTTP 200.

## 10 Acceptance Criteria (System-Level)

1. A PDF privacy policy document can be uploaded and parsed into sections without error.
2. The extracted sections are visible in the web UI before the audit is triggered.
3. A full audit completes without error on the benchmark documents (pp_compliant.pdf, pp_NonCompliant.pdf).
4. Every finding contains a valid status, severity following canonical rules, and appropriate notes.
5. Every citation passes all 3 gate checks: chunk_id traceable, article compatible, no forbidden violations.
6. Clicking any finding shows the full detail panel with GDPR evidence.
7. Administrative sections are classified as not_applicable and excluded from gap counts.
8. A PDF gap report can be generated and downloaded with all mandatory fields.
9. The system starts fully with `docker-compose up` and UI is reachable within 60 seconds.
10. All four Prometheus metric endpoints return valid data and Grafana shows live dashboard data.
11. The GitHub Actions CI/CD pipeline passes green on the main branch.
12. The full workflow (register -> upload -> audit -> findings -> remediation -> report) is completable.
13. Benchmark validation: pp_compliant.pdf produces 0 non-compliant findings (score ~100%). pp_NonCompliant.pdf produces 7 specific non-compliant findings (Legal basis, Retention, Transfer, Rights, Complaint-right, Cookie transparency, Profiling).
14. Compliance score is computed and displayed correctly for all completed audits.
15. Remediation items are generated with suggested clause text for non-compliant findings.
16. Document groups support create, rename, delete, and version assignment.

## 11 Traceability

| Requirement ID | Feature | Service | Verification |
|---------------|---------|---------|---------------|
| FR-1 to FR-4 | Auth | Auth Service | Register/login/verify/me endpoints return correct responses |
| FR-5 | Auth | Orchestration | Verify user_id scoping on all queries |
| FR-6, FR-7 | Auth | Frontend | Token persistence in localStorage; 401 triggers sign-out |
| FR-8 | Upload | Ingestion | Upload PDF; verify progress and document ID returned |
| FR-9 | Upload | Ingestion | Verify text extraction returns non-empty text |
| FR-10 | Upload | Ingestion | Verify sections produced with heading detection rules |
| FR-11 | Upload | Ingestion | Query /sections; verify all present with page spans |
| FR-12 | Sections | Frontend | Navigate to Sections page; verify renders <3s with stats |
| FR-13 | Upload | Ingestion | Upload non-PDF; verify 400 rejection |
| FR-14 | Audit | Orchestration | POST /audits; verify audit_id and status=pending |
| FR-15 | Audit | Orchestration | Verify document profiling runs before section loop |
| FR-16 | Audit | Orchestration | Verify admin section → not_applicable with no retrieval |
| FR-17 | Audit | Orchestration | Verify issue spotting from taxonomy per section |
| FR-18 | Audit | Orchestration | Verify collection mode affects article applicability |
| FR-19 | Audit | Orchestration | Verify legal qualification assigns primary/secondary articles |
| FR-20 | Audit | Knowledge | POST /search; verify 5 chunks with scores returned |
| FR-21 | Audit | Orchestration | Verify evidence gate failure → needs_review |
| FR-22 | Audit | Orchestration | Verify LLM called within budget; deterministic fallback on exhaustion |
| FR-23 | Audit | Orchestration | Verify citation gate rejects invalid citations |
| FR-24 | Audit | Orchestration | Verify publication gate suppresses internal findings |
| FR-25 | Audit | Orchestration | Verify severity follows canonical rules |
| FR-26 | Audit | Orchestration | Verify gap_note/remediation_note non-empty for gap/partial |
| FR-27 | Audit | Orchestration | Query /findings; verify all present |
| FR-28 | Audit | Orchestration | Verify systemic findings generated in post-loop |
| FR-29 | Audit | Orchestration | Verify compliance_score computed correctly |
| FR-30 | Audit | Orchestration | Verify terminal status set (complete/review_required/audit_incomplete) |
| FR-31 | Provenance | Orchestration | Verify audit record has all provenance fields |
| FR-32 | Audit | Frontend | Verify polling at 3.5s interval until terminal status |
| FR-33 to FR-36 | Findings | Frontend | Verify findings display, detail panel, checklist, debug views |
| FR-37 | Analysis | Orchestration | Verify /analysis and /review endpoints return data |
| FR-38 to FR-42 | Remediation | Orchestration | Verify items created, suggestions generated, status tracked |
| FR-43 to FR-45 | Report | Orchestration | Verify PDF generation, status polling, download |
| FR-46 to FR-51 | Groups | Orchestration | Verify CRUD, version numbering, sidebar display |
| FR-52 | Observability | All | Prometheus scrapes all 4 targets |
| FR-53 | Observability | Grafana | Dashboard panels show data after audit |
| FR-54 | Observability | All | Verify JSON logs with required fields |
| FR-55 | Logging | Loki | Verify logs collected and searchable |
| FR-56 | Alerting | Alertmanager | Verify email sent on ServiceDown |
| FR-57 | Deployment | Infra | docker-compose up; UI reachable ≤60s |
| FR-58 | CI/CD | GitHub Actions | Verify pipeline passes green |

## 12 Risks, Constraints & Limitations

### 12.1 Technical Risks

| Risk | Description | Likelihood | Mitigation |
|------|-------------|------------|------------|
| PDF section parsing quality | Arbitrary PDFs may lack clear heading structure | Medium | Regex-based detection with fallback; benchmark on test docs |
| Docker Compose networking | Inter-service calls may fail due to startup ordering | Medium | Use depends_on; retry logic in HTTP clients |
| LLM API rate limits | Groq/Gemini may rate-limit rapid sequential calls | Medium | 3 retries per provider; fallback provider; budget cap |
| Embedding model compatibility | Score distributions may shift with model updates | Low | Pin fastembed version; calibrate thresholds on benchmark |

### 12.2 AI-Specific Risks

| Risk | Description | Likelihood | Mitigation |
|------|-------------|------------|------------|
| LLM classification inconsistency | Same section may get different status on repeated runs | Medium | Low temperature (0.1); 4 deterministic gates override LLM; benchmark regression tests |
| LLM output format failure | LLM returns non-JSON or malformed output | Low | JSON parse validation; needs_review fallback; raw output logged |
| Hallucinated citations | LLM cites articles not in retrieved chunks | Low | Gate 3 rejects any citation not in retrieved universe |
| Retrieval recall gaps | Some GDPR topics may have weak coverage at k=5 | Low | Evidence sufficiency gate forces needs_review; reranking applied |
| Over-classification of not_applicable | Substantive section incorrectly filtered | Low | Processing signal keyword check before filtering |

### 12.3 Operational Risks

- LLM API availability: Dual-provider fallback (Groq + Gemini) mitigates single-provider outage.
- Single-instance deployment: Named Docker volumes preserve state across restarts.
- Corpus staleness: GDPR text is stable; re-indexing supported via FORCE_REINDEX flag.

### 12.4 Known Limitations

- Only clean, text-extractable PDFs are supported. Scanned documents require OCR (not implemented).
- Only the GDPR regulatory standard is supported.
- Audit execution is synchronous within a single HTTP request (bounded by 180s timeout).
- No distributed tracing (Jaeger/Zipkin) is implemented.
- No WebSocket support; frontend uses polling for status updates.
- Findings are a first-pass analytical output. They do not constitute legal advice.
- The not-applicable pre-classification uses pattern matching; novel administrative titles may not be filtered.
- No pagination on sections or findings endpoints.

## 13 Versioning & Change Log

| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0 | April 3, 2026 | Project Author | Initial SRS draft. GDPR-only. Three-service architecture. |
| 1.1 | April 4, 2026 | Project Author | Added: deterministic gates, evidence sufficiency, citation validation, auth service, provenance fields, rerun stability criterion. |
| 2.0 | May 12, 2026 | Project Author | Full alignment with implemented system. Four-service architecture (auth-service added as dedicated service). 13-table data model. 19-obligation taxonomy with 4 deterministic gates. Compliance scoring. Remediation planning with LLM-generated suggestions. Document groups with versioning. Custom PDF writer (replaced WeasyPrint). BAAI/bge-small-en-v1.5 via fastembed (replaced sentence-transformers). Loki/Promtail logging. Alertmanager with 7 rules. CI/CD pipeline. Benchmark validation with pp_compliant.pdf and pp_NonCompliant.pdf. Updated all language to reflect final system state. |

## 14 Appendices

### 14.1 Diagrams

The following diagrams are maintained in the `/diagrams/` directory:

| File | Description | Used In |
|------|-------------|---------|
| `systemArchitecture.png` | Full system architecture with all services, data stores, and observability stack | §3, §9 |
| `microservices.png` | Microservice functional decomposition with responsibilities and communication patterns | §9.2 |
| `useCaseDiagUML.png` | UML use case diagram showing all actor-system interactions | §2.7, §3 |
| `erd.png` | Entity-Relationship Diagram showing all 13 tables and relationships | §8.1 |
| `sequenceUML.png` | UML sequence diagram for the audit workflow (auth → ingestion → knowledge → orchestration) | §4.3, §9.3 |
| `pipelineRag.png` | RAG pipeline flow: section → embedding → retrieval → filtering → LLM → validation → output | §4.4 |
| `agentt.png` | Bounded AI agent architecture with 4 deterministic gates and post-loop synthesis | §4.1, §4.3 |

**High-Level Architecture (Text Representation)**

```
[React Frontend (Vite + Tailwind) :5173]
        |
        | HTTP
        v
+--Auth Service :8004--+  +--Ingestion Service :8001--+  +--Knowledge Service :8002--+
| - User registration  |  | - PDF upload             |  | - GDPR corpus (Qdrant)   |
| - JWT generation     |  | - Text extraction        |  | - Semantic retrieval     |
| - Token verification |  | - Section detection      |  | - fastembed bge-small    |
| - PostgreSQL(auth_db)|  | - PostgreSQL(complitrace)|  | - Citation metadata      |
+----------------------+  +---------------------------+  +---------------------------+
        ^                           |                            ^
        | verify token               | sections                   | search + scores
        |                           v                            |
+--Agent Orchestration Service :8003-------------------------------------------+
| - Audit lifecycle + provenance                                               |
| - 19-obligation taxonomy                                                     |
| - 4 deterministic gates (applicability, sufficiency, citation, publication)  |
| - Bounded LLM inference (Groq primary / Gemini fallback)                     |
| - Post-loop synthesis + compliance score                                     |
| - Remediation planning + LLM suggestions                                    |
| - Custom PDF report writer                                                   |
| - PostgreSQL (audits, findings, citations, remediation, groups, reports)     |
+------------------------------------------------------------------------------+
        |
        | metrics
        v
[Prometheus :9090] --> [Grafana :3001]
[Loki :3100] <-- [Promtail]
[Alertmanager :9093] --> [Email]
[cAdvisor :8081] [Postgres Exporter :9187]
```

**Agent Bounded Loop (4-Gate Pipeline)**

```
START: Load sections; stamp provenance; pre-compute document profile

FOR each section in order:

  STEP 0 | Applicability filter
  IF section is admin/meta (no processing signals):
    -> Skip section

  STEP 1 | Issue spotting
  Generate candidate issues from 19-obligation taxonomy (max 6)

  STEP 2 | Legal qualification
  For each candidate: determine primary article, priority bucket

  STEP 3 | Retrieval
  Build query -> POST /search (k=5) -> rerank by mode

  GATE 1 | Applicability
  Does duty apply given collection mode + document type?
  REJECT -> skip this obligation for this section

  GATE 2 | Evidence Sufficiency
  >=2 chunks score>=0.50 AND obligation keywords present?
  REJECT -> finding = needs_review

  STEP 4 | LLM Classification (if budget permits)
  Call LLM with section + chunks -> structured JSON

  GATE 3 | Citation Validation
  chunk_id traceable? Article compatible? No contradictions?
  REJECT -> citation removed; finding may be demoted

  STEP 5 | Deterministic overrides
  Severity normalization, confidence scoring

  GATE 4 | Publication
  Invariants satisfied? No banned tokens? Evidence present?
  REJECT -> finding suppressed to internal_only

  PERSIST finding + citations

POST-LOOP:
  Systemic synthesis -> specialist gaps -> disposition map
  -> publication validator -> compliance score
  -> audit status = complete | review_required | audit_incomplete
```

### 14.2 Sample Data

**Sample Published Finding (JSON)**

```json
{
  "id": "f3a2b1c0-...",
  "audit_id": "a1b2c3d4-...",
  "section_id": "s9e8d7f6-...",
  "issue_key": "missing_retention_period",
  "issue_label": "Retention period",
  "status": "gap",
  "severity": "high",
  "confidence_overall": 0.85,
  "gap_note": "Policy does not specify maximum retention periods per data category.",
  "remediation_note": "Define and document retention periods for each data category in accordance with Article 5(1)(e) GDPR.",
  "primary_legal_anchor": "GDPR Art. 13(2)(a), GDPR Art. 14(2)(a)",
  "citations": [
    {
      "chunk_id": "gdpr-art-5-p-1-sp-e-seg-0-abc123",
      "article_number": "5",
      "paragraph_ref": "1(e)",
      "article_title": "Principles relating to processing of personal data",
      "excerpt": "personal data shall be kept in a form which permits identification of data subjects for no longer than is necessary..."
    }
  ]
}
```

**Sample Remediation Item (JSON)**

```json
{
  "id": "r1a2b3c4-...",
  "audit_id": "a1b2c3d4-...",
  "finding_id": "f3a2b1c0-...",
  "issue_key": "missing_retention_period",
  "issue_label": "Retention period",
  "severity": "high",
  "score_impact_points": 14,
  "order_index": 1,
  "suggestion": {
    "suggested_fix_text": "[Organization] retains personal data for the following periods: Employee records: [X] years after termination...",
    "generation_status": "complete"
  }
}
```

**Sample Audit with Compliance Score (JSON)**

```json
{
  "id": "a1b2c3d4-...",
  "document_id": "d5e6f7a8-...",
  "status": "complete",
  "compliance_score": 43,
  "model_provider": "groq",
  "model_name": "openai/gpt-oss-120b",
  "embedding_model": "BAAI/bge-small-en-v1.5",
  "corpus_version": "gdpr-2016-679-v1"
}
```

### 14.3 Glossary

See Section 1.4 (Definitions, Acronyms, Abbreviations).

### 14.4 TBD List (All Resolved)

| ID | Item | Resolution |
|----|------|------------|
| TBD-1 | Embedding model selection | Resolved: BAAI/bge-small-en-v1.5 via fastembed. 384 dimensions. Score distributions validated against 0.45/0.50 thresholds. |
| TBD-2 | LLM primary selection | Resolved: Groq API (primary), Google Gemini (fallback). Dual-provider with 3 retries each. |
| TBD-3 | Section detection algorithm | Resolved: Regex-based heading detection (HEADING_RE, SECTION_NUM_RE, SUBSECTION_HEADING_RE) with boilerplate filtering and subsection grouping. |
| TBD-4 | Grafana dashboard thresholds | Resolved: Audit duration gauge thresholds at 120s (orange) and 180s (red). |
| TBD-5 | Demo/benchmark documents | Resolved: pp_compliant.pdf (fully compliant privacy notice) and pp_NonCompliant.pdf (privacy notice with 7 intentional gaps). |
| TBD-6 | Threshold calibration | Resolved: 0.45 retry threshold and 0.50 evidence gate validated on benchmark documents with bge-small-en-v1.5 score distributions. |

### 14.5 Gold-Set Evaluation Reference

This appendix defines the canonical evaluation set for CompliTrace benchmark validation.

**Benchmark Document: pp_compliant.pdf**

| Expected Outcome | Value |
|-----------------|-------|
| Overall verdict | compliant_or_minor_only |
| Non-compliant findings | 0 |
| Compliance score | ~100% |
| Citations present | Yes |
| Export dataset | published |

Forbidden findings (must NOT appear): Legal basis disclosure, Data subject rights disclosure, Complaint-right disclosure, Retention disclosure, Transfer safeguards disclosure, Profiling transparency.

**Benchmark Document: pp_NonCompliant.pdf**

| Expected Outcome | Value |
|-----------------|-------|
| Overall verdict | non_compliant |
| Required findings (all 7 must appear) | See below |
| Compliance score | <50% |
| Citations present | Yes |

Required findings:

| # | Issue | Expected Status | Expected Severity |
|---|-------|----------------|-------------------|
| 1 | Legal basis disclosure | Non-compliant | High |
| 2 | Retention disclosure | Non-compliant | High |
| 3 | Transfer safeguards disclosure | Non-compliant | High |
| 4 | Data subject rights disclosure | Non-compliant | High |
| 5 | Complaint-right disclosure | Non-compliant | High |
| 6 | Cookie transparency disclosure | Non-compliant | High |
| 7 | Profiling transparency | Non-compliant | High |

**Stability criterion:** Running each benchmark document three times under identical configuration must reproduce the expected findings in all runs. Any deviation on the 7 required findings for pp_NonCompliant.pdf is treated as a regression.
