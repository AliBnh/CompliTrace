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
  'sec-2': { id: 'sec-2', section_order: 2, section_title: 'International transfers' },
}

const publishedRows = [
  {
    id: 'f1',
    section_id: 'sec-1',
    issue_key: 'missing_retention_period',
    status: 'gap',
    severity: null,
    gap_note: 'duty validation marked retention_notice as non-compliant',
    remediation_note: 'In Section 1, add the retention period.',
    citations: [{ excerpt: 'No retention period statement found.' }],
    primary_legal_anchor: ['GDPR Article 13(2)(a)'],
  },
  {
    id: 'f2',
    section_id: 'systemic:missing_legal_basis',
    issue_key: 'missing_legal_basis',
    status: 'gap',
    severity: 'low',
    gap_note: 'invalid_consent and strict legal gate phrasing',
    remediation_note: 'State the lawful basis.',
    citations: [],
    primary_legal_anchor: ['GDPR Article 13(1)(c)'],
  },
  {
    id: 'f3',
    section_id: 'systemic:missing_transfer_notice',
    issue_key: 'missing_transfer_notice',
    status: 'gap',
    severity: null,
    gap_note: '[]',
    remediation_note: 'Explain safeguards used.',
    citations: [{ excerpt: '[]' }],
    primary_legal_anchor: ['GDPR Article 13(1)(f)'],
  },
]

const reviewRows = [
  { item_kind: 'review_block', id: 'rb1', section_id: 'review:block', final_disposition: 'gap', reason: 'withheld by final publication validator' },
  { item_kind: 'finding', id: 'r1', section_id: 'sec-1', issue_type: 'missing_retention_period', status: 'partial', gap_note: 'candidate_issue', remediation_note: 'Address retention' },
  { item_kind: 'finding', id: 'r2', section_id: 'systemic:missing_legal_basis', issue_type: 'missing_legal_basis', status: 'gap', gap_note: 'Observation: required legal_basis disclosure is missing', remediation_note: 'Add legal basis' },
]

const analysisRows = [
  { id: 'a1', section_id: 'sec-2', analysis_type: 'completeness_outcome', issue_type: 'missing_transfer_notice', status_candidate: 'candidate_gap', gap_note: 'possible gap', remediation_note: 'check', citations: [] },
  { id: 'a2', section_id: 'ledger:meta', analysis_type: 'support_evidence', issue_type: 'x', status_candidate: 'candidate_gap', gap_note: 'internal', remediation_note: 'internal', citations: [] },
]

const presentation = mod.buildFindingsPresentation({
  publishedRows,
  reviewRows,
  analysisRows,
  sectionsById,
  publishedBlocked: true,
})

// A. Evidence completeness / no placeholders.
assert.ok(presentation.publishedVisibleFindings.every((x) => x.evidence_text.length > 20))
assert.ok(presentation.publishedVisibleFindings.every((x) => !/\[\s*\]/.test(x.evidence_text)))
assert.ok(!JSON.stringify(presentation.reportExportFindings).includes('No supporting excerpt available in the current view'))

// B. sanitizer
const serialized = JSON.stringify(presentation).toLowerCase()
for (const banned of ['support_only', 'candidate_issue', 'meta_section', 'invalid_consent', 'strict legal gate', 'withheld by final publication validator']) {
  assert.ok(!serialized.includes(banned), `banned token leaked: ${banned}`)
}

// C. title generator no placeholders
assert.ok(presentation.reviewVisibleFindings.every((f) => f.title !== 'Compliance finding requiring review'))
assert.ok(presentation.publishedVisibleFindings.every((f) => f.title.length > 5))

// D/E dataset separation and calibrated severity/selection-ready detail content
assert.equal(presentation.reviewVisibleFindings.every((f) => f.source_mode === 'review'), true)
assert.equal(presentation.analysisVisibleFindings.length, 1)
assert.equal(presentation.analysisVisibleFindings[0].source_mode, 'analysis')
assert.equal(presentation.reviewVisibleFindings.some((f) => f.severity === 'High' && f.title.includes('legal basis')), true)
assert.ok(presentation.reviewVisibleFindings.every((f) => f.evidence_text.length > 20))

// F/G blocked state/export contract
assert.equal(presentation.reportMode, 'review')
assert.equal(presentation.reportDatasetLabel, 'Review findings (final publication blocked)')
const counts = mod.aggregateCounts(presentation.reportExportFindings)
assert.equal(counts.total, presentation.reportExportFindings.length)
const readiness = mod.validateReportExportReadiness(presentation)
assert.equal(readiness.ok, true)

// H compliant run plain output
const compliant = mod.buildFindingsPresentation({
  publishedRows: [{ id: 'f4', section_id: 'sec-1', issue_key: 'minor_drafting', status: 'compliant', severity: null, gap_note: 'Substantive disclosure signal detected.', remediation_note: null, citations: [{ excerpt: 'Disclosure is present.' }], primary_legal_anchor: [] }],
  reviewRows: [],
  analysisRows: [],
  sectionsById,
  publishedBlocked: false,
})
assert.equal(mod.aggregateCounts(compliant.reportExportFindings).non_compliant, 0)
assert.ok(!JSON.stringify(compliant).toLowerCase().includes('substantive disclosure signal detected'))

// I severity guard
for (const row of presentation.publishedVisibleFindings) {
  assert.ok(['High', 'Medium', 'Low'].includes(row.severity))
  if (/legal basis|transfer|profiling|rights|complaint/i.test(row.title)) assert.notEqual(row.severity, 'Low')
}

// J no UUID leaks
assert.ok(!serialized.match(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i))

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
