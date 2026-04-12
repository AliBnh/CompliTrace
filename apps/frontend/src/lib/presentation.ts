import type { AnalysisItemOut, FindingOut, ReviewItemOut, SectionOut } from './types'

export type UserStatus = 'Compliant' | 'Partially compliant' | 'Non-compliant' | 'Not applicable'
export type UserSeverity = 'High' | 'Medium' | 'Low'
export type SourceMode = 'published' | 'review' | 'analysis'
export type DatasetKey = 'publishedVisibleFindings' | 'reviewVisibleFindings' | 'analysisVisibleFindings' | 'reportExportFindings'

export type Issue = {
  issueKey: string
  issueLabel: string
  status: UserStatus
  severity: UserSeverity
  whyThisMatters: string
  recommendedAction: string
  evidenceText: string
  legalAnchors: string[]
}

export type SectionFinding = {
  stable_ui_id: string
  sectionId: string
  sectionTitle: string
  overallStatus: UserStatus
  severity: UserSeverity
  issues: Issue[]
  sourceMode: SourceMode
}

export type NormalizedFinding = SectionFinding

export type DatasetSummary = {
  compliant: number
  partially_compliant: number
  non_compliant: number
  not_applicable: number
  total: number
}

export type FindingsPresentation = {
  publishedVisibleFindings: SectionFinding[]
  reviewVisibleFindings: SectionFinding[]
  analysisVisibleFindings: SectionFinding[]
  reportExportFindings: SectionFinding[]
  datasetLabels: Record<DatasetKey, string>
  publishedBlocked: boolean
  publishedBlockers: string[]
  reportMode: 'published' | 'review'
  reportDatasetLabel: 'Final published findings' | 'Review findings (used because publication is blocked)'
}

const FALLBACK_CONTEXT = 'This issue requires additional context before publication.'

const BANNED_PATTERNS = [
  'support_only', 'internal_only', 'candidate_issue', 'provisional_local', 'support_evidence', 'post_reviewer_snapshot',
  'meta_section', 'auditability gate', 'not-assessable', 'not_assessable', 'confirmed_document_gap', 'probable_document_gap',
  'clear_non_compliance', 'duty validation marked', 'filtered by', 'explicit violation validator matched', 'validator token',
  'no explicit evidence refs from final map', 'withheld by final publication validator',
]

const ISSUE_LABELS: Record<string, string> = {
  legal_basis: 'Legal basis disclosure',
  rights_notice: 'Data subject rights disclosure',
  complaint_right: 'Complaint right disclosure',
  transfers: 'Transfer safeguards disclosure',
  cookies: 'Cookie transparency disclosure',
  profiling: 'Profiling transparency',
  governance: 'Governance and compliance disclosure',
  contact: 'Contact information disclosure',
  retention: 'Retention disclosure',
  recipients: 'Recipients disclosure',
  purpose: 'Purpose disclosure',
  role_ambiguity: 'Role allocation disclosure',
  wording_only: 'Wording clarity issue',
}

const ISSUE_ALIASES: Record<string, string> = {
  missing_legal_basis: 'legal_basis',
  missing_rights_notice: 'rights_notice',
  missing_complaint_right: 'complaint_right',
  missing_transfer_notice: 'transfers',
  profiling_disclosure_gap: 'profiling',
  governance_disclosure_gap: 'governance',
  contact_disclosure_gap: 'contact',
  cookie_disclosure_gap: 'cookies',
  missing_retention_period: 'retention',
  recipients_disclosure_gap: 'recipients',
  purpose_specificity_gap: 'purpose',
  controller_processor_role_ambiguity: 'role_ambiguity',
  role_ambiguity: 'role_ambiguity',
  wording_only: 'wording_only',
}

const WHY_TEXT: Record<string, string> = {
  legal_basis: 'Missing lawful basis mapping means people cannot understand the legal grounds required under GDPR Articles 13 and 6.',
  rights_notice: 'Missing rights disclosures prevents data subjects from understanding and exercising rights required by GDPR Articles 13 and 15-22.',
  complaint_right: 'Missing complaint-right guidance prevents users from understanding supervisory authority recourse required by GDPR Article 13(2)(d).',
  transfers: 'Missing transfer safeguards disclosure obscures Chapter V protections required when data is sent internationally.',
  cookies: 'Missing cookie transparency prevents informed notice about cookie processing purposes and legal basis obligations under GDPR transparency duties.',
  profiling: 'Missing profiling transparency hides decision logic and effects, undermining GDPR Articles 13(2)(f), 14(2)(g), and 22 safeguards.',
  governance: 'Missing governance and compliance disclosure weakens accountability transparency expected under GDPR Articles 5(2) and 24.',
  contact: 'Missing contact information prevents data subjects from reaching the controller or DPO as required by GDPR Article 13(1).',
  retention: 'Missing retention disclosures means users cannot tell how long data is kept, violating GDPR Article 13(2)(a) transparency duties.',
  recipients: 'Missing recipients disclosures prevents understanding of who receives data under GDPR Article 13(1)(e).',
  purpose: 'Unclear purpose mapping reduces transparency about why data is processed, conflicting with GDPR Articles 5(1)(b) and 13(1)(c).',
  role_ambiguity: 'Controller/processor ambiguity prevents users from understanding responsibility allocations required under GDPR accountability rules.',
  wording_only: 'Ambiguous wording can still mislead users and undermine GDPR transparency even when core sections exist.',
}

const ACTION_TEXT: Record<string, string> = {
  legal_basis: 'Add explicit lawful basis statements for each processing purpose.',
  rights_notice: 'Add a complete rights section with access, rectification, erasure, objection, portability, and complaint routes.',
  complaint_right: 'Add a clear supervisory authority complaint-right statement and practical submission instructions.',
  transfers: 'Add transfer destinations and safeguard mechanisms (for example SCCs) with a concise explanation.',
  cookies: 'Add cookie categories, purposes, legal basis, and user controls.',
  profiling: 'Add profiling logic, significance, and likely consequences for affected individuals.',
  governance: 'Add governance accountability information including compliance ownership and review cadence.',
  contact: 'Add controller contact details and DPO contact details where applicable.',
  retention: 'Add retention periods or objective retention criteria by data category.',
  recipients: 'Add clear recipient categories and third-party sharing details.',
  purpose: 'Add explicit mapping between personal data categories and processing purposes.',
  role_ambiguity: 'Clarify controller versus processor role by processing context.',
  wording_only: 'Revise language for plain, specific, unambiguous disclosures.',
}

function sanitizeUserFacingText(value?: string | null): string {
  let text = (value ?? '').trim()
  if (!text) return ''

  text = text
    .replace(/\[[^\]]*\]|\([^)]*\)/g, ' ')
    .replace(/\b[a-z0-9_]+_without_[a-z0-9_]+\b/gi, ' ')
    .replace(/withheld by final publication validator/gi, ' ')
    .replace(/Section\s*\(\s*\)\.?/gi, ' ')
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi, ' ')
    .replace(/\b(?:evi|section|evidence|chunk)_id\s*[:=]\s*[a-z0-9:_-]+/gi, ' ')
    .replace(/\b[a-z]+:[a-z0-9:_-]{10,}\b/gi, ' ')
    .replace(/\{\s*\}|\[\s*\]/g, ' ')

  for (const pattern of BANNED_PATTERNS) {
    text = text.replace(new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), ' ')
  }

  text = text.replace(/Observation:\s*/gi, '').replace(/\s+/g, ' ').trim()
  if (/^(n\/?a|null|none|undefined|-|\[\])$/i.test(text)) return ''
  return text
}

function sanitizeOrFallback(value?: string | null): string {
  const sanitized = sanitizeUserFacingText(value)
  return sanitized || FALLBACK_CONTEXT
}

function mapStatus(value?: string | null): UserStatus {
  const s = (value ?? '').toLowerCase().replace(/_/g, ' ')
  if (s.includes('gap') || s.includes('non compliant') || s.includes('blocked') || s.includes('candidate')) return 'Non-compliant'
  if (s.includes('partial')) return 'Partially compliant'
  if (s.includes('compliant') || s.includes('satisfied')) return 'Compliant'
  return 'Not applicable'
}

function canonicalIssueKey(value?: string | null): string {
  const normalized = (value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  return ISSUE_ALIASES[normalized] ?? normalized
}

function issueLabel(issue: string): string {
  return ISSUE_LABELS[issue] ?? 'Compliance disclosure issue'
}

function whyText(issue: string, fallback?: string | null): string {
  return sanitizeOrFallback(WHY_TEXT[issue] ?? fallback)
}

function actionText(issue: string, fallback?: string | null): string {
  return sanitizeOrFallback(ACTION_TEXT[issue] ?? fallback)
}

function mapSeverity(issue: string, raw?: string | null): UserSeverity {
  if (['legal_basis', 'rights_notice', 'complaint_right', 'transfers', 'profiling'].includes(issue)) return 'High'
  if (['retention', 'recipients', 'purpose', 'role_ambiguity'].includes(issue)) return 'Medium'
  if (issue === 'wording_only') return 'Low'

  const base = (raw ?? '').toLowerCase()
  if (base === 'high') return 'High'
  if (base === 'medium') return 'Medium'
  return 'Low'
}

function sectionTitleFor(sectionId: string, sectionsById: Record<string, SectionOut>): string | null {
  if (sectionId.startsWith('systemic:')) return 'Document-wide finding'
  const section = sectionsById[sectionId]
  if (!section?.section_title?.trim()) return null
  const title = sanitizeUserFacingText(section.section_title)
  if (!title) return null
  return `Section ${section.section_order}: ${title}`
}

function evidenceText(sectionTitle: string, excerpt?: string | null, issue?: string): string {
  const sanitized = sanitizeUserFacingText(excerpt)
  if (sanitized) return `${sectionTitle}: "${sanitized}"`
  return `Confirmed after review of the full document: no disclosure of ${(issueLabel(issue ?? 'compliance_issue')).toLowerCase()} was identified.`
}

function hasInternalText(value: string): boolean {
  const normalized = value.toLowerCase()
  if (/\{\s*\}|\[\s*\]|\[.*\]|\(.*\)|\b[a-z0-9_]+_without_[a-z0-9_]+\b/.test(normalized)) return true
  return BANNED_PATTERNS.some((pattern) => normalized.includes(pattern))
}

function severityRank(severity: UserSeverity): number {
  if (severity === 'High') return 3
  if (severity === 'Medium') return 2
  return 1
}

function statusRank(status: UserStatus): number {
  if (status === 'Non-compliant') return 4
  if (status === 'Partially compliant') return 3
  if (status === 'Not applicable') return 2
  return 1
}

function buildIssue(params: {
  issueKeyRaw?: string | null
  statusRaw?: string | null
  severityRaw?: string | null
  gapNote?: string | null
  remediationNote?: string | null
  excerpt?: string | null
  sectionTitle: string
  legalAnchors?: string[] | null
}): Issue {
  const issueKey = canonicalIssueKey(params.issueKeyRaw)
  return {
    issueKey,
    issueLabel: issueLabel(issueKey),
    status: mapStatus(params.statusRaw),
    severity: mapSeverity(issueKey, params.severityRaw),
    whyThisMatters: whyText(issueKey, params.gapNote),
    recommendedAction: actionText(issueKey, params.remediationNote),
    evidenceText: sanitizeOrFallback(evidenceText(params.sectionTitle, params.excerpt, issueKey)),
    legalAnchors: (params.legalAnchors ?? []).map((x) => sanitizeUserFacingText(x)).filter(Boolean),
  }
}

function normalizePublished(rows: FindingOut[], sectionsById: Record<string, SectionOut>): SectionFinding[] {
  return rows.flatMap((row) => {
    const visibilityToken = `${row.classification ?? ''} ${row.publish_flag ?? ''} ${row.finding_type ?? ''}`.toLowerCase()
    if (/(support_only|internal_only|diagnostic_internal_only)/.test(visibilityToken)) return []
    const sectionTitle = sectionTitleFor(row.section_id, sectionsById)
    if (!sectionTitle) return []
    return [{
      stable_ui_id: `published:${row.id}`,
      sectionId: row.section_id,
      sectionTitle,
      overallStatus: mapStatus(row.status),
      severity: 'Low' as UserSeverity,
      issues: [
        buildIssue({
          issueKeyRaw: row.issue_key ?? row.section_id.split('systemic:')[1],
          statusRaw: row.status,
          severityRaw: row.severity,
          gapNote: row.gap_note,
          remediationNote: row.remediation_note,
          excerpt: row.citations?.[0]?.excerpt ?? row.citation_summary_text,
          sectionTitle,
          legalAnchors: row.primary_legal_anchor ?? [],
        }),
      ],
      sourceMode: 'published',
    }]
  })
}

function normalizeReview(rows: ReviewItemOut[], sectionsById: Record<string, SectionOut>): SectionFinding[] {
  return rows.flatMap((row) => {
    if (row.item_kind === 'review_block' || row.section_id.startsWith('ledger:') || row.section_id.startsWith('review:')) return []
    const sectionTitle = sectionTitleFor(row.section_id, sectionsById)
    if (!sectionTitle) return []
    return [{
      stable_ui_id: `review:${row.id}`,
      sectionId: row.section_id,
      sectionTitle,
      overallStatus: mapStatus(row.status ?? row.final_disposition),
      severity: 'Low' as UserSeverity,
      issues: [
        buildIssue({
          issueKeyRaw: row.issue_type,
          statusRaw: row.status ?? row.final_disposition,
          gapNote: row.gap_note ?? row.reason,
          remediationNote: row.remediation_note,
          excerpt: row.reason ?? row.gap_note,
          sectionTitle,
        }),
      ],
      sourceMode: 'review',
    }]
  })
}

function normalizeAnalysis(rows: AnalysisItemOut[], sectionsById: Record<string, SectionOut>): SectionFinding[] {
  return rows.flatMap((row) => {
    if (/(support_evidence|meta_section|internal)/i.test(`${row.analysis_type} ${row.artifact_role ?? ''} ${row.section_id}`)) return []
    if (row.section_id.startsWith('ledger:')) return []
    const sectionTitle = sectionTitleFor(row.section_id, sectionsById)
    if (!sectionTitle) return []
    return [{
      stable_ui_id: `analysis:${row.id}`,
      sectionId: row.section_id,
      sectionTitle,
      overallStatus: mapStatus(row.status_candidate),
      severity: 'Low' as UserSeverity,
      issues: [
        buildIssue({
          issueKeyRaw: row.issue_type,
          statusRaw: row.status_candidate,
          gapNote: row.gap_note,
          remediationNote: row.remediation_note,
          excerpt: row.citations?.[0]?.excerpt ?? row.gap_note,
          sectionTitle,
        }),
      ],
      sourceMode: 'analysis',
    }]
  })
}

function collapseToSectionRows(rows: SectionFinding[]): SectionFinding[] {
  const map = new Map<string, SectionFinding>()
  for (const row of rows) {
    const key = `${row.sourceMode}:${row.sectionId}`
    const existing = map.get(key)
    if (!existing) {
      map.set(key, { ...row })
      continue
    }
    const seen = new Set(existing.issues.map((x) => x.issueKey))
    for (const issue of row.issues) {
      if (!seen.has(issue.issueKey)) {
        existing.issues.push(issue)
        seen.add(issue.issueKey)
      }
    }
  }

  return Array.from(map.values())
    .map((row) => {
      const issues = [...row.issues].sort((a, b) => a.issueLabel.localeCompare(b.issueLabel))
      const overallStatus = issues.reduce((worst, issue) => (statusRank(issue.status) > statusRank(worst) ? issue.status : worst), 'Compliant' as UserStatus)
      const severity = issues.reduce((worst, issue) => (severityRank(issue.severity) > severityRank(worst) ? issue.severity : worst), 'Low' as UserSeverity)
      return {
        ...row,
        stable_ui_id: `${row.sourceMode}:${row.sectionId}`,
        issues,
        overallStatus,
        severity,
      }
    })
    .sort((a, b) => a.sectionTitle.localeCompare(b.sectionTitle))
}

function computeBlockedReviewRows(reviewRows: ReviewItemOut[]): string[] {
  return reviewRows
    .filter((r) => r.item_kind === 'review_block' && mapStatus(r.final_disposition) !== 'Compliant')
    .map((r) => sanitizeOrFallback(r.reason))
}

export function buildFindingsPresentation(params: {
  publishedRows: FindingOut[]
  reviewRows: ReviewItemOut[]
  analysisRows: AnalysisItemOut[]
  sectionsById: Record<string, SectionOut>
  publishedBlocked: boolean
}): FindingsPresentation {
  const publishedVisibleFindings = params.publishedBlocked
    ? []
    : collapseToSectionRows(normalizePublished(params.publishedRows, params.sectionsById))

  const reviewVisibleFindings = collapseToSectionRows(normalizeReview(params.reviewRows, params.sectionsById))
  const analysisVisibleFindings = collapseToSectionRows(normalizeAnalysis(params.analysisRows, params.sectionsById))

  const reportMode: 'published' | 'review' = params.publishedBlocked ? 'review' : 'published'
  const reportExportFindings = reportMode === 'published' ? publishedVisibleFindings : reviewVisibleFindings
  const reportDatasetLabel = reportMode === 'published' ? 'Final published findings' : 'Review findings (used because publication is blocked)'

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
    publishedBlockers: computeBlockedReviewRows(params.reviewRows),
    reportMode,
    reportDatasetLabel,
  }
}

export function aggregateCounts(rows: SectionFinding[]): DatasetSummary {
  const out: DatasetSummary = { compliant: 0, partially_compliant: 0, non_compliant: 0, not_applicable: 0, total: rows.length }
  for (const row of rows) {
    if (row.overallStatus === 'Compliant') out.compliant += 1
    else if (row.overallStatus === 'Partially compliant') out.partially_compliant += 1
    else if (row.overallStatus === 'Non-compliant') out.non_compliant += 1
    else out.not_applicable += 1
  }
  return out
}

export function validateReportExportReadiness(
  presentation: FindingsPresentation,
  pdfMeta?: { pdfRenderedFindingsCount: number; pdfDatasetLabel: string; pdfRows?: SectionFinding[] },
): { ok: boolean; errors: string[] } {
  const errors = validatePresentationInvariants(presentation, pdfMeta)
  return { ok: errors.length === 0, errors }
}

export function validatePresentationInvariants(
  presentation: FindingsPresentation,
  pdfMeta?: { pdfRenderedFindingsCount: number; pdfDatasetLabel: string; pdfRows?: SectionFinding[] },
): string[] {
  const errors: string[] = []

  const reportCounts = aggregateCounts(presentation.reportExportFindings)
  const reportCountSum = reportCounts.compliant + reportCounts.partially_compliant + reportCounts.non_compliant + reportCounts.not_applicable
  if (reportCountSum !== presentation.reportExportFindings.length) errors.push('Report counts must equal report dataset length')

  if (presentation.publishedBlocked && JSON.stringify(presentation.reportExportFindings) !== JSON.stringify(presentation.reviewVisibleFindings)) {
    errors.push('Report dataset must equal review dataset when publication is blocked')
  }

  const pdfCount = pdfMeta?.pdfRenderedFindingsCount ?? presentation.reportExportFindings.length
  const pdfLabel = pdfMeta?.pdfDatasetLabel ?? presentation.reportDatasetLabel
  const pdfRows = pdfMeta?.pdfRows ?? presentation.reportExportFindings

  if (pdfCount !== presentation.reportExportFindings.length) errors.push('PDF dataset must equal reportExportFindings count')
  if (pdfLabel !== presentation.reportDatasetLabel) errors.push('PDF dataset label must equal Report Center label')
  if (JSON.stringify(pdfRows) !== JSON.stringify(presentation.reportExportFindings)) errors.push('PDF dataset must equal reportExportFindings')

  const datasets: Array<[string, SectionFinding[]]> = [
    ['publishedVisibleFindings', presentation.publishedVisibleFindings],
    ['reviewVisibleFindings', presentation.reviewVisibleFindings],
    ['analysisVisibleFindings', presentation.analysisVisibleFindings],
    ['reportExportFindings', presentation.reportExportFindings],
  ]

  for (const [name, rows] of datasets) {
    const keys = new Set<string>()
    for (const row of rows) {
      const dedupeKey = `${row.sourceMode}:${row.sectionId}`
      if (keys.has(dedupeKey)) errors.push(`Duplicate section rows detected in ${name}`)
      keys.add(dedupeKey)

      if (!sanitizeUserFacingText(row.sectionTitle)) errors.push(`Missing valid sectionTitle in ${name}`)
      if (!row.issues.length) errors.push(`Missing issues in ${name} for section ${row.sectionId}`)

      for (const issue of row.issues) {
        if (!sanitizeUserFacingText(issue.whyThisMatters)) errors.push(`Missing Why this matters in ${name} for section ${row.sectionId}`)
        if (hasInternalText(issue.whyThisMatters) || hasInternalText(issue.evidenceText) || hasInternalText(issue.recommendedAction)) {
          errors.push(`Unsanitized content in ${name} for section ${row.sectionId}`)
        }
      }
    }
  }

  if (presentation.reportExportFindings.length === 0 && (presentation.reviewVisibleFindings.length > 0 || presentation.publishedVisibleFindings.length > 0)) {
    errors.push('Report dataset empty while UI has findings')
  }

  return errors
}

export function buildReviewSummary(findings: SectionFinding[]): string | null {
  const issues = findings
    .filter((f) => f.overallStatus === 'Non-compliant' || f.overallStatus === 'Partially compliant')
    .flatMap((f) => f.issues.map((i) => i.issueLabel))
  if (!issues.length) return null
  const uniqueLabels = Array.from(new Set(issues)).slice(0, 4)
  return `Review identified likely issues with ${uniqueLabels.join(', ').toLowerCase()}.`
}

export function containsBannedUserText(value: string): boolean {
  return hasInternalText(value)
}
