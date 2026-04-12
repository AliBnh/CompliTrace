import type { AnalysisItemOut, FindingOut, ReviewItemOut, SectionOut } from './types'

export type UserStatus = 'Compliant' | 'Partially compliant' | 'Non-compliant' | 'Not applicable'
export type UserSeverity = 'High' | 'Medium' | 'Low'
export type SourceMode = 'published' | 'review' | 'analysis'
export type DatasetKey = 'publishedVisibleFindings' | 'reviewVisibleFindings' | 'analysisVisibleFindings' | 'reportExportFindings'

export type NormalizedFinding = {
  stable_ui_id: string
  title: string
  issue_label: string
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
  datasetLabels: Record<DatasetKey, string>
  publishedBlocked: boolean
  publishedBlockers: string[]
  reportMode: 'published' | 'review'
  reportDatasetLabel: 'Final published findings' | 'Review findings (final publication blocked)'
}

const BANNED_PATTERNS = [
  'support_only', 'internal_only', 'candidate_issue', 'provisional_local', 'support_evidence', 'post_reviewer_snapshot',
  'meta_section', 'auditability gate', 'not-assessable', 'not_assessable', 'confirmed_document_gap', 'probable_document_gap',
  'clear_non_compliance', 'duty validation marked', 'filtered by', 'explicit violation validator matched', 'validator token',
  'no explicit evidence refs from final map',
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

const ISSUE_LABELS: Record<string, string> = {
  missing_complaint_right: 'Complaint-right disclosure',
  missing_legal_basis: 'Legal basis disclosure',
  missing_retention_period: 'Retention disclosure',
  profiling_disclosure_gap: 'Profiling transparency',
  recipients_disclosure_gap: 'Recipients disclosure',
  purpose_specificity_gap: 'Purpose specificity',
  missing_rights_notice: 'Rights notice disclosure',
  missing_transfer_notice: 'Transfer disclosure',
  controller_processor_role_ambiguity: 'Role allocation',
}

const WHY_TEXT: Record<string, string> = {
  missing_complaint_right: 'The notice does not explain the right to lodge a complaint with a supervisory authority.',
  missing_legal_basis: 'The notice describes processing activities but does not state the lawful basis for those activities.',
  missing_retention_period: 'The notice does not explain how long personal data is kept or the criteria used to decide retention periods.',
  profiling_disclosure_gap: 'The notice refers to profiling but does not explain the logic, significance, or likely consequences for individuals.',
  recipients_disclosure_gap: 'The notice does not clearly identify recipient categories for the personal data disclosed in the notice.',
  purpose_specificity_gap: 'The categories of personal data are described, but the related purpose mapping is not sufficiently explicit.',
  missing_rights_notice: 'The notice does not clearly explain the data subject rights that apply to this processing.',
  missing_transfer_notice: 'The notice refers to international transfers but does not explain the safeguard relied upon.',
  controller_processor_role_ambiguity: 'The notice does not clearly explain when the organisation acts as controller or processor.',
}

const ACTION_TEXT: Record<string, string> = {
  missing_complaint_right: 'Add a clear statement that individuals can lodge a complaint with their supervisory authority and include a practical route to do so.',
  missing_legal_basis: 'Add the lawful basis for each processing purpose and link each basis to the relevant activity.',
  missing_retention_period: 'Add concrete retention periods or objective retention criteria for each main data category.',
  profiling_disclosure_gap: 'Add a profiling explanation covering logic used, significance, and likely effects on individuals.',
  recipients_disclosure_gap: 'Add recipient categories for each purpose, including key third-party categories where relevant.',
  purpose_specificity_gap: 'Clarify which personal data categories are used for each purpose so the mapping is explicit.',
  missing_rights_notice: 'Add a rights section that lists access, rectification, erasure, restriction, portability, objection, and withdrawal rights where applicable.',
  missing_transfer_notice: 'Add transfer details, destination context, and safeguard mechanism (for example SCCs) with a short explanation.',
  controller_processor_role_ambiguity: 'Clarify controller and processor roles per processing context and align the notice language with that allocation.',
}

function sanitizeUserFacingText(value?: string | null): string {
  let text = (value ?? '').trim()
  if (!text) return ''
  text = text
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi, ' ')
    .replace(/\b(?:evi|section|evidence|chunk)_id\s*[:=]\s*[a-z0-9:_-]+/gi, ' ')
    .replace(/\b[a-z]+:[a-z0-9:_-]{10,}\b/gi, ' ')
    .replace(/\{\s*\}|\[\s*\]/g, ' ')
    .replace(/filtered by\s*\([^)]*\)/gi, ' ')
    .replace(/\bby\s+\./gi, ' ')

  for (const pattern of BANNED_PATTERNS) {
    text = text.replace(new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), ' ')
  }

  text = text
    .replace(/Observation:\s*/gi, '')
    .replace(/substantive disclosure signal detected\.?/gi, 'The notice text suggests disclosure is present.')
    .replace(/\s+/g, ' ')
    .trim()

  if (/^(n\/?a|null|none|undefined|-|\[\])$/i.test(text)) return ''
  return text
}

function mapStatus(value?: string | null): UserStatus {
  const s = (value ?? '').toLowerCase().replace(/_/g, ' ')
  if (s.includes('gap') || s.includes('non compliant') || s.includes('blocked') || s.includes('candidate')) return 'Non-compliant'
  if (s.includes('partial')) return 'Partially compliant'
  if (s.includes('compliant') || s.includes('satisfied')) return 'Compliant'
  return 'Not applicable'
}

function mapSeverity(issue: string | null, severity?: string | null): UserSeverity {
  const i = (issue ?? '').toLowerCase()
  if (/(legal_basis|complaint|rights|transfer|profil)/.test(i)) return 'High'
  if (/(retention|recipient|purpose|role)/.test(i)) return 'Medium'
  const base = (severity ?? '').toLowerCase()
  if (base === 'high') return 'High'
  if (base === 'medium') return 'Medium'
  return 'Low'
}

function issueTitle(issue: string | null): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  if (ISSUE_TITLES[normalized]) return ISSUE_TITLES[normalized]
  return 'GDPR transparency disclosure issue'
}

function issueLabel(issue: string | null): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  if (ISSUE_LABELS[normalized]) return ISSUE_LABELS[normalized]
  return 'Transparency disclosure'
}

function whyText(issue: string | null, fallback?: string | null): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  return sanitizeUserFacingText(WHY_TEXT[normalized]) || sanitizeUserFacingText(fallback) || 'The notice does not clearly disclose this GDPR transparency requirement.'
}

function actionText(issue: string | null, fallback?: string | null): string {
  const normalized = (issue ?? '').trim().toLowerCase()
  return sanitizeUserFacingText(ACTION_TEXT[normalized]) || sanitizeUserFacingText(fallback) || 'Update the notice with precise GDPR-required disclosure language for this issue.'
}

function scopeInfo(sectionId: string, sectionsById: Record<string, SectionOut>) {
  if (sectionId.startsWith('systemic:')) {
    const issue = sectionId.split('systemic:')[1] ?? ''
    return { scope_type: 'document' as const, scope_label: 'Document-wide finding', section_key: sectionId, issue, section_title: null }
  }
  const section = sectionsById[sectionId]
  if (!section?.section_title) return null
  return {
    scope_type: 'section' as const,
    scope_label: 'Section finding',
    section_key: sectionId,
    issue: null,
    section_title: `Section ${section.section_order}: ${sanitizeUserFacingText(section.section_title)}`,
  }
}

function rowTitle(scopeType: 'section' | 'document', sectionTitle: string | null, issue: string | null): string {
  return scopeType === 'section' ? (sectionTitle ?? 'Document section') : issueTitle(issue)
}

function evidenceText(sectionTitle: string | null, excerpt: string, issue: string | null): { mode: 'excerpt' | 'full_document_absence'; text: string } {
  const e = sanitizeUserFacingText(excerpt)
  if (e) return { mode: 'excerpt', text: `${sectionTitle ?? 'Section'}: "${e}"` }
  return {
    mode: 'full_document_absence',
    text: `Confirmed after review of the full document: no disclosure of ${issueLabel(issue).toLowerCase()} was identified.`,
  }
}

function hasHumanEvidence(finding: NormalizedFinding): boolean {
  const text = sanitizeUserFacingText(finding.evidence_text)
  if (!text) return false
  return /^Section .*: ".+"$/.test(text) || /^Confirmed after review of the full document: no disclosure of .+ was identified\.$/.test(text)
}

function passesSanitizer(finding: NormalizedFinding): boolean {
  const blob = [
    finding.title,
    finding.issue_label,
    finding.why_this_matters,
    finding.recommended_action,
    finding.evidence_text,
    ...finding.legal_anchors,
    ...finding.details,
  ].join(' ').toLowerCase()

  if (!blob.trim()) return false
  if (/\{\s*\}|\[\s*\]|filtered by\s*\([^)]*\)|\bby\s+\./.test(blob)) return false
  if (/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i.test(blob)) return false
  if (/\b(?:section|evidence|chunk)_id\b/.test(blob)) return false
  return !BANNED_PATTERNS.some((term) => blob.includes(term.toLowerCase()))
}

function finalizeFinding(finding: NormalizedFinding): NormalizedFinding | null {
  if (!hasHumanEvidence(finding)) return null
  if (!passesSanitizer(finding)) return null
  if (!finding.title || finding.title === 'GDPR transparency disclosure gap' || finding.title === 'Compliance finding requiring review') return null
  return finding
}

function normalizePublished(row: FindingOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  const visibilityToken = `${row.classification ?? ''} ${row.publish_flag ?? ''} ${row.finding_type ?? ''}`.toLowerCase()
  if (/(support_only|internal_only|diagnostic_internal_only)/.test(visibilityToken)) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  if (!scope) return null
  const issue = row.issue_key ?? scope.issue
  const evidence = evidenceText(scope.scope_type === 'section' ? scope.section_title : 'Section', row.citations?.[0]?.excerpt ?? row.citation_summary_text ?? '', issue)
  return finalizeFinding({
    stable_ui_id: `published:${row.id}`,
    title: rowTitle(scope.scope_type, scope.section_title, issue),
    issue_label: issueLabel(issue),
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? scope.section_title : null,
    status: mapStatus(row.status),
    severity: mapSeverity(issue, row.severity),
    why_this_matters: whyText(issue, row.gap_note),
    recommended_action: actionText(issue, row.remediation_note),
    legal_anchors: (row.primary_legal_anchor ?? []).map((a) => sanitizeUserFacingText(a)).filter(Boolean),
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'published',
    section_key: scope.section_key,
    details: [],
  })
}

function normalizeReview(row: ReviewItemOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  if (row.item_kind === 'review_block' || row.section_id.startsWith('ledger:') || row.section_id.startsWith('review:')) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  if (!scope) return null
  const issue = row.issue_type ?? scope.issue
  const evidence = evidenceText(scope.scope_type === 'section' ? scope.section_title : 'Section', row.reason ?? row.gap_note ?? '', issue)
  return finalizeFinding({
    stable_ui_id: `review:${row.id}`,
    title: rowTitle(scope.scope_type, scope.section_title, issue),
    issue_label: issueLabel(issue),
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? scope.section_title : null,
    status: mapStatus(row.status ?? row.final_disposition),
    severity: mapSeverity(issue, null),
    why_this_matters: whyText(issue, row.gap_note ?? row.reason),
    recommended_action: actionText(issue, row.remediation_note),
    legal_anchors: [],
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'review',
    section_key: scope.section_key,
    details: [],
  })
}

function normalizeAnalysis(row: AnalysisItemOut, sectionsById: Record<string, SectionOut>): NormalizedFinding | null {
  if (/(support_evidence|meta_section|internal)/i.test(`${row.analysis_type} ${row.artifact_role ?? ''} ${row.section_id}`)) return null
  if (row.section_id.startsWith('ledger:')) return null
  const scope = scopeInfo(row.section_id, sectionsById)
  if (!scope) return null
  const issue = row.issue_type ?? scope.issue
  const evidence = evidenceText(scope.scope_type === 'section' ? scope.section_title : 'Section', row.citations?.[0]?.excerpt ?? row.gap_note ?? '', issue)
  return finalizeFinding({
    stable_ui_id: `analysis:${row.id}`,
    title: rowTitle(scope.scope_type, scope.section_title, issue),
    issue_label: issueLabel(issue),
    scope_type: scope.scope_type,
    scope_label: scope.scope_label,
    section_title: scope.scope_type === 'section' ? scope.section_title : null,
    status: mapStatus(row.status_candidate),
    severity: mapSeverity(issue, null),
    why_this_matters: whyText(issue, row.gap_note),
    recommended_action: actionText(issue, row.remediation_note),
    legal_anchors: [],
    evidence_mode: evidence.mode,
    evidence_text: evidence.text,
    visible: true,
    source_mode: 'analysis',
    section_key: scope.section_key,
    details: [],
  })
}

function sortFindings(rows: NormalizedFinding[]): NormalizedFinding[] {
  return [...rows].sort((a, b) => `${a.title}|${a.issue_label}`.localeCompare(`${b.title}|${b.issue_label}`))
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

  const computedPublished = sortFindings(params.publishedRows.map((r) => normalizePublished(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const reviewVisibleFindings = sortFindings(params.reviewRows.map((r) => normalizeReview(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const analysisVisibleFindings = sortFindings(params.analysisRows.map((r) => normalizeAnalysis(r, params.sectionsById)).filter(Boolean) as NormalizedFinding[])
  const publishedVisibleFindings = params.publishedBlocked ? [] : computedPublished

  const reportMode: 'published' | 'review' = params.publishedBlocked ? 'review' : 'published'
  const reportExportFindings = reportMode === 'published' ? publishedVisibleFindings : reviewVisibleFindings
  const reportDatasetLabel = reportMode === 'published' ? 'Final published findings' : 'Review findings (final publication blocked)'

  return {
    publishedVisibleFindings,
    reviewVisibleFindings,
    analysisVisibleFindings,
    reportExportFindings,
    datasetLabels: {
      publishedVisibleFindings: 'Final published findings',
      reviewVisibleFindings: 'Review findings',
      analysisVisibleFindings: 'Analysis findings',
      reportExportFindings: reportDatasetLabel,
    },
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

export function validateReportExportReadiness(
  presentation: FindingsPresentation,
  pdfMeta?: { pdfRenderedFindingsCount: number; pdfDatasetLabel: string },
): { ok: boolean; errors: string[] } {
  const errors: string[] = []
  const rows = presentation.reportExportFindings
  for (const row of rows) {
    if (!hasHumanEvidence(row)) errors.push(`Missing evidence for ${row.title} / ${row.issue_label}`)
    if (!passesSanitizer(row)) errors.push(`Unsanitized text remains in ${row.title} / ${row.issue_label}`)
    if (!['High', 'Medium', 'Low'].includes(row.severity)) errors.push(`Invalid severity for ${row.title} / ${row.issue_label}`)
  }

  const pdfRenderedFindingsCount = pdfMeta?.pdfRenderedFindingsCount ?? rows.length
  const pdfDatasetLabel = pdfMeta?.pdfDatasetLabel ?? presentation.reportDatasetLabel
  if (rows.length !== pdfRenderedFindingsCount) errors.push('Report Center and PDF finding counts diverge')
  if (presentation.reportDatasetLabel !== pdfDatasetLabel) errors.push('Report Center and PDF dataset labels diverge')
  if (rows.length > 0 && pdfRenderedFindingsCount === 0) errors.push('Report Center has findings but PDF would export zero findings')

  return { ok: errors.length === 0, errors }
}

export function buildReviewSummary(findings: NormalizedFinding[]): string | null {
  const nonCompliant = findings.filter((f) => f.status === 'Non-compliant' || f.status === 'Partially compliant')
  if (nonCompliant.length === 0) return null
  const uniqueLabels = Array.from(new Set(nonCompliant.map((f) => f.issue_label))).slice(0, 4)
  return `Review identified likely issues with ${uniqueLabels.join(', ').toLowerCase()}.`
}

export function containsBannedUserText(value: string): boolean {
  const normalized = value.toLowerCase()
  if (/\{\s*\}|\[\s*\]|filtered by\s*\([^)]*\)|\bby\s+\./.test(normalized)) return true
  return BANNED_PATTERNS.some((term) => normalized.includes(term))
}
