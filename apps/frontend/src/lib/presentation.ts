import type { AnalysisItemOut, FindingOut, ReviewItemOut, SectionOut } from './types'

export type UserStatus = 'Compliant' | 'Partially compliant' | 'Non-compliant' | 'Not applicable'
export type UserSeverity = 'High' | 'Medium' | 'Low'
export type SourceMode = 'published' | 'review' | 'analysis'

export type NormalizedFinding = {
  stable_ui_id: string
  title: string
  scope_type: 'section' | 'document'
  scope_label: string
  section_title: string | null
  status: UserStatus
  severity: UserSeverity
  why_this_matters: string
  recommended_action: string
  legal_anchors: string[]
  evidence_mode: 'excerpt' | 'full_document_absence' | 'none'
  evidence_text: string
  visible: boolean
  source_mode: SourceMode
  section_key: string
  details: string[]
}

export type DatasetSummary = {
  compliant: number
  partially_compliant: number
  non_compliant: number
  not_applicable: number
  total: number
}

export type FindingsPresentation = {
  publishedVisibleFindings: NormalizedFinding[]
  reviewVisibleFindings: NormalizedFinding[]
  analysisVisibleFindings: NormalizedFinding[]
  reportVisibleFindings: NormalizedFinding[]
  publishedBlocked: boolean
  publishedBlockers: string[]
  reportMode: 'published' | 'review'
}

const BANNED_TERMS = [
  'support_only', 'internal_only', 'candidate_issue', 'provisional_local', 'support_evidence', 'post_reviewer_snapshot',
  'meta_section', 'auditability gate', 'not_assessable', 'confirmed_document_gap', 'probable_document_gap',
  'clear_non_compliance', 'withheld by final publication validator', 'explicit violation validator matched',
  'duty validation marked', 'validator', 'embedding model', 'corpus version', 'parse failure rate',
  'contradiction rate', 'heuristic quality score', 'confidence component breakdown',
]

const ISSUE_TITLES: Record<string, string> = {
  missing_complaint_right: 'Missing complaint-right disclosure',
  missing_legal_basis: 'Missing legal basis disclosure',
  missing_retention_period: 'Missing retention-period disclosure',
  profiling_disclosure_gap: 'Profiling transparency gap',
  recipients_disclosure_gap: 'Recipients disclosure gap',
  purpose_specificity_gap: 'Purpose specificity gap',
  missing_rights_notice: 'Missing rights-notice disclosure',
  missing_transfer_notice: 'Missing transfer disclosure',
}

function cleanText(value?: string | null): string {
  let text = (value ?? '').trim()
  if (!text) return ''
  text = text.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi, '')
    .replace(/\b(?:evi|section|evidence)_id\s*[:=]\s*[a-z0-9:_-]+/gi, '')
    .replace(/\b[a-z]+:[a-z0-9:_-]{10,}\b/gi, '')
  for (const term of BANNED_TERMS) text = text.replace(new RegExp(term, 'gi'), '')
  text = text.replace(/\s{2,}/g, ' ').trim()
  return /^(n\/?a|null|none|undefined|-)$/.test(text.toLowerCase()) ? '' : text
}

function mapStatus(value?: string | null): UserStatus {
  const s = (value ?? '').toLowerCase().replace(/_/g, ' ')
  if (s.includes('gap') || s.includes('non compliant') || s.includes('blocked')) return 'Non-compliant'
  if (s.includes('partial')) return 'Partially compliant'
  if (s.includes('compliant') || s.includes('satisfied')) return 'Compliant'
  return 'Not applicable'
}

function mapSeverity(issue: string | null, severity?: string | null): UserSeverity {
  const base = (severity ?? '').toLowerCase()
  if (base === 'high') return 'High'
  if (base === 'medium') return 'Medium'
  if (base === 'low') return 'Low'
  const i = (issue ?? '').toLowerCase()
  if (/(legal_basis|complaint|rights|transfer|profil)/.test(i)) return 'High'
  if (/(retention|recipient|purpose)/.test(i)) return 'Medium'
  return 'Low'
}

function titleFrom(issue: string | null, fallback: string): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  if (ISSUE_TITLES[normalized]) return ISSUE_TITLES[normalized]
  const cleanFallback = cleanText(fallback)
  if (cleanFallback && !/^[0-9a-f-]{16,}$/i.test(cleanFallback)) return cleanFallback
  return 'Compliance finding requiring review'
}

function scopeInfo(sectionId: string, sectionsById: Record<string, SectionOut>) {
  if (sectionId.startsWith('systemic:')) {
    const issue = sectionId.split('systemic:')[1] ?? ''
    return { scope_type: 'document' as const, scope_label: 'Document-wide finding', section_key: sectionId, issue }
  }
  const section = sectionsById[sectionId]
  return {
    scope_type: 'section' as const,
    scope_label: 'Section finding',
    section_key: sectionId,
    issue: null,
    section_title: section?.section_title ? `Section ${section.section_order}: ${section.section_title}` : 'Document section',
  }
}

function evidenceText(sectionTitle: string | null, excerpt: string, issueTitle: string): { mode: 'excerpt' | 'full_document_absence' | 'none'; text: string } {
  const e = cleanText(excerpt)
  if (e) return { mode: 'excerpt', text: `${sectionTitle ?? 'Section'}: ${e}` }
  return { mode: 'full_document_absence', text: `Confirmed after review of the full document: no disclosure of ${issueTitle.toLowerCase()} was identified.` }
}

function rank(status: UserStatus): number {
  if (status === 'Non-compliant') return 4
  if (status === 'Partially compliant') return 3
  if (status === 'Compliant') return 2
  return 1
}

function mergeSectionRows(rows: NormalizedFinding[]): NormalizedFinding[] {
  const map = new Map<string, NormalizedFinding>()
  for (const row of rows) {
    if (row.scope_type !== 'section') continue
    const existing = map.get(row.section_key)
    if (!existing) {
      map.set(row.section_key, row)
      continue
    }
    const winner = rank(row.status) > rank(existing.status) ? row : existing
    const loser = winner === row ? existing : row
    winner.details = [...winner.details, loser.why_this_matters].filter(Boolean)
    map.set(row.section_key, winner)
  }
  const docs = rows.filter((r) => r.scope_type === 'document')
  return [...map.values(), ...docs]
}

function normalizePublished(row: FindingOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  const visibilityToken = `${row.classification ?? ''} ${row.publish_flag ?? ''} ${row.finding_type ?? ''}`.toLowerCase()
  if (/(support_only|internal_only|diagnostic_internal_only)/.test(visibilityToken)) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  const issue = row.issue_key ?? scope.issue
  const title = titleFrom(issue, row.section_id)
  const evidence = evidenceText(scope.scope_type === 'section' ? (scope.section_title ?? null) : 'Document-wide evidence', row.citations?.[0]?.excerpt ?? row.citation_summary_text ?? '', title)
  return {
    stable_ui_id: `published:${row.id}`,
    title,
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? (scope.section_title ?? null) : null,
    status: mapStatus(row.status),
    severity: mapSeverity(issue, row.severity),
    why_this_matters: cleanText(row.gap_note) || 'Insufficient detail in this section to confirm full compliance.',
    recommended_action: cleanText(row.remediation_note) || 'Add explicit GDPR-required disclosures for this obligation.',
    legal_anchors: (row.primary_legal_anchor ?? []).map((a) => cleanText(a)).filter(Boolean),
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'published',
    section_key: scope.section_key,
    details: [],
  }
}

function normalizeReview(row: ReviewItemOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  if (row.item_kind === 'review_block' || row.section_id.startsWith('ledger:') || row.section_id.startsWith('review:')) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  const issue = row.issue_type ?? scope.issue
  const title = titleFrom(issue, row.section_id)
  const evidence = evidenceText(scope.scope_type === 'section' ? (scope.section_title ?? null) : 'Document-wide evidence', row.reason ?? row.gap_note ?? '', title)
  return {
    stable_ui_id: `review:${row.id}`,
    title,
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? (scope.section_title ?? null) : null,
    status: mapStatus(row.status ?? row.final_disposition),
    severity: mapSeverity(issue, null),
    why_this_matters: cleanText(row.gap_note ?? row.reason) || 'Insufficient detail in this section to confirm full compliance.',
    recommended_action: cleanText(row.remediation_note) || 'Clarify and complete this disclosure before publication.',
    legal_anchors: [],
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'review',
    section_key: scope.section_key,
    details: [],
  }
}

function normalizeAnalysis(row: AnalysisItemOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  if (/(support_evidence|meta_section|internal)/i.test(`${row.analysis_type} ${row.artifact_role ?? ''} ${row.section_id}`)) return null
  if (row.section_id.startsWith('ledger:')) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  const issue = row.issue_type ?? scope.issue
  const title = titleFrom(issue, row.section_id)
  const evidence = evidenceText(scope.scope_type === 'section' ? (scope.section_title ?? null) : 'Document-wide evidence', row.citations?.[0]?.excerpt ?? row.gap_note ?? '', title)
  return {
    stable_ui_id: `analysis:${row.id}`,
    title,
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? (scope.section_title ?? null) : null,
    status: mapStatus(row.status_candidate),
    severity: mapSeverity(issue, null),
    why_this_matters: cleanText(row.gap_note) || 'Insufficient detail in this section to confirm full compliance.',
    recommended_action: cleanText(row.remediation_note) || 'Confirm this finding during reviewer validation.',
    legal_anchors: [],
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'analysis',
    section_key: scope.section_key,
    details: [],
  }
}

export function buildFindingsPresentation(params: {
  publishedRows: FindingOut[]
  reviewRows: ReviewItemOut[]
  analysisRows: AnalysisItemOut[]
  sectionsById: Record<string, SectionOut>
  publishedBlocked: boolean
}): FindingsPresentation {
  const blockers = params.reviewRows
    .filter((r) => r.item_kind === 'review_block' && mapStatus(r.final_disposition) !== 'Compliant')
    .map((r) => cleanText(r.reason) || 'Some findings still require review before final publication.')

  const publishedVisibleFindings = mergeSectionRows(params.publishedRows.map((r) => normalizePublished(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const reviewVisibleFindings = mergeSectionRows(params.reviewRows.map((r) => normalizeReview(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const analysisVisibleFindings = mergeSectionRows(params.analysisRows.map((r) => normalizeAnalysis(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])

  const reportMode: 'published' | 'review' = params.publishedBlocked ? 'review' : 'published'
  const reportVisibleFindings = reportMode === 'published' ? publishedVisibleFindings : reviewVisibleFindings

  return {
    publishedVisibleFindings,
    reviewVisibleFindings,
    analysisVisibleFindings,
    reportVisibleFindings,
    publishedBlocked: params.publishedBlocked,
    publishedBlockers: blockers,
    reportMode,
  }
}

export function aggregateCounts(rows: NormalizedFinding[]): DatasetSummary {
  const out: DatasetSummary = { compliant: 0, partially_compliant: 0, non_compliant: 0, not_applicable: 0, total: rows.length }
  for (const row of rows) {
    if (row.status === 'Compliant') out.compliant += 1
    else if (row.status === 'Partially compliant') out.partially_compliant += 1
    else if (row.status === 'Non-compliant') out.non_compliant += 1
    else out.not_applicable += 1
  }
  return out
}
