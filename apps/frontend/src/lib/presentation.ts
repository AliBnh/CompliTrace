import type { FindingOut, ReviewItemOut } from './types'

export type UserStatus = 'Compliant' | 'Partially compliant' | 'Non-compliant' | 'Not applicable'
export type UserSeverity = 'High' | 'Medium' | 'Low' | null

export type PresentationRow = {
  id: string
  title: string
  scope: 'Section finding' | 'Document-wide finding'
  status: UserStatus
  severity: UserSeverity
  summary: string
  evidence: string
  remediation: string | null
  legalAnchors: string | null
  sectionKey: string
}

export type FindingsSnapshot = {
  mode: 'published' | 'review'
  message: string | null
  rows: PresentationRow[]
  sectionRows: PresentationRow[]
  systemicRows: PresentationRow[]
  counts: Record<UserStatus, number>
  blockers: string[]
}

const INTERNAL_TERMS = [
  'support_only',
  'internal_only',
  'post_reviewer_snapshot',
  'confirmed_document_gap',
  'probable_document_gap',
  'not_assessable_from_provided_text',
  'withheld by final publication validator',
]

export function mapUserStatus(value?: string | null): UserStatus {
  const s = (value ?? '').toLowerCase()
  if (s.includes('gap') || s.includes('non_compliance') || s.includes('blocked')) return 'Non-compliant'
  if (s.includes('partial')) return 'Partially compliant'
  if (s.includes('compliant') || s.includes('no_issue') || s.includes('satisfied')) return 'Compliant'
  return 'Not applicable'
}

export function mapUserSeverity(value?: string | null): UserSeverity {
  const s = (value ?? '').toLowerCase()
  if (s === 'high') return 'High'
  if (s === 'medium') return 'Medium'
  if (s === 'low') return 'Low'
  return null
}

function statusRank(s: UserStatus): number {
  if (s === 'Non-compliant') return 4
  if (s === 'Partially compliant') return 3
  if (s === 'Compliant') return 2
  return 1
}

function scrub(text?: string | null): string {
  const raw = (text ?? '').trim()
  if (!raw) return ''
  let out = raw
    .replace(/evi:[a-z]+:[a-z0-9:_-]+/gi, '')
    .replace(/issue_type[:=][^\s,;]+/gi, '')
    .replace(/\b(full_notice|partial_notice_excerpt|uncertain_scope)\b/gi, '')
  for (const token of INTERNAL_TERMS) {
    out = out.replace(new RegExp(token, 'gi'), '')
  }
  out = out.replace(/\s{2,}/g, ' ').trim()
  return out
}

export function formatLegalAnchors(anchors?: string[] | null): string | null {
  const parts = (anchors ?? []).filter(Boolean)
  if (!parts.length) return null
  if (parts.length === 1) return parts[0]
  return `GDPR Articles ${parts.map((a) => a.replace(/^GDPR\s+Article\s+/i, '')).join(' and ')}`
}

function inferSummary(gapNote?: string | null, remediation?: string | null): string {
  const note = scrub(gapNote)
  if (note) return note
  if (remediation) return `Recommended action: ${scrub(remediation)}`
  return 'No material compliance issue is visible in this view.'
}

function findingToPresentation(row: FindingOut): PresentationRow | null {
  const hidden = ['support_only', 'internal_only', 'diagnostic_internal_only'].some((t) =>
    `${row.classification ?? ''} ${row.finding_type ?? ''} ${row.publish_flag ?? ''}`.toLowerCase().includes(t),
  )
  if (hidden) return null
  const status = mapUserStatus(row.status)
  const title = row.section_id.startsWith('systemic:') ? row.section_id.replace('systemic:', '').split('_').join(' ') : row.section_id
  const evidenceFromCitation = row.citations[0]?.excerpt ? scrub(row.citations[0].excerpt) : ''
  const evidence = evidenceFromCitation || scrub(row.citation_summary_text) || 'No supporting excerpt available in the current view.'
  return {
    id: row.id,
    title,
    scope: row.section_id.startsWith('systemic:') ? 'Document-wide finding' : 'Section finding',
    status,
    severity: mapUserSeverity(row.severity),
    summary: inferSummary(row.gap_note, row.remediation_note),
    evidence,
    remediation: scrub(row.remediation_note) || null,
    legalAnchors: formatLegalAnchors(row.primary_legal_anchor),
    sectionKey: row.section_id,
  }
}

function reviewToPresentation(row: ReviewItemOut): PresentationRow | null {
  if (row.section_id.startsWith('ledger:') || row.section_id.startsWith('review:')) return null
  if ((row.item_kind === 'review_block' && (row.final_disposition ?? '').toLowerCase() === 'satisfied')) return null
  const status = mapUserStatus(row.status ?? row.final_disposition)
  return {
    id: row.id,
    title: row.section_id.startsWith('systemic:') ? row.section_id.replace('systemic:', '').split('_').join(' ') : row.section_id,
    scope: row.section_id.startsWith('systemic:') ? 'Document-wide finding' : 'Section finding',
    status,
    severity: null,
    summary: inferSummary(row.gap_note ?? row.reason, row.remediation_note),
    evidence: scrub(row.reason) || 'No supporting excerpt available in the current view.',
    remediation: scrub(row.remediation_note) || null,
    legalAnchors: null,
    sectionKey: row.section_id,
  }
}

function dedupeSectionRows(rows: PresentationRow[]): PresentationRow[] {
  const byKey = new Map<string, PresentationRow>()
  for (const row of rows) {
    const existing = byKey.get(row.sectionKey)
    if (!existing || statusRank(row.status) > statusRank(existing.status)) {
      byKey.set(row.sectionKey, row)
    }
  }
  return [...byKey.values()]
}

function countsFrom(rows: PresentationRow[]): Record<UserStatus, number> {
  const base: Record<UserStatus, number> = {
    Compliant: 0,
    'Partially compliant': 0,
    'Non-compliant': 0,
    'Not applicable': 0,
  }
  for (const row of rows) base[row.status] += 1
  return base
}

export function buildFindingsSnapshot(params: {
  publishedRows: FindingOut[]
  reviewRows: ReviewItemOut[]
  publishedBlocked: boolean
}): FindingsSnapshot {
  const blockers = params.reviewRows
    .filter((r) => r.item_kind === 'review_block' && (r.final_disposition ?? '').toLowerCase() !== 'satisfied')
    .map((r) => scrub(r.reason) || 'Unresolved review blocker')
  const mode: 'published' | 'review' = params.publishedBlocked ? 'review' : 'published'
  const rawRows = mode === 'published'
    ? params.publishedRows.map(findingToPresentation).filter(Boolean) as PresentationRow[]
    : params.reviewRows.map(reviewToPresentation).filter(Boolean) as PresentationRow[]
  const sectionRows = dedupeSectionRows(rawRows.filter((r) => r.scope === 'Section finding'))
  const systemicRows = rawRows.filter((r) => r.scope === 'Document-wide finding')
  const rows = [...sectionRows, ...systemicRows]
  return {
    mode,
    message: params.publishedBlocked ? 'Final report not available yet due to unresolved review issues.' : null,
    rows,
    sectionRows,
    systemicRows,
    counts: countsFrom(rows),
    blockers,
  }
}
