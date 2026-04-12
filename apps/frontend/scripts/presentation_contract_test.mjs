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
}

const publishedRows = [
  {
    id: 'f1',
    section_id: 'sec-1',
    issue_key: 'missing_legal_basis',
    status: 'gap',
    severity: null,
    gap_note: 'duty validation marked retention_notice as non-compliant',
    remediation_note: 'In Section 4, add lawful basis mapping.',
    citations: [{ excerpt: 'We process data for support and billing.' }],
    primary_legal_anchor: ['GDPR Article 13(1)(c)'],
  },
  {
    id: 'f2',
    section_id: 'systemic:missing_complaint_right',
    issue_key: 'missing_complaint_right',
    status: 'gap',
    severity: 'low',
    gap_note: 'invalid_consent and strict legal gate phrasing',
    remediation_note: 'Explain complaint right.',
    citations: [],
    primary_legal_anchor: ['GDPR Article 13(2)(d)'],
  },
]

const reviewRows = [
  { item_kind: 'review_block', id: 'rb1', section_id: 'review:block', final_disposition: 'gap', reason: 'withheld by final publication validator' },
  { item_kind: 'finding', id: 'r1', section_id: 'sec-2', issue_type: 'missing_transfer_notice', status: 'gap', gap_note: 'candidate_issue transfer rationale', remediation_note: 'Add transfer safeguards' },
  { item_kind: 'finding', id: 'r2', section_id: 'sec-3', issue_type: 'missing_rights_notice', status: 'partial', gap_note: 'Observation: rights section is incomplete', remediation_note: 'Expand rights section' },
]

const analysisRows = [
  { id: 'a1', section_id: 'sec-2', analysis_type: 'completeness_outcome', issue_type: 'missing_transfer_notice', status_candidate: 'candidate_gap', gap_note: 'possible gap filtered by (.)', remediation_note: 'check', citations: [] },
  { id: 'a2', section_id: 'ledger:meta', analysis_type: 'support_evidence', issue_type: 'x', status_candidate: 'candidate_gap', gap_note: 'internal', remediation_note: 'internal', citations: [] },
]

const blockedPresentation = mod.buildFindingsPresentation({
  publishedRows,
  reviewRows,
  analysisRows,
  sectionsById,
  publishedBlocked: true,
})

// A. dataset contract
assert.equal(blockedPresentation.datasetLabels.publishedVisibleFindings, 'Final published findings')
assert.equal(blockedPresentation.datasetLabels.reviewVisibleFindings, 'Review findings')
assert.equal(blockedPresentation.datasetLabels.analysisVisibleFindings, 'Analysis findings')
assert.equal(blockedPresentation.datasetLabels.reportExportFindings, 'Review findings (final publication blocked)')
assert.equal(blockedPresentation.publishedVisibleFindings.length, 0)
assert.deepEqual(blockedPresentation.reportExportFindings, blockedPresentation.reviewVisibleFindings)

// B. export gate tests
const mismatchCount = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: blockedPresentation.reportExportFindings.length + 1,
  pdfDatasetLabel: blockedPresentation.reportDatasetLabel,
})
assert.equal(mismatchCount.ok, false)
assert.ok(mismatchCount.errors.some((x) => x.includes('counts diverge')))
const mismatchLabel = mod.validateReportExportReadiness(blockedPresentation, {
  pdfRenderedFindingsCount: blockedPresentation.reportExportFindings.length,
  pdfDatasetLabel: 'Final published findings',
})
assert.equal(mismatchLabel.ok, false)
assert.ok(mismatchLabel.errors.some((x) => x.includes('labels diverge')))
const missingEvidencePresentation = {
  ...blockedPresentation,
  reportExportFindings: [{ ...blockedPresentation.reportExportFindings[0], evidence_text: '' }],
}
assert.equal(mod.validateReportExportReadiness(missingEvidencePresentation).ok, false)

// C. title tests
assert.ok(blockedPresentation.reviewVisibleFindings.every((f) => f.title.startsWith('Section ')))
assert.ok(blockedPresentation.reviewVisibleFindings.every((f) => !['GDPR transparency disclosure gap', 'Compliance finding requiring review'].includes(f.title)))

// D. sanitizer tests
const serializedBlocked = JSON.stringify(blockedPresentation).toLowerCase()
for (const banned of ['support_only', 'candidate_issue', 'meta_section', 'invalid_consent', 'duty validation marked', 'filtered by (.)']) {
  assert.ok(!serializedBlocked.includes(banned), `banned token leaked: ${banned}`)
}
const renderedText = [
  ...blockedPresentation.reviewVisibleFindings.flatMap((f) => [f.title, f.issue_label, f.why_this_matters, f.recommended_action, f.evidence_text]),
  ...blockedPresentation.analysisVisibleFindings.flatMap((f) => [f.title, f.issue_label, f.why_this_matters, f.recommended_action, f.evidence_text]),
].join(' ').toLowerCase()
assert.ok(!renderedText.includes('[]'))
assert.ok(!renderedText.includes('{}'))

// E. evidence tests
assert.ok(blockedPresentation.reviewVisibleFindings.every((f) => /^Section .*: ".+"$|^Confirmed after review of the full document: no disclosure of .+ was identified\.$/.test(f.evidence_text)))

// F. review/analysis UX tests via data model
assert.equal(blockedPresentation.reviewVisibleFindings.every((f) => f.source_mode === 'review'), true)
assert.equal(blockedPresentation.analysisVisibleFindings.every((f) => f.source_mode === 'analysis'), true)
assert.equal(blockedPresentation.analysisVisibleFindings.length, 1)
assert.ok(blockedPresentation.reviewVisibleFindings.every((f) => f.title !== f.issue_label))
for (const row of [...blockedPresentation.reviewVisibleFindings, ...blockedPresentation.analysisVisibleFindings]) {
  assert.ok(['High', 'Medium', 'Low'].includes(row.severity))
  if (/legal basis|rights|complaint|transfer|profiling/i.test(`${row.issue_label} ${row.title}`)) assert.notEqual(row.severity, 'Low')
}

// G. compliant run tests
const compliantPresentation = mod.buildFindingsPresentation({
  publishedRows: [{ id: 'f4', section_id: 'sec-1', issue_key: 'minor_drafting', status: 'compliant', severity: null, gap_note: 'Substantive disclosure signal detected.', remediation_note: null, citations: [{ excerpt: 'Lawful basis is contract.' }], primary_legal_anchor: [] }],
  reviewRows: [],
  analysisRows: [],
  sectionsById,
  publishedBlocked: false,
})
assert.equal(mod.aggregateCounts(compliantPresentation.reportExportFindings).non_compliant, 0)
assert.equal(compliantPresentation.reportDatasetLabel, 'Final published findings')
assert.equal(mod.validateReportExportReadiness(compliantPresentation).ok, true)

// generic anti-leak
assert.ok(!serializedBlocked.match(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i))

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
