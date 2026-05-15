import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import ts from 'typescript'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const srcPath = path.join(root, 'src', 'lib', 'presentation.ts')
const source = fs.readFileSync(srcPath, 'utf8')
const findingsPageSource = fs.readFileSync(path.join(root, 'src', 'features', 'findings', 'FindingsPage.tsx'), 'utf8')
assert.ok(findingsPageSource.includes('No published findings for this audit.'))

const transpiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 },
  fileName: srcPath,
}).outputText

const tempFile = path.join(root, '.tmp.presentation.test.mjs')
fs.writeFileSync(tempFile, transpiled, 'utf8')
const mod = await import(pathToFileURL(tempFile).href)

const sectionsById = {
  'sec-1': { id: 'sec-1', section_order: 4, section_title: '2. Categories of Personal Data' },
  'sec-2': { id: 'sec-2', section_order: 6, section_title: 'International Transfers' },
  'sec-3': { id: 'sec-3', section_order: 9, section_title: 'Data Subject Rights' },
}

const publishedRows = [
  {
    id: 'f1',
    section_id: 'sec-1',
    issue_key: 'missing_legal_basis',
    issue_label: 'Legal basis disclosure',
    status: 'gap',
    severity: null,
    gap_note: 'Section ().',
    remediation_note: 'Add lawful basis mapping.',
    citations: [{ excerpt: 'We process data for support and billing.' }],
    primary_legal_anchor: ['GDPR Article 13(1)(c)'],
  },
  {
    id: 'f2',
    section_id: 'sec-2',
    issue_key: 'profiling_disclosure_gap',
    issue_label: 'Automated decision-making / profiling',
    status: 'gap',
    severity: null,
    gap_note: 'Profiling is not fully described.',
    remediation_note: 'Add profiling details.',
    citations: [{ excerpt: 'Profiling effects are not described.' }],
    primary_legal_anchor: ['GDPR Article 13(2)(f)'],
  },
  {
    id: 'f3',
    section_id: 'sec-2',
    issue_key: 'missing_transfer_notice',
    issue_label: 'International transfers',
    status: 'gap',
    severity: null,
    gap_note: 'Transfer safeguards are not described.',
    remediation_note: 'Add transfer safeguards.',
    citations: [{ excerpt: 'Transfer wording lacks safeguards.' }],
    primary_legal_anchor: ['GDPR Article 13(1)(f)'],
  },
  {
    id: 'f4',
    section_id: 'sec-3',
    issue_key: 'missing_controller_contact',
    issue_label: 'Contact information',
    status: 'gap',
    severity: null,
    gap_note: 'Contact method not visible.',
    remediation_note: 'Add contact details.',
    citations: [{ excerpt: 'No direct contact route is listed.' }],
    primary_legal_anchor: ['GDPR Article 13(1)(a)'],
  },
  {
    id: 'f5',
    section_id: 'sec-3',
    issue_key: 'purpose_specificity_gap',
    issue_label: 'Purpose specificity',
    status: 'partial',
    severity: null,
    gap_note: 'Purpose mapping is too broad.',
    remediation_note: 'Clarify purpose mapping.',
    citations: [{ excerpt: 'Purpose text exists.' }],
    primary_legal_anchor: ['GDPR Article 5(1)(b)'],
  },
  {
    id: 'f6',
    section_id: 'sec-1',
    issue_key: 'future_new_gdpr_obligation',
    issue_label: 'Binding corporate rules disclosure',
    status: 'gap',
    severity: 'medium',
    gap_note: 'BCR transfer mechanism not disclosed.',
    remediation_note: 'Add BCR disclosure.',
    citations: [{ excerpt: 'BCR reference missing.' }],
    primary_legal_anchor: ['GDPR Article 47'],
  },
  {
    id: 'f7',
    section_id: 'systemic:lawful_basis_and_consent',
    issue_key: 'lawful_basis_and_consent',
    issue_label: 'Lawful basis and consent',
    status: 'gap',
    severity: 'high',
    gap_note: 'The notice does not state the lawful basis for processing and the consent mechanism is deficient.',
    remediation_note: 'Identify the Article 6(1) ground for each processing purpose and ensure consent is freely given, specific and unambiguous.',
    citations: [{ excerpt: 'We process your data to improve our services.' }],
    primary_legal_anchor: ['GDPR Article 13(1)(c)', 'GDPR Article 6(1)'],
  },
]

const reviewRows = [
  { item_kind: 'review_block', id: 'rb1', section_id: 'review:block', final_disposition: 'gap', reason: 'withheld by final publication validator' },
  { item_kind: 'finding', id: 'r1', section_id: 'sec-2', issue_type: 'missing_transfer_notice', status: 'gap', gap_note: 'candidate_issue transfer rationale', remediation_note: 'Add transfer safeguards', citations: [{ chunk_id: 'c1', article_number: '13', paragraph_ref: '1', article_title: 'Info', excerpt: 'Transfer wording lacks safeguards.' }] },
  { item_kind: 'finding', id: 'r2', section_id: 'sec-2', issue_type: 'profiling_disclosure_gap', status: 'partial', gap_note: '[debug] profiling_without_required_explanation', remediation_note: 'Expand profiling section', citations: [{ chunk_id: 'c2', article_number: '13', paragraph_ref: '2', article_title: 'Info', excerpt: 'Profiling effects are not described.' }] },
  { item_kind: 'finding', id: 'r3', section_id: 'systemic:missing_retention_period', issue_type: 'missing_retention_period', status: 'gap', gap_note: 'Substantive disclosure signal detected', remediation_note: 'Add retention timelines' },
  { item_kind: 'finding', id: 'r4', section_id: 'sec-3', issue_type: 'purpose_specificity_gap', status: 'compliant', gap_note: 'legal gate reconciliation', remediation_note: 'Clarify purpose mapping', reason: '', citations: [{ chunk_id: 'c3', article_number: '5', paragraph_ref: null, article_title: 'Principles', excerpt: 'Purpose text exists.' }] },
]

const analysisRows = [
  { id: 'a1', section_id: 'sec-2', analysis_type: 'completeness_outcome', issue_type: 'missing_transfer_notice', status_candidate: 'candidate_gap', gap_note: 'possible gap filtered by (.)', remediation_note: 'check', citations: [] },
]

const presentation = mod.buildFindingsPresentation({
  publishedRows,
  reviewRows,
  analysisRows,
  sectionsById,
  publishedBlocked: false,
})

// dataset contract: report/export must use final published findings dataset
assert.deepEqual(presentation.reportExportFindings, presentation.publishedVisibleFindings)
assert.equal(presentation.reportDatasetLabel, 'Final published findings')

// published findings use backend's issue_label directly — no 'Unknown issue classification'
const labels = presentation.reportExportFindings.flatMap((row) => row.issues.map((x) => x.issueLabel))
assert.ok(!labels.includes('Unknown issue classification'), 'Unknown issue classification must never appear in published output')
assert.ok(!labels.includes('Transparency disclosure'))
assert.ok(!labels.includes('Compliance disclosure issue'))
assert.ok(labels.includes('Automated decision-making / profiling'))
assert.ok(labels.includes('International transfers'))
assert.ok(labels.includes('Contact information'))
assert.ok(labels.includes('Purpose specificity'))
// backend-label passthrough: unknown issue_key uses issue_label from backend, not fallback
assert.ok(labels.includes('Binding corporate rules disclosure'), 'backend-provided label for unknown issue_key must be used directly')
// domain-consolidated finding must surface its label correctly
assert.ok(labels.includes('Lawful basis and consent'), 'lawful_basis_and_consent consolidated finding must surface its label')
// all published labels must be non-empty clean strings
for (const label of labels) {
  assert.ok(label && label.trim().length > 0, `empty label in published output`)
}

// section summary model checks
const sectionRows = presentation.reportExportFindings.filter((row) => row.scope === 'Section')
assert.equal(sectionRows.length, new Set(sectionRows.map((row) => row.sectionId)).size)
for (const row of sectionRows) {
  assert.equal(row.issueCount, row.issues.length)
  assert.equal(row.primaryIssueLabel, row.issues[0].issueLabel)
}

// document finding model checks
const split = mod.splitFindingsByScope(presentation.reportExportFindings)
assert.ok(split.sectionFindings.length > 0)
assert.equal(split.documentFindings.length, new Set(split.documentFindings.map((x) => x.issueKey)).size)
assert.ok(split.sectionFindings.every((row) => !row.sectionId.startsWith('systemic:')))

// clean section titles (no machine prefix)
for (const row of split.sectionFindings) {
  assert.ok(!/^section\s+\d+:/i.test(row.sectionTitle), `machine numbered title leaked: ${row.sectionTitle}`)
}

// copy sanity + human evidence
for (const row of presentation.reportExportFindings) {
  for (const issue of row.issues) {
    assert.ok(issue.whyThisMatters.trim().length > 0)
    assert.ok(issue.recommendedAction.trim().length > 0)
    assert.ok(issue.evidenceText.trim().length > 0)
    assert.ok(issue.evidenceText.includes(': "') || issue.evidenceText.startsWith('Confirmed after review of the full document:'), issue.evidenceText)
  }
}
const serializedBlocked = JSON.stringify(presentation).toLowerCase()
for (const banned of [
  'candidate_issue', 'withheld by final publication validator', 'profiling_without_required_explanation',
  'signal detected', 'legal gate', 'duty-level', 'reconciliation', 'suppressed',
  'no_exportable_findings_after_safety_filters', 'invariant',
  // machine-generated fallback strings that must never reach the UI
  'gdpr compliance assessment for',
  'obligation-specific notice wording',
  'required gdpr article anchor',
  'internal diagnostic',
  'classified as internal diagnostic',
  'unknown issue',
]) {
  assert.ok(!serializedBlocked.includes(banned), `banned token leaked: ${banned}`)
}

// severity mapping and compliant display behavior
assert.equal(mod.mapSeverity('legal_basis', 'high'), 'High')
assert.equal(mod.mapSeverity('retention', 'medium'), 'Medium')
assert.equal(mod.severityDisplayForStatus('Compliant', 'High'), null)
assert.equal(mod.severityDisplayForStatus('Not applicable', 'High'), null)

// export contract tests
const reportCounts = mod.aggregateCounts(presentation.reportExportFindings)
const readiness = mod.validateReportExportReadiness(presentation, {
  pdfRenderedFindingsCount: presentation.reportExportFindings.length,
  pdfDatasetLabel: presentation.reportDatasetLabel,
  pdfRows: presentation.reportExportFindings,
  pdfStatusCounts: reportCounts,
})
assert.equal(readiness.ok, true)

const mismatch = mod.validateReportExportReadiness(presentation, {
  pdfRenderedFindingsCount: presentation.reportExportFindings.length + 1,
  pdfDatasetLabel: 'Final published findings',
  pdfRows: presentation.reportExportFindings.slice(0, 1),
  pdfStatusCounts: reportCounts,
})
assert.equal(mismatch.ok, false)
assert.ok(mismatch.errors.some((x) => x.toLowerCase().includes('count')))

const zeroPayload = mod.validateReportExportReadiness(presentation, {
  pdfRenderedFindingsCount: 0,
  pdfDatasetLabel: presentation.reportDatasetLabel,
  pdfRows: [],
  pdfStatusCounts: { compliant: 0, partially_compliant: 0, non_compliant: 0, not_applicable: 0, total: 0 },
})
assert.equal(zeroPayload.ok, false)

const compliantPresentation = mod.buildFindingsPresentation({
  publishedRows: [],
  reviewRows: [
    { item_kind: 'review_block', id: 'cb1', section_id: 'review:core_duties', final_disposition: 'satisfied', reason: 'all satisfied' },
  ],
  analysisRows: [
    { id: 'ca1', section_id: 'sec-1', analysis_type: 'completeness_outcome', issue_type: 'missing_transfer_notice', status_candidate: 'candidate_gap', gap_note: 'candidate only', remediation_note: 'n/a', citations: [] },
  ],
  sectionsById,
  publishedBlocked: false,
})
assert.equal(compliantPresentation.publishedVisibleFindings.length, 0)
assert.equal(mod.aggregateCounts(compliantPresentation.reviewVisibleFindings).non_compliant, 0)
assert.equal(mod.aggregateCounts(compliantPresentation.analysisVisibleFindings).non_compliant, 0)

// ── Internal / diagnostic text leakage contract ─────────────────────────────
// No user-facing surface may show internal pipeline text.
// This test proves the gap BEFORE the fix and stays green after.

const internalTextLeakPresentation = mod.buildFindingsPresentation({
  publishedRows: [],
  reviewRows: [
    {
      // issue_type is a known canonical key (passes the ISSUE_LABELS filter from the
      // previous fix) but gap_note and remediation_note contain internal diagnostic text.
      item_kind: 'finding', id: 'leak1', section_id: 'sec-1',
      issue_type: 'invalid_consent_or_legal_basis', status: 'gap',
      gap_note: 'Local finding suppressed: required GDPR article anchor is absent. Finding classified as internal diagnostic only.',
      remediation_note: null,
      citations: [{ chunk_id: 'cx2', article_number: '6', paragraph_ref: '1', article_title: 'Lawfulness of processing', excerpt: 'We process your data for operational purposes.' }],
    },
  ],
  analysisRows: [],
  sectionsById,
  publishedBlocked: false,
})

const leakIssues = internalTextLeakPresentation.reviewVisibleFindings.flatMap((r) => r.issues)
assert.equal(leakIssues.length, 1, 'review row with valid known issue_type must still be shown after internal-text filter')

const leakAllText = JSON.stringify(internalTextLeakPresentation).toLowerCase()
const internalDiagnosticBanned = [
  'local finding',
  'anchor is absent',
  'required gdpr article anchor',
  'internal diagnostic',
  'diagnostic only',
  'requires additional context before publication',
]
for (const banned of internalDiagnosticBanned) {
  assert.ok(!leakAllText.includes(banned), `internal token '${banned}' must not appear in any surface text after sanitization`)
}

// ── Issue-label leakage contract ────────────────────────────────────────────
// 'Unknown issue classification' must never appear on any surface —
// published, review, or analysis.  Rows that cannot be mapped to a canonical
// issue key must be filtered out entirely; they must not be labeled 'Unknown'.

// 1. All surfaces of the main presentation must be leak-free.
const allSurfaceLabels = [
  ...presentation.publishedVisibleFindings,
  ...presentation.reviewVisibleFindings,
  ...presentation.analysisVisibleFindings,
].flatMap((r) => r.issues.map((x) => x.issueLabel))
assert.ok(
  !allSurfaceLabels.includes('Unknown issue classification'),
  'Unknown issue classification must not appear on any surface (published / review / analysis)',
)

// 2. Review and analysis rows with unmapped issue_type must be excluded,
//    not passed through with a generic fallback label.
const unknownTypePresentation = mod.buildFindingsPresentation({
  publishedRows: [],
  reviewRows: [
    // unmapped — must be excluded
    { item_kind: 'finding', id: 'u1', section_id: 'sec-1', issue_type: 'some_internal_diagnostic_type', status: 'gap', gap_note: 'Internal diagnostic text.', remediation_note: 'Fix.', citations: [] },
    // null issue_type — must be excluded
    { item_kind: 'finding', id: 'u2', section_id: 'sec-2', issue_type: null, status: 'gap', gap_note: 'No issue type.', remediation_note: 'Fix.', citations: [] },
    // known type — must still appear
    { item_kind: 'finding', id: 'u3', section_id: 'sec-1', issue_type: 'missing_legal_basis', status: 'gap', gap_note: 'Legal basis is missing.', remediation_note: 'Add lawful basis.', citations: [{ chunk_id: 'cx1', article_number: '13', paragraph_ref: '1', article_title: 'Info', excerpt: 'We process data for support.' }] },
  ],
  analysisRows: [
    // unmapped — must be excluded
    { id: 'ua1', section_id: 'sec-1', analysis_type: 'completeness_outcome', issue_type: 'some_internal_analysis_key', status_candidate: 'gap', gap_note: 'Internal analysis.', remediation_note: 'Fix.', citations: [] },
    // known type — must still appear
    { id: 'ua2', section_id: 'sec-2', analysis_type: 'completeness_outcome', issue_type: 'missing_transfer_notice', status_candidate: 'gap', gap_note: 'Transfer safeguards not described.', remediation_note: 'Add transfer safeguards.', citations: [] },
  ],
  sectionsById,
  publishedBlocked: false,
})

const reviewLabels = unknownTypePresentation.reviewVisibleFindings.flatMap((r) => r.issues.map((x) => x.issueLabel))
const analysisLabels = unknownTypePresentation.analysisVisibleFindings.flatMap((r) => r.issues.map((x) => x.issueLabel))

assert.ok(
  !reviewLabels.includes('Unknown issue classification'),
  'Unknown issue classification must not appear in review findings',
)
assert.ok(
  !analysisLabels.includes('Unknown issue classification'),
  'Unknown issue classification must not appear in analysis findings',
)

// unknown-type rows must be completely excluded
const unknownReviewSections = unknownTypePresentation.reviewVisibleFindings.flatMap((r) =>
  r.issues.filter((i) => i.issueKey === 'some_internal_diagnostic_type'),
)
assert.equal(unknownReviewSections.length, 0, 'Internal diagnostic issue type must be excluded from review')

const unknownAnalysisSections = unknownTypePresentation.analysisVisibleFindings.flatMap((r) =>
  r.issues.filter((i) => i.issueKey === 'some_internal_analysis_key'),
)
assert.equal(unknownAnalysisSections.length, 0, 'Internal analysis issue type must be excluded from analysis')

// known-type rows must still be shown after the filter
assert.ok(reviewLabels.includes('Legal basis disclosure'), 'Known review issue type must still be shown after unknown-type filter')
assert.ok(analysisLabels.includes('International transfers'), 'Known analysis issue type must still be shown after unknown-type filter')

// serialized output must be entirely free of the banned string
const serializedUnknown = JSON.stringify(unknownTypePresentation).toLowerCase()
assert.ok(
  !serializedUnknown.includes('unknown issue classification'),
  'Serialized unknownTypePresentation must not contain "unknown issue classification"',
)

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
