import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
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
    status: 'partial',
    severity: null,
    gap_note: 'Purpose mapping is too broad.',
    remediation_note: 'Clarify purpose mapping.',
    citations: [{ excerpt: 'Purpose text exists.' }],
    primary_legal_anchor: ['GDPR Article 5(1)(b)'],
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

// canonical labels only
const labels = presentation.reportExportFindings.flatMap((row) => row.issues.map((x) => x.issueLabel))
for (const label of labels) {
  assert.ok([
    'Legal basis disclosure',
    'Data subject rights',
    'Right to lodge a complaint',
    'Retention period',
    'International transfers',
    'Automated decision-making / profiling',
    'Cookie transparency disclosure',
    'Contact information',
    'Data governance responsibilities',
    'Purpose specificity',
    'Recipients of personal data',
    'Role allocation disclosure',
  ].includes(label), `unexpected issue label ${label}`)
}
assert.ok(!labels.includes('Transparency disclosure'))
assert.ok(!labels.includes('Compliance disclosure issue'))
assert.ok(labels.includes('Automated decision-making / profiling'))
assert.ok(labels.includes('International transfers'))
assert.ok(labels.includes('Contact information'))
assert.ok(labels.includes('Purpose specificity'))

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
for (const banned of ['candidate_issue', 'withheld by final publication validator', 'profiling_without_required_explanation', 'signal detected', 'legal gate', 'duty-level', 'reconciliation', 'suppressed', 'no_exportable_findings_after_safety_filters', 'invariant']) {
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

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
