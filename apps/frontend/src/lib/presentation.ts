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
  evidence_mode: 'excerpt' | 'full_document_absence'
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
  reportExportFindings: NormalizedFinding[]
  publishedBlocked: boolean
  publishedBlockers: string[]
  reportMode: 'published' | 'review'
  reportDatasetLabel: 'Final published findings' | 'Review findings (final publication blocked)'
}

const BANNED_TERMS = [
  'support_only', 'internal_only', 'candidate_issue', 'provisional_local', 'support_evidence', 'post_reviewer_snapshot',
  'meta_section', 'auditability gate', 'not_assessable', 'confirmed_document_gap', 'probable_document_gap',
  'clear_non_compliance', 'withheld by final publication validator', 'explicit violation validator matched',
  'duty validation marked', 'no explicit evidence refs from final map', 'raw issue_type keys', 'raw section ids',
  'raw evidence ids', 'invalid_consent', 'profiling_without_required_explanation', 'weak_transfer_safeguards',
  'embedding model', 'corpus version', 'parse failure rate', 'contradiction rate', 'heuristic quality score',
  'confidence component breakdown', 'strict legal gate', 'validator',
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
  controller_processor_role_ambiguity: 'Role allocation needs clarification',
}

const ISSUE_SUBJECT: Record<string, string> = {
  missing_complaint_right: 'the right to lodge a complaint with a supervisory authority',
  missing_legal_basis: 'the lawful basis for the processing activities described',
  missing_retention_period: 'a retention period or retention criteria for the data processed',
  profiling_disclosure_gap: 'profiling logic, significance, and expected consequences',
  recipients_disclosure_gap: 'categories of recipients for disclosed processing activities',
  purpose_specificity_gap: 'clear mapping between data categories and processing purposes',
  missing_rights_notice: 'the data subject rights notice required under GDPR',
  missing_transfer_notice: 'international transfer safeguards and related disclosures',
  controller_processor_role_ambiguity: 'whether the organisation acts as controller or processor in each context',
}

function sanitizeUserFacingText(value?: string | null): string {
  let text = (value ?? '').trim()
  if (!text) return ''
  text = text
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi, ' ')
    .replace(/\b(?:evi|section|evidence)_id\s*[:=]\s*[a-z0-9:_-]+/gi, ' ')
    .replace(/\b[a-z]+:[a-z0-9:_-]{10,}\b/gi, ' ')
    .replace(/\[\s*\]/g, ' ')
    .replace(/\s+/g, ' ')

  for (const term of BANNED_TERMS) {
    text = text.replace(new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), ' ')
  }

  text = text
    .replace(/The reviewed notice content triggers GDPR transparency analysis\.?/gi, '')
    .replace(/Observation:\s*/gi, '')
    .replace(/substantive disclosure signal detected\.?/gi, 'The notice text suggests disclosure is present, but key details remain unclear.')
    .replace(/\s+/g, ' ')
    .trim()

  if (/^(n\/?a|null|none|undefined|-|\[\])$/i.test(text)) return ''
  return text
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
  if (base === 'low') {
    const i = (issue ?? '').toLowerCase()
    if (/(legal_basis|complaint|rights|transfer|profil)/.test(i)) return 'High'
    return 'Low'
  }
  const i = (issue ?? '').toLowerCase()
  if (/(legal_basis|complaint|rights|transfer|profil)/.test(i)) return 'High'
  if (/(retention|recipient|purpose|role)/.test(i)) return 'Medium'
  return 'Low'
}

function titleFrom(issue: string | null, fallback: string): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  if (ISSUE_TITLES[normalized]) return ISSUE_TITLES[normalized]
  const cleanFallback = sanitizeUserFacingText(fallback)
  if (cleanFallback && !/^[0-9a-f-]{12,}$/i.test(cleanFallback) && !cleanFallback.toLowerCase().includes('compliance finding requiring review')) {
    return cleanFallback.slice(0, 92)
  }
  return 'GDPR transparency disclosure gap'
}

function issueSubject(issue: string | null, title: string): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  if (ISSUE_SUBJECT[normalized]) return ISSUE_SUBJECT[normalized]
  return title.toLowerCase()
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

function evidenceText(sectionTitle: string | null, excerpt: string, issue: string | null, title: string): { mode: 'excerpt' | 'full_document_absence'; text: string } {
  const e = sanitizeUserFacingText(excerpt)
  if (e) return { mode: 'excerpt', text: `${sectionTitle ?? 'Section'}: ${e}` }
  return {
    mode: 'full_document_absence',
    text: `Confirmed after review of the full document: no disclosure of ${issueSubject(issue, title)} was identified.`,
  }
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

function hasHumanEvidence(finding: NormalizedFinding): boolean {
  const text = sanitizeUserFacingText(finding.evidence_text)
  if (!text) return false
  if (/no supporting excerpt available in the current view/i.test(text)) return false
  if (text === '[]') return false
  return true
}

function passesSanitizer(finding: NormalizedFinding): boolean {
  const blob = [
    finding.title,
    finding.why_this_matters,
    finding.recommended_action,
    finding.evidence_text,
    ...finding.legal_anchors,
    ...finding.details,
  ].join(' ').toLowerCase()
  if (!blob.trim()) return false
  if (/\[[\s]*\]/.test(blob)) return false
  if (/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i.test(blob)) return false
  return !BANNED_TERMS.some((term) => blob.includes(term.toLowerCase()))
}

function hasLegalAnchorsIfNeeded(finding: NormalizedFinding): boolean {
  if (finding.status === 'Compliant') return true
  return finding.legal_anchors.length > 0 || finding.source_mode !== 'published'
}

function normalizePublished(row: FindingOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  const visibilityToken = `${row.classification ?? ''} ${row.publish_flag ?? ''} ${row.finding_type ?? ''}`.toLowerCase()
  if (/(support_only|internal_only|diagnostic_internal_only)/.test(visibilityToken)) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  const issue = row.issue_key ?? scope.issue
  const title = titleFrom(issue, row.section_id)
  const evidence = evidenceText(scope.scope_type === 'section' ? (scope.section_title ?? null) : 'Document-wide evidence', row.citations?.[0]?.excerpt ?? row.citation_summary_text ?? '', issue, title)

  const finding: NormalizedFinding = {
    stable_ui_id: `published:${row.id}`,
    title,
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? (scope.section_title ?? null) : null,
    status: mapStatus(row.status),
    severity: mapSeverity(issue, row.severity),
    why_this_matters: sanitizeUserFacingText(row.gap_note) || 'The notice does not clearly disclose this GDPR transparency requirement.',
    recommended_action: sanitizeUserFacingText(row.remediation_note) || 'Update the notice with explicit GDPR-required disclosure language for this issue.',
    legal_anchors: (row.primary_legal_anchor ?? []).map((a) => sanitizeUserFacingText(a)).filter(Boolean),
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'published',
    section_key: scope.section_key,
    details: [],
  }

  if (!hasHumanEvidence(finding)) return null
  if (!passesSanitizer(finding)) return null
  if (!hasLegalAnchorsIfNeeded(finding)) return null
  return finding
}

function normalizeReview(row: ReviewItemOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  if (row.item_kind === 'review_block' || row.section_id.startsWith('ledger:') || row.section_id.startsWith('review:')) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  const issue = row.issue_type ?? scope.issue
  const title = titleFrom(issue, row.section_id)
  const evidence = evidenceText(scope.scope_type === 'section' ? (scope.section_title ?? null) : 'Document-wide evidence', row.reason ?? row.gap_note ?? '', issue, title)
  return {
    stable_ui_id: `review:${row.id}`,
    title,
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? (scope.section_title ?? null) : null,
    status: mapStatus(row.status ?? row.final_disposition),
    severity: mapSeverity(issue, null),
    why_this_matters: sanitizeUserFacingText(row.gap_note ?? row.reason) || 'This review finding indicates incomplete GDPR transparency disclosure.',
    recommended_action: sanitizeUserFacingText(row.remediation_note) || (scope.scope_type === 'section' ? `In ${scope.section_title ?? 'this section'}, add the missing disclosure in plain legal language.` : 'Add a document-wide disclosure section addressing this requirement.'),
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
  const evidence = evidenceText(scope.scope_type === 'section' ? (scope.section_title ?? null) : 'Document-wide evidence', row.citations?.[0]?.excerpt ?? row.gap_note ?? '', issue, title)
  return {
    stable_ui_id: `analysis:${row.id}`,
    title,
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? (scope.section_title ?? null) : null,
    status: mapStatus(row.status_candidate),
    severity: mapSeverity(issue, null),
    why_this_matters: sanitizeUserFacingText(row.gap_note) || 'Early analysis suggests this disclosure may be incomplete.',
    recommended_action: sanitizeUserFacingText(row.remediation_note) || 'Confirm this issue during review and draft precise disclosure language.',
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
    .map((r) => sanitizeUserFacingText(r.reason) || 'Some findings still require review before final publication.')

  const publishedVisibleFindings = mergeSectionRows(params.publishedRows.map((r) => normalizePublished(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const reviewVisibleFindings = mergeSectionRows(params.reviewRows.map((r) => normalizeReview(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const analysisVisibleFindings = mergeSectionRows(params.analysisRows.map((r) => normalizeAnalysis(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])

  const reportMode: 'published' | 'review' = params.publishedBlocked ? 'review' : 'published'
  const reportExportFindings = reportMode === 'published' ? publishedVisibleFindings : reviewVisibleFindings
  const reportDatasetLabel = reportMode === 'published' ? 'Final published findings' : 'Review findings (final publication blocked)'

  return {
    publishedVisibleFindings,
    reviewVisibleFindings,
    analysisVisibleFindings,
    reportExportFindings,
    publishedBlocked: params.publishedBlocked,
    publishedBlockers: blockers,
    reportMode,
    reportDatasetLabel,
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

export function validateReportExportReadiness(presentation: FindingsPresentation): { ok: boolean; errors: string[] } {
  const errors: string[] = []
  const rows = presentation.reportExportFindings
  for (const row of rows) {
    if (!hasHumanEvidence(row)) errors.push(`Missing evidence for ${row.title}`)
    if (!passesSanitizer(row)) errors.push(`Unsanitized text remains in ${row.title}`)
    if (!row.severity || !['High', 'Medium', 'Low'].includes(row.severity)) errors.push(`Invalid severity for ${row.title}`)
  }
  if (presentation.reportMode === 'published' && presentation.reportDatasetLabel !== 'Final published findings') {
    errors.push('Dataset label mismatch for published export mode')
  }
  if (presentation.reportMode === 'review' && presentation.reportDatasetLabel !== 'Review findings (final publication blocked)') {
    errors.push('Dataset label mismatch for review export mode')
  }
  return { ok: errors.length === 0, errors }
}

export function buildReviewSummary(findings: NormalizedFinding[]): string | null {
  const nonCompliant = findings.filter((f) => f.status === 'Non-compliant' || f.status === 'Partially compliant')
  if (nonCompliant.length === 0) return null
  const uniqueTitles = Array.from(new Set(nonCompliant.map((f) => f.title))).slice(0, 4)
  return `Review identified likely issues with ${uniqueTitles.join(', ').toLowerCase()}.`
}

export function containsBannedUserText(value: string): boolean {
  const normalized = value.toLowerCase()
  return BANNED_TERMS.some((term) => normalized.includes(term)) || /\[[\s]*\]/.test(normalized)
}
