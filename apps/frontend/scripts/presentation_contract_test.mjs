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
  'sec-1': { id: 'sec-1', section_order: 1, section_title: 'Data retention' },
}

const publishedRows = [
  { id: 'f1', section_id: 'sec-1', issue_key: 'missing_retention_period', status: 'gap', severity: null, gap_note: 'duty validation marked retention_notice as non-compliant', remediation_note: 'Fix', citations: [{ excerpt: 'No retention period statement found.' }], primary_legal_anchor: ['GDPR Article 13(2)(a)'] },
  { id: 'f2', section_id: 'sec-1', issue_key: 'missing_retention_period', status: 'partial', severity: 'medium', gap_note: 'support_evidence', remediation_note: 'Fix 2', citations: [] },
  { id: 'f3', section_id: 'systemic:missing_legal_basis', issue_key: 'missing_legal_basis', status: 'gap', severity: null, gap_note: 'missing legal basis', remediation_note: 'Add legal basis', citations: [] },
]

const reviewRows = [
  { item_kind: 'review_block', id: 'rb1', section_id: 'review:block', final_disposition: 'gap', reason: 'withheld by final publication validator' },
  { item_kind: 'finding', id: 'r1', section_id: 'sec-1', issue_type: 'missing_retention_period', status: 'partial', gap_note: 'candidate_issue', remediation_note: 'Address retention' },
]

const analysisRows = [
  { id: 'a1', section_id: 'sec-1', analysis_type: 'completeness_outcome', issue_type: 'missing_transfer_notice', status_candidate: 'candidate_gap', gap_note: 'possible gap', remediation_note: 'check', citations: [] },
  { id: 'a2', section_id: 'ledger:meta', analysis_type: 'support_evidence', issue_type: 'x', status_candidate: 'candidate_gap', gap_note: 'internal', remediation_note: 'internal', citations: [] },
]

const presentation = mod.buildFindingsPresentation({ publishedRows, reviewRows, analysisRows, sectionsById, publishedBlocked: true })

assert.equal(presentation.publishedVisibleFindings.filter((r) => r.scope_type === 'section').length, 1, 'one row per section')
assert.equal(presentation.reportMode, 'review')
assert.equal(presentation.reviewVisibleFindings.length, 1)
assert.equal(presentation.analysisVisibleFindings.length, 1)
assert.ok(!JSON.stringify(presentation).toLowerCase().includes('validator'))
assert.ok(!JSON.stringify(presentation).toLowerCase().includes('support_evidence'))
assert.ok(!JSON.stringify(presentation).match(/[0-9a-f]{8}-[0-9a-f]{4}/i))
assert.equal(presentation.publishedVisibleFindings[0].severity, 'Medium', 'severity fallback mapping')
assert.ok(presentation.publishedVisibleFindings[1].evidence_text.toLowerCase().includes('confirmed after review of the full document'))

const counts = mod.aggregateCounts(presentation.reportVisibleFindings)
assert.equal(counts.total, presentation.reportVisibleFindings.length)

const compliant = mod.buildFindingsPresentation({
  publishedRows: [{ id: 'f4', section_id: 'sec-1', issue_key: 'minor_drafting', status: 'compliant', severity: null, gap_note: null, remediation_note: null, citations: [{ excerpt: 'Disclosure is present.' }] }],
  reviewRows: [],
  analysisRows: [],
  sectionsById,
  publishedBlocked: false,
})
const compliantCounts = mod.aggregateCounts(compliant.reportVisibleFindings)
assert.equal(compliantCounts.non_compliant, 0)

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
