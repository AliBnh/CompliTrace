## 0. The single most important conclusion

Your system does **not** have only “finding accuracy” problems. It has four intertwined problem classes:

1. **Legal-reasoning defects**
2. **Cross-stage truth inconsistency**
3. **Presentation/export contract failures**
4. **Benchmark governance/testing gaps**

Until all four are fixed together, you will keep getting regressions.

---

# I. Core architecture and truth-layer blockers

## 1. No single authoritative final decision ledger

Different layers re-decide truth:

- audit runner
- review reconciliation
- publication validation
- routes
- frontend normalization
- report generation

### Why this is a blocker

The same issue can be:

- created
- downgraded
- suppressed
- reintroduced
- exported differently

That is why you keep seeing contradictions between analysis, review, published, and report.

### Required fix

Create one backend artifact per audit:

`final_decision_ledger`

Each row must represent one canonical issue and contain:

- issue key
- section scope or document-wide scope
- final status
- final severity
- final issue label
- final legal anchors
- final evidence refs
- publication eligibility
- review visibility
- report/export eligibility
- reason code

All downstream surfaces must derive from this only.

---

## 2. No single authoritative export contract

Frontend computes report readiness and dataset selection locally, while backend report generation has its own selection and transformation logic.

### Why this is a blocker

UI can say one thing, PDF can export another.

### Required fix

Backend must return a single `export_contract` object containing:

- dataset_used
- export_allowed
- blocker_reasons
- counts by status
- included finding ids
- document-wide finding ids
- section finding ids
- readiness timestamp

Frontend may display it, but must not invent its own export truth.

---

## 3. Backend publication logic is too fragmented

Publication truth currently depends on:

- candidate spotting
- evidence gates
- citation compatibility
- document-wide synthesis
- final disposition maps
- release validators
- grouped review buckets
- route-layer publication guards

### Why this is a blocker

It makes outcomes unstable and hard to reason about.

### Required fix

All publication-state decisions must be derived once into the final decision ledger.
Suppression should become an exception path, not the normal path.

---

## 4. Frontend normalization can hide backend truth defects

The frontend normalization layer sanitizes and remaps backend output before rendering/exporting.

### Why this is a blocker

The UI can look “cleaner” while the backend is still wrong.

### Required fix

In benchmark mode, expose three comparable datasets:

- raw backend findings
- normalized frontend findings
- export payload findings

All three must be checked against benchmark truth.

---

# II. Benchmark governance blockers

## 5. Benchmark fixtures are not governed tightly enough

You already saw test confusion from document naming and flow interpretation.

### Why this is a blocker

If fixture truth is not locked, you cannot trust regression results.

### Required fix

Create locked fixtures:

- `benchmark_notice_compliant`
- `benchmark_notice_noncompliant`

For each, store:

- expected overall verdict
- required findings
- forbidden findings
- expected counts by family
- expected report counts
- expected citations presence
- expected export dataset label

---

## 6. No full end-to-end benchmark acceptance suite

Right now you have partial logic checks and UI checks, but not one authoritative acceptance test from ingestion to PDF.

### Required fix

For each benchmark fixture, assert:

- raw sections extracted
- backend analysis output
- backend review output
- backend published output
- frontend normalized findings
- report preview
- exported PDF text

All must match expectations.

---

# III. Benchmark truth failures: compliant notice false positives

Reference truth: the compliant benchmark is a strong privacy notice and should not get major findings for legal basis, rights, complaint right, retention, transfers, or profiling.

## 7. Legal basis false positives on compliant notice

The compliant notice explicitly contains legal bases and purpose-linked processing explanations, yet the system still produces section-level legal basis problems.

### Required fix

Add upstream duty-satisfaction logic:

- dedicated legal basis section present
- purpose-to-basis mapping present
  = satisfied

Once satisfied, no downstream legal-basis issue may be created.

---

## 8. Rights disclosure false positives on compliant notice

The compliant notice includes full data subject rights, yet rights issues still appear.

### Required fix

Implement deterministic rights completeness detection:

- access
- rectification
- erasure
- restriction
- objection
- portability
- complaint right
- request/response handling

If satisfied, block rights issue creation upstream.

---

## 9. Complaint-right false positives on compliant notice

The compliant notice explicitly includes the right to lodge a complaint with a supervisory authority, yet complaint-right issues still surface.

### Required fix

Complaint-right should be a protected duty:

- if explicit complaint-right clause exists, no complaint-right issue may be created anywhere.

---

## 10. Retention false positives on compliant notice

The compliant notice includes category-based retention schedules and criteria, yet retention issues still appear.

### Required fix

Retention validator must mark compliant when it finds:

- concrete periods
- or objective criteria
- or category-based schedules
  in sufficient detail.

---

## 11. Transfer false positives on compliant notice

The compliant notice explains transfer safeguards. It should not receive transfer-gap findings.

### Required fix

Transfer validator must recognize:

- adequacy references
- SCC-style safeguard references
- mechanism explanation
- supplementary safeguard wording where present

---

## 12. Profiling false positives on compliant notice

The compliant notice includes profiling/ADM explanation and human review limitation, but profiling-related concern still leaks into outputs.

### Required fix

Profiling validator must mark satisfied when it finds:

- profiling existence
- input categories
- logic involved
- significance/consequences
- human review limitation on legal/similarly significant effects

---

## 13. Article 14 / indirect-collection threshold too aggressive

The compliant benchmark references indirect collection through integrations, but not in a way that justifies a major Article 14 finding. Yet the system escalates it.

### Required fix

Article 14 should trigger only where:

- indirect collection is actually material to the notice
- and required source/category/source-type disclosures are materially missing

---

# IV. Benchmark truth failures: non-compliant notice false negatives or misframing

Reference truth: the non-compliant benchmark should clearly trigger major findings for invalid consent/legal basis, indefinite retention, weak transfer safeguards, incomplete rights, missing complaint-right, cookies/tracking issues, and profiling issues.

## 14. Retention defect is underdetected or misframed

The non-compliant notice contains explicit excessive/indefinite retention language, but the system does not consistently produce the right substantive finding.

### Required fix

Hard-promote retention when phrases indicate:

- indefinite retention
- extended historical retention
- indefinite backups/logs/archive retention

Map to:

- Article 13(2)(a)
- Article 5(1)(e)

---

## 15. Cookies/tracking defect is underdetected and misclassified

The non-compliant notice describes non-essential tracking technologies and adtech behavior without proper consent transparency, but the system often collapses that into legal basis or weak partials.

### Required fix

Dedicated cookies/tracking family:

- non-essential tracking consent
- withdrawal/preference mechanism
- tracking scope disclosure
- third-party advertising ecosystem transparency

---

## 16. Recipients/marketing-sharing issue is underdetected

The non-compliant notice expressly references marketing partners, ad networks, affiliates, and sync-like recipient behavior. This is not being surfaced strongly enough.

### Required fix

Dedicated recipients/third-party sharing family:

- marketing recipients
- ad network recipients
- cross-platform audience sync
- affiliate sharing
  with linkage to legal-basis/cookies if relevant

---

## 17. Rights issue is misframed as absence rather than incompleteness

The non-compliant notice mentions some rights, but incompletely. Your system tends to frame that as full absence.

### Required fix

Split rights outcomes into:

- absent rights notice
- incomplete rights notice
- rights present but unusable wording

---

## 18. Complaint-right issue should always surface strongly on the non-compliant benchmark

This is one of the clearest missing duties and should always be a major finding.

### Required fix

Make complaint-right a required benchmark finding for the non-compliant fixture.

---

## 19. Profiling issue should always surface under profiling, not under legal basis

The non-compliant notice’s automated scoring/risk/profiling defect is real, but it must be labeled and explained as profiling, not legal basis.

### Required fix

Dedicated profiling family with dedicated templates and severity.

---

## 20. Transfer safeguard issue should surface under transfer safeguards, not legal basis

The non-compliant notice’s transfer clause is defective, but the system currently spreads that logic into generic legal-basis framing.

### Required fix

Dedicated transfer safeguards family with dedicated evidence and recommendations.

---

# V. Taxonomy, issue identity, and reasoning coherence blockers

## 21. Canonical issue taxonomy is still not enforced end-to-end

You still have inconsistent issue naming and collapse of unrelated issues into “legal basis disclosure.”

### Required fix

One shared issue registry used by:

- backend finding generation
- frontend normalization
- report generation
- PDF labels
- severity rules
- recommendation templates
- legal anchors
- evidence renderers

Allowed canonical issue set:

- Legal basis disclosure
- Data subject rights disclosure
- Complaint-right disclosure
- Retention disclosure
- Transfer safeguards disclosure
- Profiling transparency
- Cookie transparency disclosure
- Contact information disclosure
- Governance and compliance disclosure
- Purpose specificity disclosure
- Recipients disclosure
- Role allocation disclosure

---

## 22. Title / issue / explanation / recommendation / evidence are still semantically misaligned

A finding can still say one thing in the title and another in the explanation or evidence.

### Required fix

All visible finding fields must be generated from one normalized issue object:

- issue_type
- issue_subtype
- status
- severity
- evidence mode
- recommendation template

No cross-family text stitching.

---

## 23. Legal basis logic still absorbs unrelated issues

This remains the single biggest taxonomy failure.

### Required fix

Split legal basis into:

- missing lawful basis
- invalid consent wording
- purpose-to-basis mapping defect

Do not allow cookies, transfers, profiling, contact, or rights to inherit the legal basis family unless that is truly the core issue.

---

## 24. Contact information logic is still too weak and too unstable

The compliant benchmark has correct contact/DPO/rep details but still gets contact-related fallout. The non-compliant benchmark gets clumsy contact findings.

### Required fix

Deterministic contact-duty validator:

- controller identity
- controller contact
- DPO contact
- EU representative when relevant

If satisfied, no contact issue creation.

---

## 25. Subtyping of obligations is still missing

The system needs more than yes/no or partial/non-compliant.

### Required fix

Add explicit issue subtypes:

- missing
- incomplete
- invalid
- present but unclear
- present but overbroad
- present but contradictory

Map those to final statuses and recommendation templates.

---

# VI. Evidence, citation, and traceability blockers

## 26. Empty citations remain a hard blocker

You already have evidence/citation infrastructure in the backend models, but surfaced findings still lack proper citations.

### Required fix

No surfaced finding unless it has:

- at least one evidence ref
- at least one citation OR explicit absence statement
- source section title
- source section id/ref

---

## 27. Evidence is still not citation-grade

Synthetic prose and backend notes still appear where direct excerpts or explicit absence statements should appear.

### Required fix

Allowed evidence modes only:

1. direct excerpt
2. explicit absence statement after full-document review

Everything else must be blocked from render/export.

---

## 28. Internal/debug text still leaks into evidence and reasoning

Phrases equivalent to:

- suppression
- reconciliation
- strict gate
- validator
- internal-only
  still contaminate outputs.

### Required fix

Hard sanitizer for all non-debug surfaces.
If forbidden phrases remain, the finding cannot be published or exported.

---

## 29. Evidence and reasoning are still mixed

The system sometimes uses reasoning as if it were evidence.

### Required fix

Strict field discipline:

- Why this matters = legal reasoning
- Evidence = excerpt or explicit absence statement only

---

# VII. Cross-stage status and severity blockers

## 30. Status logic is still too coarse and unstable

The same duty can appear as:

- partial
- non-compliant
- not assessable
  with no clear threshold logic.

### Required fix

Define deterministic thresholds per issue subtype and enforce them across stages.

---

## 31. Severity calibration is still not correct

You still get severity that is either inflated, flattened, or semantically wrong.

### Required fix

Base severity by canonical issue family:

- High: legal basis, rights, complaint-right, transfer safeguards, profiling
- Medium: retention, recipients, purpose specificity, role allocation
- Low: drafting-only issues

Then modify by:

- evidence strength
- actual status

---

## 32. Compliant and Not applicable must not visually read like active risk

In UI flows, compliant/not-applicable rows can still look severe.

### Required fix

Hide or mute severity for:

- Compliant
- Not applicable

---

## 33. Not-assessable is still overused and misused

This is not just model uncertainty. The repo shows deterministic gates are contributing to it.

### Required fix

Use not-assessable only when the text genuinely lacks enough information.
Explicit unlawful language must override later downgrades unless contradicted by compliant text elsewhere.

---

# VIII. Frontend modeling and UX blockers

## 34. Section titles are still not client-grade

Primary visible titles still include machine numbering.

### Required fix

Primary title = clean human section title only.
Numbering, if kept, must be secondary metadata only.

---

## 35. Section table is still not a true section-summary model

It is improved but still behaves partly like an issue table.

### Required fix

One row per section with:

- clean section title
- overall status
- highest applicable severity
- primary issue
- issue count

Right panel then shows issue-level detail.

---

## 36. Document-wide findings block still needs dedupe and stronger modeling

It improved, but repeated/duplicative or under-contextualized cards can still appear.

### Required fix

Deduplicate document-wide findings by canonical issue key and render one card per distinct issue.

---

## 37. Findings counts are still not guaranteed to reflect legally distinct issues

If taxonomy and aggregation are wrong, counts become misleading.

### Required fix

Counts must be computed over normalized, legally distinct findings, not repeated section symptoms.

---

## 38. Right panel should render only validated findings

Some right-panel fields are still stronger or weaker than others in quality.

### Required fix

Only render a finding in production UI if:

- issue family valid
- status valid
- evidence valid
- explanation valid
- recommendation valid

Otherwise keep it internal/debug only.

---

## 39. Report Center still needs to be a true export review surface

It improved, but still needs stronger export trust features.

### Required fix

Show:

- dataset used
- export readiness state
- blocker reasons
- preview findings
- proof that export payload matches preview

---

## 40. Export readiness must be backend-authoritative

The repo analysis shows frontend currently calculates readiness locally.

### Required fix

Backend returns:

- export_allowed
- blocker_reasons
- dataset_used
- counts
- finding ids

Frontend displays that only.

---

## 41. Chips, card hierarchy, spacing, and density still need final polish

This is lower priority than the logic issues, but still necessary before client release.

### Required fix

Final UX pass after logic freeze:

- chip widths
- no broken wrapping
- stronger distinction between document-wide and section findings
- cleaner report preview layout
- improved typography hierarchy

---

# IX. Report and PDF-specific blockers

## 42. PDF export still uses the wrong dataset

This is still the worst defect. Both benchmark PDFs exported false empty reports while the UI showed findings.

### Required fix

PDF must consume `reportExportFindings` only.

---

## 43. PDF template still does not reflect the actual visible preview

Even when report preview looks plausible, the PDF does not match it.

### Required fix

PDF export must be generated from the exact same backend contract object used to build the report preview.

---

## 44. Custom PDF writer needs semantic golden-file tests

The repo uses a custom low-level PDF writer.

### Required fix

For each benchmark fixture:

- generate PDF
- parse text from PDF
- assert:
  - correct dataset label
  - correct counts
  - required findings present
  - forbidden findings absent
  - no debug/internal text

---

# X. Testing and release blockers

## 45. No benchmark-protected acceptance rules for compliant fixture

Without explicit forbidden findings, compliant regressions will keep recurring.

### Required fix

For the compliant benchmark, forbid:

- major legal basis finding
- rights finding
- complaint-right finding
- retention finding
- transfer safeguards finding
- profiling finding

unless benchmark truth is updated.

---

## 46. No benchmark-protected required-finding set for non-compliant fixture

Without explicit required findings, underdetection will keep recurring.

### Required fix

For the non-compliant benchmark, require:

- legal basis / invalid consent defect
- retention defect
- transfer safeguard defect
- rights defect
- complaint-right defect
- cookies/tracking defect
- profiling defect

---

## 47. No raw-backend vs normalized-frontend vs export-payload comparison

This is now necessary because the architecture has multiple transformation layers.

### Required fix

Every benchmark test must compare:

- raw backend findings
- normalized frontend findings
- report preview findings
- exported PDF findings

---

## 48. No final release gate based on benchmark passage

You need one binary release condition.

### Required fix

Release cannot proceed unless:

- compliant benchmark passes with no forbidden major findings
- non-compliant benchmark passes with all required major findings
- report preview and PDF match on both
- no internal/debug text appears anywhere client-facing

---

# Final implementation order

If you want the fastest path to a production-capable system, do the fixes in this order:

1. Create `final_decision_ledger` in backend
2. Create backend-authoritative `export_contract`
3. Fix PDF to use `reportExportFindings` only
4. Lock benchmark fixtures and expected outcomes
5. Enforce canonical issue taxonomy end-to-end
6. Fix compliant false positives
7. Fix non-compliant false negatives / misframing
8. Enforce evidence/citation rules
9. Fix status/severity logic
10. Finish section-summary and document-wide modeling
11. Upgrade Report Center
12. Final UX polish pass
13. Add golden-file PDF tests and full end-to-end benchmark gates
