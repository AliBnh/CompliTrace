import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const srcPath = path.join(root, 'src', 'lib', 'presentation.ts')
const source = fs.readFileSync(srcPath, 'utf8')

const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2020,
    module: ts.ModuleKind.ES2020,
  },
  fileName: srcPath,
}).outputText

const tempFile = path.join(root, '.tmp.presentation.test.mjs')
fs.writeFileSync(tempFile, transpiled, 'utf8')
const mod = await import(pathToFileURL(tempFile).href)

const publishedRows = [
  {
    id: 'f1',
    section_id: 'sec-1',
    status: 'gap',
    severity: 'high',
    gap_note: 'confirmed_document_gap evi:policy:abc Missing legal basis.',
    remediation_note: 'Add legal basis mapping.',
    citations: [],
  },
  {
    id: 'f2',
    section_id: 'sec-1',
    status: 'partial',
    severity: 'medium',
    gap_note: 'partial',
    remediation_note: null,
    citations: [],
  },
  {
    id: 'f3',
    section_id: 'systemic:missing_transfer_notice',
    status: 'gap',
    severity: 'high',
    gap_note: 'Transfer safeguards are not disclosed.',
    remediation_note: 'State SCCs or adequacy mechanism.',
    citations: [],
  },
]

const reviewRows = [
  { item_kind: 'review_block', id: 'rb1', section_id: 'review:block', final_disposition: 'gap', reason: 'missing evidence linkage' },
]

const snapPublished = mod.buildFindingsSnapshot({ publishedRows, reviewRows: [], publishedBlocked: false })
assert.equal(snapPublished.sectionRows.length, 1, 'one row per section expected')
assert.equal(snapPublished.counts['Non-compliant'], 2, 'non-compliant counts should reflect deduped visible rows')
assert.ok(!snapPublished.rows[0].summary.includes('confirmed_document_gap'))
assert.ok(!snapPublished.rows[0].summary.includes('evi:policy'))

const snapBlocked = mod.buildFindingsSnapshot({ publishedRows, reviewRows, publishedBlocked: true })
assert.equal(snapBlocked.mode, 'review')
assert.ok((snapBlocked.message || '').toLowerCase().includes('final report'))
assert.ok(snapBlocked.blockers.length > 0)

fs.unlinkSync(tempFile)
console.log('presentation contract checks passed')
