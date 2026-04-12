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
  'sec-1': { id: 'sec-1', section_order: 4, section_title: 'Legal Bases for Processing' },
  'sec-2': { id: 'sec-2', section_order: 6, section_title: 'International Transfers' },
  'sec-3': { id: 'sec-3', section_order: 9, section_title: 'Data Subject Rights' },
  'systemic:retention': { id: 'systemic:retention', section_order: 0, section_title: 'Systemic retention' },
}

const publishedRows = [
  {
    id: 'f1',
    section_id: 'sec-1',
    issue_key: 'missing_legal_basis',
    status: 'gap',
    severity: null,
    gap_note: 'Section ().',
    remediation_note: 'In Section 4, add lawful basis mapping.',
    citations: [{ excerpt: 'We process data for support and billing.' }],
    primary_legal_anchor: ['GDPR Article 13(1)(c)'],
  },
]

const reviewRows = [
  { item_kind: 'review_block', id: 'rb1', section_id: 'review:block', final_disposition: 'gap', reason: 'withheld by final publication validator' },
  { item_kind: 'finding', id: 'r1', section_id: 'sec-2', issue_type: 'missing_transfer_notice', status: 'gap', gap_note: 'candidate_issue transfer rationale', remediation_note: 'Add transfer safeguards' },
  { item_kind: 'finding', id: 'r2', section_id: 'sec-2', issue_type: 'profiling_disclosure_gap', status: 'partial', gap_note: '[debug] profiling_without_required_explanation', remediation_note: 'Expand profiling section' },
  { item_kind: 'finding', id: 'r3', section_id: 'systemic:retention', issue_type: 'missing_retention_period', status: 'gap', gap_note: 'Substantive disclosure signal detected', remediation_note: 'Add retention timelines' },
  { item_kind: 'finding', id: 'r4', section_id: 'sec-3', issue_type: 'unknown_disclosure_gap', status: 'gap', gap_note: 'legal gate reconciliation', remediation_note: 'Clarify transparency details' },
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

// 1) No duplicate section rows
for (const rows of [
  blockedPresentation.publishedVisibleFindings,
  blockedPresentation.reviewVisibleFindings,
  blockedPresentation.analysisVisibleFindings,
  blockedPresentation.reportExportFindings,
]) {
  const ids = rows.map((row) => `${row.sourceMode}:${row.sectionId}`)
  assert.equal(new Set(ids).size, ids.length)
}

// 2) Counts match dataset length
const counts = mod.aggregateCounts(blockedPresentation.reportExportFindings)
assert.equal(counts.total, blockedPresentation.reportExportFindings.length)
assert.equal(counts.compliant + counts.partially_compliant + counts.non_compliant + counts.not_applicable, blockedPresentation.reportExportFindings.length)

// 3) Report dataset equals Review dataset when blocked
assert.deepEqual(blockedPresentation.reportExportFindings, blockedPresentation.reviewVisibleFindings)
assert.equal(blockedPresentation.reportDatasetLabel, 'Review findings (used because publication is blocked)')

// 4) PDF dataset equals Report dataset
mod.assertPdfDatasetIntegrity(blockedPresentation.reportExportFindings, blockedPresentation.reportExportFindings)
const readiness = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: blockedPresentation.reportExportFindings.length,
  pdfDatasetLabel: blockedPresentation.reportDatasetLabel,
  pdfRows: blockedPresentation.reportExportFindings,
})
assert.equal(readiness.ok, true)

// 5) No internal tokens in output
const serializedBlocked = JSON.stringify(blockedPresentation).toLowerCase()
for (const banned of ['candidate_issue', 'withheld by final publication validator', 'profiling_without_required_explanation', 'section ().', 'signal detected', 'legal gate', 'duty-level', 'reconciliation', 'suppressed']) {
  assert.ok(!serializedBlocked.includes(banned), `banned token leaked: ${banned}`)
}

// 6) Every finding has non-empty Why this matters
for (const row of blockedPresentation.reportExportFindings) {
  for (const issue of row.issues) {
    assert.ok(issue.whyThisMatters.trim().length > 0)
  }
}

// human-readable issue labels & severity override checks
const issueLabels = blockedPresentation.reportExportFindings.flatMap((row) => row.issues.map((x) => x.issueLabel))
assert.ok(issueLabels.includes('Transfer safeguards disclosure'))
assert.ok(issueLabels.includes('Profiling transparency'))
assert.ok(issueLabels.includes('Transparency disclosure'))
const severities = blockedPresentation.reportExportFindings.flatMap((row) => row.issues.map((x) => x.severity))
assert.ok(severities.includes('High'))

// 7) Document-wide findings are separate from section findings
const documentRows = blockedPresentation.reportExportFindings.filter((row) => row.scope === 'Document-wide')
const sectionRows = blockedPresentation.reportExportFindings.filter((row) => row.scope === 'Section')
assert.ok(documentRows.length > 0)
assert.ok(sectionRows.every((row) => !row.sectionId.startsWith('systemic:')))
assert.ok(documentRows.every((row) => row.sectionTitle === 'Entire document'))
assert.ok(!serializedBlocked.includes('document-wide finding'))

// mismatch checks must fail
const mismatch = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: blockedPresentation.reportExportFindings.length + 1,
  pdfDatasetLabel: blockedPresentation.reportDatasetLabel,
  pdfRows: blockedPresentation.reportExportFindings,
})
assert.equal(mismatch.ok, false)
assert.throws(
  () => mod.assertPdfDatasetIntegrity(blockedPresentation.reportExportFindings.slice(0, 1), blockedPresentation.reportExportFindings),
  /PDF dataset mismatch/,
)

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
