# CompliTrace

**CompliTrace** is a GDPR Privacy Policy Pre-Audit Copilot that automates the first-pass review of internal privacy and data-handling policy documents.

It ingests a clean text-based PDF, splits it into logical sections, runs a bounded retrieval-augmented AI audit against a pre-indexed GDPR corpus, generates structured findings with citations, and produces a downloadable PDF gap report.

---

## Overview

Performing a first-pass GDPR compliance review of a company policy is slow, manual, and error-prone. A reviewer must:

- read the full document
- identify relevant GDPR obligations
- compare each section against those obligations
- document gaps with citations and remediation notes

CompliTrace turns that process into a repeatable application workflow with:

- section-level traceability
- retrieval-grounded citations
- persistent audit records
- structured findings
- standardized PDF reporting

This project is intentionally scoped as a **narrow MVP**. It is not a general chatbot, not a legal decision engine, and not a full compliance platform.

---

## Problem Statement

Junior analysts and consultants often spend hours reviewing privacy or data-handling policies against GDPR requirements. The quality of that review depends heavily on experience, and missed articles or weak citations reduce trust in the result.

CompliTrace is designed to support that first-pass review by automating document parsing, GDPR evidence retrieval, structured finding generation, and report creation.

---

## What the System Does

CompliTrace supports the following end-to-end flow:

1. Upload a clean text-based PDF privacy or data-handling policy
2. Extract readable text from the PDF
3. Detect logical section boundaries
4. Store the document and sections
5. Run a bounded AI-driven GDPR gap audit section by section
6. Retrieve relevant GDPR article chunks from a pre-indexed corpus
7. Generate structured findings with citations
8. Persist audit results
9. Generate a downloadable PDF gap report

---

## Scope

### In Scope

- Upload and ingestion of a single privacy or data-handling policy document in PDF format
- Automatic text extraction and section detection
- Section-by-section GDPR gap analysis
- Retrieval of relevant GDPR article chunks from a pre-indexed corpus
- Structured findings per section:
  - compliance status
  - severity
  - gap note
  - remediation note
  - article citations
- Persistence of audit data in a relational database
- PDF report generation and download
- Minimal web frontend for upload, review, findings, and reporting
- Structured logging, Prometheus metrics, and Grafana dashboard
- Containerized local deployment with Docker Compose
- Basic CI/CD pipeline with GitHub Actions

### Out of Scope

- Standards other than GDPR
- OCR for scanned or image-based PDFs
- User authentication and authorization
- Multi-user collaboration
- Real-time streaming output
- Chatbot or conversational Q&A
- Multi-tenant architecture
- Document version comparison
- Export formats other than PDF

---

## Intended Users

### Analyst

A junior compliance analyst, IT auditor, or consultant who:

- uploads a document
- reviews detected sections
- triggers the audit
- reviews findings
- downloads the report

### System Administrator / Developer

The person who:

- runs the stack locally
- monitors the system
- manages infrastructure and observability
- re-indexes the GDPR corpus if needed

---

## Supported Input

The MVP is designed for **internal company privacy or data-handling policy / procedure documents** in **clean, text-extractable PDF form**.

### Examples of suitable input

- Employee Data Handling Policy
- Personal Data Management Procedure
- Privacy and Data Retention Policy
- Internal Procedure for Handling Data Subject Requests

### Unsupported input

- scanned PDFs
- image-based PDFs
- public-facing privacy notices
- contracts / DPAs
- DPIAs
- records of processing spreadsheets
- vendor questionnaires
- multi-document compliance programs

---

## Core Features

### 1. Document Upload and Ingestion

- Accept a single PDF file upload
- Extract readable text
- Detect logical section boundaries
- Persist document metadata and sections

### 2. Sections Review

- Display detected sections before the audit starts
- Allow the user to inspect section titles and previews

### 3. Agentic GDPR Gap Audit

- Process sections in order
- Pre-classify administrative sections where applicable
- Retrieve relevant GDPR evidence
- Apply evidence sufficiency checks
- Classify the section
- Store findings and citations

### 4. Findings Review

- Show all findings in a structured table
- Display status and severity
- Allow detailed inspection of section text, evidence, notes, and citations

### 5. Gap Report Generation

- Generate a structured PDF gap report
- Include executive summary, per-section findings, and citation evidence

### 6. Observability

- Expose Prometheus metrics from all services
- Emit structured JSON logs
- Visualize system metrics in Grafana

---

## AI and RAG Design

CompliTrace uses a **bounded AI agent** rather than an open-ended assistant.

The system is designed so that the model does not invent legal citations from memory. Every substantive finding must be grounded in retrieved GDPR evidence.

### Agent workflow

For each section, the agent performs:

1. not-applicable pre-check
2. topic inference
3. dynamic retrieval query generation
4. top-k GDPR retrieval
5. retrieval quality evaluation
6. optional retry
7. evidence sufficiency gate
8. classification
9. finding generation
10. citation validation
11. persistence

### Valid finding statuses

- `compliant`
- `partial`
- `gap`
- `needs review`
- `not applicable`

### Severity values

- `low`
- `medium`
- `high`

### Citation rules

Every citation must:

- match an article present in the retrieved top-k set
- match paragraph metadata when applicable
- include a traceable chunk identifier

If a citation fails validation, it is rejected before persistence.

---

## Technology Stack

### Frontend

- React
- Vite
- Tailwind CSS

### Backend

- FastAPI
- Python-based service architecture

### Databases and Storage

- PostgreSQL for relational persistence
- Qdrant for vector search
- Docker volumes for uploaded PDFs and generated reports

### AI / Retrieval

- Groq API as primary LLM provider
- Gemini Flash as alternative provider
- Ollama as documented local fallback
- `sentence-transformers/all-MiniLM-L6-v2` for embeddings
- Semantic retrieval over a pre-indexed GDPR corpus

### Observability

- Prometheus
- Grafana
- Structured JSON logs

### DevOps

- Docker
- Docker Compose
- GitHub Actions

---

## Architecture

CompliTrace uses a **microservice architecture** with synchronous REST communication between services.

### Services

#### Document Ingestion Service

Responsible for:

- PDF upload
- text extraction
- section detection
- persistence of documents and sections

#### Regulatory Knowledge Service

Responsible for:

- storing GDPR embeddings in Qdrant
- serving semantic retrieval requests
- returning ranked GDPR chunks with similarity scores and citation metadata

#### Agent Orchestration Service

Responsible for:

- managing audit lifecycle
- running the bounded agent loop
- validating citations
- persisting findings and provenance
- generating PDF reports

### Infrastructure Components

- PostgreSQL
- Qdrant
- Prometheus
- Grafana

---

## Frontend Views

The frontend consists of exactly four views:

### Upload Page

- file input
- upload button
- upload status indicator

### Sections Review Page

- ordered list of detected sections
- title, content preview, and page range where available
- action to trigger the audit

### Findings Page

- findings table
- status badges
- severity indicators
- detail panel on click

### Report Page

- summary cards
- counts by status
- PDF download button

---

## API Surface

### Document Ingestion Service

- `POST /documents`
- `GET /documents/{id}`
- `GET /documents/{id}/sections`

### Regulatory Knowledge Service

- `POST /search`
- `GET /chunks/{id}`

### Agent Orchestration Service

- `POST /audits`
- `GET /audits/{id}`
- `GET /audits/{id}/findings`
- `POST /audits/{id}/report`
- `GET /audits/{id}/report`
- `GET /audits/{id}/report/download`

---

## Data Model

The relational model includes the following main tables:

- `documents`
- `sections`
- `audits`
- `findings`
- `finding_citations`
- `reports`

An optional `regulation_chunks` mirror may also exist in PostgreSQL for traceability, while vector embeddings are stored in Qdrant.

### Core entity relationships

- one document has many sections
- one document can have many audits
- one audit produces many findings
- one finding belongs to one section
- one finding can have many citations
- one audit can generate one report

### Audit provenance

Each audit stores provenance metadata including:

- model provider
- model name
- model temperature
- prompt template version
- embedding model
- corpus version

---

## Status Model

### Document status

- `pending`
- `parsed`
- `failed`

### Audit status

- `pending`
- `running`
- `complete`
- `failed`

### Finding status

- `compliant`
- `partial`
- `gap`
- `needs review`
- `not applicable`

### Report status

- `pending`
- `ready`
- `failed`

---

## Non-Functional Targets

The MVP targets the following performance and behavior constraints:

- retrieval latency: **≤ 500 ms** per query
- document parsing time: **≤ 10 s** for a 10-page text PDF
- LLM inference latency: **≤ 10 s** per section
- full audit duration: **≤ 3 min** for a 10-section document
- PDF report generation: **≤ 15 s**
- frontend page load time: **≤ 3 s**

Additional goals:

- citation validation must be fully enforced
- logs must be structured JSON
- all services must expose health and metrics endpoints
- the full stack must start with one Docker Compose command

---

## Observability

All services expose:

- `/health`
- `/metrics`

Prometheus scrapes service metrics, and Grafana visualizes:

- retrieval latency
- audit duration
- findings by status

Logs are emitted as structured JSON to standard output.

Key monitored signals include:

- retrieval call count
- retrieval retry count
- audit duration
- LLM inference latency
- evidence gate failures
- citation validation failures
- findings count by status

---

## Deployment

The entire system is designed to run locally with Docker Compose.

### Expected services

- ingestion
- knowledge
- orchestration
- postgres
- qdrant
- prometheus
- grafana

### Environment configuration
Expected environment variables include:

LLM API keys
- database connection settings
- service URLs
- model configuration

---
## Demo Workflow
A complete demo should follow this path:

- Upload a clean internal privacy or data-handling policy PDF
- Review extracted sections
- Trigger the GDPR gap audit
- Inspect findings and evidence
- Generate and download the PDF report

The SRS expects the entire live demo workflow to be completable in under 6 minutes.

## Acceptance Baseline
The MVP is considered complete when it can:

- upload and parse a valid policy PDF
- detect and display sections
- complete an audit on the predefined demo document
- generate findings with valid statuses and valid citations
- generate and download a PDF report
- expose valid Prometheus metrics for all services
- show live Grafana dashboard data
- run end-to-end through Docker Compose
- pass the GitHub Actions pipeline


## Limitations
This is an intentionally narrow MVP.
Known limitations include:

- only clean, text-based PDFs are supported
- only GDPR is supported
- no OCR
- no user authentication or access control
- no concurrent audits
- no multi-user support
- no document version comparison
- no chat interface
- findings are not legal advice
- the system is designed for first-pass analyst-assisted review only


## Future Improvements
Potential future directions include:

- support for additional regulatory standards
- OCR pipeline for scanned documents
- authentication and access control
- concurrent audit support
- stronger evaluation and calibration tooling
- production deployment hardening
- richer document parsing
- formal topic-to-obligation modeling for more consistent classification
