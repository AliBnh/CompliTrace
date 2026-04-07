# Day 9–12 Audit Quality Remediation Plan

## Goal
Raise GDPR audit output quality from "scanner-grade" to "auditor-grade" by improving legal mapping precision, traceability, deduplication, and severity consistency without document-specific hardcoding.

## Current pipeline surfaces to modify
- `apps/orchestration-service/app/services/audit_runner.py`: finding generation, citation gating, status fallback behavior, severity assignment, and final post-processing.
- `apps/orchestration-service/app/services/llm.py`: issue prompts and model call contracts for legal reasoning output.
- `apps/orchestration-service/app/schemas/audit.py`: finding schema (reasoning fields, confidence, assessment type, clustering metadata).
- `apps/orchestration-service/app/services/reports.py`: report output shaping and executive-summary rendering.
- `apps/orchestration-service/tests/`: regression tests for citation fit, clustering, and severity consistency.

## Workstreams

### 1) Legal mapping precision gate (highest ROI)
**Objective:** Ensure each issue type maps to legally relevant GDPR anchors, not only citation-valid chunks.

**Implementation:**
1. Add an issue taxonomy constant with required/preferred article families in `audit_runner.py`.
2. Add a `claim_citation_fit_score` computed from:
   - issue-type/article compatibility,
   - paragraph-level compatibility,
   - semantic overlap between claim text and retrieved legal excerpt.
3. Enforce minimum fit score for a substantive finding.
4. Require one primary legal anchor article per issue; keep weaker related citations as optional secondary references.

**Acceptance criteria:**
- Complaint-right findings require transparency-rights anchors (e.g., Article 13(2)(d)/14(2)(e) equivalent families).
- Transfer findings reject subject-access-only anchors when transfer disclosures are asserted.

### 2) Source-mode gating (Article 13 vs 14)
**Objective:** Stop overusing Article 14 when indirect collection is unproven.

**Implementation:**
1. Add source-mode inference output object in `audit_runner.py` with `mode` + `confidence` + `evidence`.
2. Introduce deterministic rule:
   - direct mode: prioritize Article 13 obligations,
   - indirect mode: Article 14 allowed,
   - uncertain mode: downgrade to "not assessable" instead of dual-citing as if confirmed.
3. Add schema fields in `schemas/audit.py` for source-mode rationale.

**Acceptance criteria:**
- Findings that cite 14-only obligations include explicit indirect-collection evidence.

### 3) Structured reasoning traceability
**Objective:** Make every substantive finding reviewable as fact -> law -> conclusion.

**Implementation:**
1. Extend finding schema in `schemas/audit.py` with required fields:
   - `policy_evidence_excerpt`,
   - `legal_requirement`,
   - `gap_reasoning`,
   - `confidence_level`,
   - `assessment_type` (`confirmed`, `probable`, `not_assessable`).
2. Update LLM output contract in `llm.py` and validation/parsing logic in `audit_runner.py`.
3. Reject substantive findings missing any required reasoning field.

**Acceptance criteria:**
- No substantive finding reaches report output without all reasoning chain fields.

### 4) Deduplication and cross-section consolidation
**Objective:** Eliminate repetitive findings while preserving section-level provenance.

**Implementation:**
1. Add post-processing consolidator in `audit_runner.py`:
   - normalize issue signatures,
   - cluster near-duplicates (issue type + missing obligation + legal anchor similarity),
   - merge into one primary finding with `affected_sections` metadata.
2. Update `reports.py` to render consolidated findings first and section drill-down second.

**Acceptance criteria:**
- Repeated missing-transparency findings across sections collapse into one consolidated item with section list.

### 5) Severity matrix normalization
**Objective:** Make severity deterministic and explainable.

**Implementation:**
1. Add severity matrix in `audit_runner.py` keyed by issue class and obligation criticality.
2. Require explicit `severity_rationale` field in schema.
3. Allow downgrade only if mitigating evidence is present.

**Acceptance criteria:**
- Same issue category under equivalent evidence yields consistent severity.

### 6) Low-information fallback handling
**Objective:** Replace "junk" needs-review rows with useful diagnostics.

**Implementation:**
1. If citation validation fails after retries, emit a bounded diagnostic object with:
   - failed prerequisite (e.g., retrieval insufficiency, source-mode ambiguity),
   - required next action,
   - non-substantive classification.
2. Configure `reports.py` to hide low-information diagnostics from executive summary by default.

**Acceptance criteria:**
- "Needs review" entries include actionable diagnostic metadata, not generic rejection text.

### 7) Profiling-tier reasoning
**Objective:** Distinguish profiling transparency from Article 22-like automated decisioning concerns.

**Implementation:**
1. Add profiling tier detector in `audit_runner.py`:
   - profiling present,
   - automated decision-making present,
   - legal/similarly significant effect present.
2. Gate obligations and remediations by tier.

**Acceptance criteria:**
- Findings differentiate generic profiling disclosure gaps from high-impact automated decisioning gaps.

## Test plan additions
Create/extend tests in `apps/orchestration-service/tests/`:
1. **Article-fit tests**: wrong-article mappings are rejected.
2. **Source-mode tests**: uncertain collection mode yields `not_assessable`, not forced dual citation.
3. **Reasoning completeness tests**: substantive finding must include all trace fields.
4. **Dedup tests**: repeated issue across sections consolidates.
5. **Severity consistency tests**: same fact pattern => same severity.
6. **Fallback diagnostic tests**: low-confidence outputs produce actionable diagnostics.

## Delivery sequencing

### Day 9
- Implement legal mapping precision gate + tests.
- Implement source-mode gating + tests.

### Day 10
- Add structured reasoning schema and LLM contract updates.
- Add validation hard-fail for incomplete reasoning.

### Day 11
- Implement dedup consolidation and report rendering updates.
- Add severity matrix and rationale field.

### Day 12
- Add low-information diagnostic fallback.
- Add profiling-tier detector.
- Run full regression and tune thresholds.

## Success metrics
- >= 90% of substantive findings pass manual legal-anchor review.
- >= 95% substantive findings contain complete fact->law->conclusion chain.
- >= 50% reduction in duplicate findings in executive report output.
- <= 10% non-actionable "needs review" rows.
- Severity disagreement between reruns on same input < 5%.
