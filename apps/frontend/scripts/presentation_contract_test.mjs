import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const srcPath = path.join(root, 'src', 'lib', 'presentation.ts')
const source = fs.readFileSync(srcPath, 'utf8')

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

const blockedPresentation = mod.buildFindingsPresentation({
  publishedRows,
  reviewRows,
  analysisRows,
  sectionsById,
  publishedBlocked: true,
})

// dataset contract + blocked fallback
assert.deepEqual(blockedPresentation.reportExportFindings, blockedPresentation.reviewVisibleFindings)
assert.equal(blockedPresentation.reportDatasetLabel, 'Review findings (used because publication is blocked)')

// canonical labels only
const labels = blockedPresentation.reportExportFindings.flatMap((row) => row.issues.map((x) => x.issueLabel))
for (const label of labels) {
  assert.ok([
    'Legal basis disclosure',
    'Data subject rights disclosure',
    'Complaint-right disclosure',
    'Retention disclosure',
    'Transfer safeguards disclosure',
    'Profiling transparency',
    'Cookie transparency disclosure',
    'Contact information disclosure',
    'Governance and compliance disclosure',
    'Purpose specificity disclosure',
    'Recipients disclosure',
    'Role allocation disclosure',
  ].includes(label), `unexpected issue label ${label}`)
}
assert.ok(!labels.includes('Transparency disclosure'))
assert.ok(!labels.includes('Compliance disclosure issue'))

// section summary model checks
const sectionRows = blockedPresentation.reportExportFindings.filter((row) => row.scope === 'Section')
assert.equal(sectionRows.length, new Set(sectionRows.map((row) => row.sectionId)).size)
for (const row of sectionRows) {
  assert.equal(row.issueCount, row.issues.length)
  assert.equal(row.primaryIssueLabel, row.issues[0].issueLabel)
}

// document finding model checks
const split = mod.splitFindingsByScope(blockedPresentation.reportExportFindings)
assert.ok(split.documentFindings.length > 0)
assert.equal(split.documentFindings.length, new Set(split.documentFindings.map((x) => x.issueKey)).size)
assert.ok(split.sectionFindings.every((row) => !row.sectionId.startsWith('systemic:')))

// clean section titles (no machine prefix)
for (const row of split.sectionFindings) {
  assert.ok(!/^section\s+\d+:/i.test(row.sectionTitle), `machine numbered title leaked: ${row.sectionTitle}`)
}

// copy sanity + human evidence
for (const row of blockedPresentation.reportExportFindings) {
  for (const issue of row.issues) {
    assert.ok(issue.whyThisMatters.trim().length > 0)
    assert.ok(issue.recommendedAction.trim().length > 0)
    assert.ok(issue.evidenceText.trim().length > 0)
    assert.ok(issue.evidenceText.includes(': "') || issue.evidenceText.startsWith('Confirmed after review of the full document:'), issue.evidenceText)
  }
}
const serializedBlocked = JSON.stringify(blockedPresentation).toLowerCase()
for (const banned of ['candidate_issue', 'withheld by final publication validator', 'profiling_without_required_explanation', 'signal detected', 'legal gate', 'duty-level', 'reconciliation', 'suppressed', 'no_exportable_findings_after_safety_filters', 'invariant']) {
  assert.ok(!serializedBlocked.includes(banned), `banned token leaked: ${banned}`)
}

// severity mapping and compliant display behavior
assert.equal(mod.mapSeverity('legal_basis', null), 'High')
assert.equal(mod.mapSeverity('retention', null), 'Medium')
assert.equal(mod.severityDisplayForStatus('Compliant', 'High'), null)
assert.equal(mod.severityDisplayForStatus('Not applicable', 'High'), null)

// export contract tests
const reportCounts = mod.aggregateCounts(blockedPresentation.reportExportFindings)
const readiness = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: blockedPresentation.reportExportFindings.length,
  pdfDatasetLabel: blockedPresentation.reportDatasetLabel,
  pdfRows: blockedPresentation.reportExportFindings,
  pdfStatusCounts: reportCounts,
})
assert.equal(readiness.ok, true)

const mismatch = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: blockedPresentation.reportExportFindings.length + 1,
  pdfDatasetLabel: 'Final published findings',
  pdfRows: blockedPresentation.reportExportFindings.slice(0, 1),
  pdfStatusCounts: reportCounts,
})
assert.equal(mismatch.ok, false)
assert.ok(mismatch.errors.some((x) => x.toLowerCase().includes('count')))
assert.ok(mismatch.errors.some((x) => x.toLowerCase().includes('label')))

const zeroPayload = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: 0,
  pdfDatasetLabel: blockedPresentation.reportDatasetLabel,
  pdfRows: [],
  pdfStatusCounts: { compliant: 0, partially_compliant: 0, non_compliant: 0, not_applicable: 0, total: 0 },
})
assert.equal(zeroPayload.ok, false)

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
