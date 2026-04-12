import type { AnalysisItemOut, FindingOut, ReviewItemOut, SectionOut } from './types'

export type UserStatus = 'Compliant' | 'Partially compliant' | 'Non-compliant' | 'Not applicable'
export type UserSeverity = 'High' | 'Medium' | 'Low'
export type SourceMode = 'published' | 'review' | 'analysis'
export type DatasetKey = 'publishedVisibleFindings' | 'reviewVisibleFindings' | 'analysisVisibleFindings' | 'reportExportFindings'

const CANONICAL_ISSUE_LABELS = [
  'Legal basis disclosure',
  'Data subject rights disclosure',
  'Complaint-right disclosure',
  'Retention disclosure',
  'Transfer safeguards disclosure',
  'Profiling transparency',
  'Cookie transparency disclosure',
  'Contact information disclosure',
  'Governance and compliance disclosure',
  'Purpose specificity disclosure',
  'Recipients disclosure',
  'Role allocation disclosure',
] as const

export type IssueLabel = typeof CANONICAL_ISSUE_LABELS[number]

export type Issue = {
  issueKey: string
  issueLabel: IssueLabel
  status: UserStatus
  severity: UserSeverity
  whyThisMatters: string
  recommendedAction: string
  evidenceText: string
  legalAnchors: string[]
  citations: Array<{ source_section_title: string; excerpt_text: string; gdpr_articles: string[]; evidence_reasoning_link: string }>
}

export type SectionFinding = {
  stable_ui_id: string
  sectionId: string
  sectionTitle: string
  scope: 'Section' | 'Document-wide'
  overallStatus: UserStatus
  overallSeverity: UserSeverity
  primaryIssueLabel: IssueLabel
  issueCount: number
  issues: Issue[]
  sourceMode: SourceMode
}

export type DocumentFinding = {
  stable_ui_id: string
  issueKey: string
  title: string
  status: UserStatus
  severity: UserSeverity
  whyThisMatters: string
  recommendation: string
  evidence: string
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
const WHY_FALLBACK = 'The notice does not provide enough clear detail to verify this required disclosure.'
const ABSENCE_PREFIX = 'Confirmed after review of the full document: no'
const DEBUG_OR_INTERNAL = /(signal detected|validator|suppressed|duty-level|reconciliation|candidate_issue|internal_only|support_only|meta_section|legal gate)/i

const BANNED_PATTERNS = [
  'support_only', 'internal_only', 'candidate_issue', 'provisional_local', 'support_evidence', 'post_reviewer_snapshot',
  'meta_section', 'auditability gate', 'not-assessable', 'not_assessable', 'confirmed_document_gap', 'probable_document_gap',
  'clear_non_compliance', 'duty validation marked', 'filtered by', 'explicit violation validator matched', 'validator token',
  'no explicit evidence refs from final map', 'withheld by final publication validator',
  'signal detected', 'legal gate', 'duty-level', 'reconciliation', 'suppressed',
  'not assessable from provided excerpt', 'finding promoted to substantive non-compliance', 'strict legal gate',
]

const ISSUE_ALIASES: Record<string, string> = {
  missing_legal_basis: 'legal_basis',
  legal_basis: 'legal_basis',
  missing_rights_notice: 'rights_notice',
  rights_notice: 'rights_notice',
  missing_complaint_right: 'complaint_right',
  complaint_right: 'complaint_right',
  missing_transfer_notice: 'transfers',
  transfers: 'transfers',
  profiling_disclosure_gap: 'profiling',
  profiling: 'profiling',
  governance_disclosure_gap: 'governance',
  governance: 'governance',
  contact_disclosure_gap: 'contact',
  missing_controller_contact: 'contact',
  missing_controller_identity: 'contact',
  contact: 'contact',
  cookie_disclosure_gap: 'cookies',
  cookies: 'cookies',
  missing_retention_period: 'retention',
  retention: 'retention',
  recipients_disclosure_gap: 'recipients',
  recipients: 'recipients',
  purpose_specificity_gap: 'purpose',
  purpose: 'purpose',
  controller_processor_role_ambiguity: 'role_ambiguity',
  role_ambiguity: 'role_ambiguity',
  wording_only: 'wording_only',
}

const ISSUE_LABELS: Record<string, IssueLabel> = {
  legal_basis: 'Legal basis disclosure',
  rights_notice: 'Data subject rights disclosure',
  complaint_right: 'Complaint-right disclosure',
  transfers: 'Transfer safeguards disclosure',
  cookies: 'Cookie transparency disclosure',
  profiling: 'Profiling transparency',
  governance: 'Governance and compliance disclosure',
  contact: 'Contact information disclosure',
  retention: 'Retention disclosure',
  recipients: 'Recipients disclosure',
  purpose: 'Purpose specificity disclosure',
  role_ambiguity: 'Role allocation disclosure',
  wording_only: 'Governance and compliance disclosure',
}

const WHY_TEXT: Record<string, string> = {
  legal_basis: 'The notice describes processing activities but does not state the lawful basis for those activities.',
  rights_notice: 'The notice does not explain the rights available to data subjects in a complete and usable way.',
  complaint_right: 'The notice does not clearly explain that people can lodge a complaint with a supervisory authority.',
  transfers: 'The notice refers to international transfers but does not explain the safeguard relied upon.',
  cookies: 'The notice references cookies or similar technologies without clearly explaining purposes, controls, and legal basis.',
  profiling: 'The notice does not clearly explain profiling logic, significance, or likely consequences where profiling is referenced.',
  governance: 'The notice does not clearly explain governance ownership or compliance accountability for privacy obligations.',
  contact: 'The notice does not provide clear contact details for privacy or data-protection requests.',
  retention: 'The notice does not clearly state retention periods or objective retention criteria.',
  recipients: 'The notice does not clearly identify categories of recipients or third parties receiving personal data.',
  purpose: 'The categories of personal data are described, but the related purpose mapping is not sufficiently explicit.',
  role_ambiguity: 'The notice does not clearly explain when the organization acts as controller or processor.',
  wording_only: 'Important disclosures are drafted in a way that could confuse readers and reduce transparency.',
}

const ACTION_TEXT: Record<string, string> = {
  legal_basis: 'Add a lawful basis statement for each processing purpose in this section.',
  rights_notice: 'Add a complete data-subject rights section covering access, rectification, erasure, restriction, portability, objection, and complaint rights.',
  complaint_right: 'Add a clear complaint-right statement and identify how to contact the relevant supervisory authority.',
  transfers: 'Explain whether international transfers occur and identify the safeguard relied upon.',
  cookies: 'Add clear cookie categories, purposes, legal basis, and user control options.',
  profiling: 'Add clear profiling disclosures describing logic, significance, and likely consequences for individuals.',
  governance: 'Add governance and compliance ownership details, including responsibility and review cadence.',
  contact: 'Add controller contact details and DPO contact details where applicable.',
  retention: 'Add retention periods or objective retention criteria for each relevant data category.',
  recipients: 'Add recipient categories and describe third-party sharing contexts.',
  purpose: 'Clarify which categories of personal data are processed for which purposes.',
  role_ambiguity: 'Clarify controller and processor roles for each processing context.',
  wording_only: 'Replace ambiguous wording with plain-language disclosure text that is specific and complete.',
}

function sanitizeUserFacingText(value?: string | null): string {
  let text = (value ?? '').trim()
  if (!text) return ''

  text = text
    .replace(/\[[^\]]*\]|\([^)]*\)/g, ' ')
    .replace(/\b[a-z0-9_]+_without_[a-z0-9_]+\b/gi, ' ')
    .replace(/Section\s*\(\s*\)\.?/gi, ' ')
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi, ' ')
    .replace(/\b(?:evi|section|evidence|chunk)_id\s*[:=]\s*[a-z0-9:_-]+/gi, ' ')
    .replace(/\b[a-z]+:[a-z0-9:_-]{10,}\b/gi, ' ')
    .replace(/\{\s*\}|\[\s*\]/g, ' ')

  for (const pattern of BANNED_PATTERNS) {
    text = text.replace(new RegExp(pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), ' ')
  }

  text = text
    .replace(/Observation:\s*/gi, '')
    .replace(/substantive disclosure signal detected\.?/gi, 'The notice appears to reference this topic, but required details are missing or unclear.')
    .replace(/section\s*\./gi, 'Section')
    .replace(/\s+/g, ' ')
    .trim()
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
  return ISSUE_ALIASES[normalized] ?? 'legal_basis'
}

function issueLabel(issue: string): IssueLabel {
  return ISSUE_LABELS[issue] ?? 'Legal basis disclosure'
}

function whyText(issue: string, fallback?: string | null): string {
  const sanitized = sanitizeUserFacingText(WHY_TEXT[issue] ?? fallback)
  return sanitized || WHY_FALLBACK
}

function actionText(issue: string, fallback?: string | null): string {
  return sanitizeOrFallback(ACTION_TEXT[issue] ?? fallback)
}

export function mapSeverity(issue: string, raw?: string | null): UserSeverity {
  if (['legal_basis', 'rights_notice', 'complaint_right', 'transfers', 'profiling'].includes(issue)) return 'High'
  if (['retention', 'recipients', 'purpose', 'role_ambiguity', 'governance', 'contact', 'cookies'].includes(issue)) return 'Medium'
  if (issue === 'wording_only') return 'Low'

  const base = (raw ?? '').toLowerCase()
  if (base === 'high') return 'High'
  if (base === 'medium') return 'Medium'
  return 'Low'
}

function sectionTitleFor(sectionId: string, sectionsById: Record<string, SectionOut>): string | null {
  if (sectionId.startsWith('systemic:')) return null
  const section = sectionsById[sectionId]
  if (!section?.section_title?.trim()) return null
  return sanitizeUserFacingText(section.section_title).replace(/^\d+(\.\d+)*\s*[-:.)]?\s*/g, '')
}

function evidenceText(sectionTitle: string, excerpt?: string | null, issue?: string): string {
  const sanitized = sanitizeUserFacingText(excerpt)
  if (sanitized) return `${sectionTitle}: "${sanitized}"`
  return `${ABSENCE_PREFIX} ${issueLabel(issue ?? 'legal_basis').toLowerCase()} was identified.`
}

function hasInternalText(value: string): boolean {
  const normalized = value.toLowerCase()
  if (/\{\s*\}|\[\s*\]|\b[a-z0-9_]+_without_[a-z0-9_]+\b/.test(normalized)) return true
  if (DEBUG_OR_INTERNAL.test(normalized)) return true
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
    citations: [],
  }
}

function normalizePublished(rows: FindingOut[], sectionsById: Record<string, SectionOut>): IssueSeed[] {
  return rows.flatMap((row) => {
    const visibilityToken = `${row.classification ?? ''} ${row.publish_flag ?? ''} ${row.finding_type ?? ''}`.toLowerCase()
    if (/(support_only|internal_only|diagnostic_internal_only)/.test(visibilityToken)) return []
    const isDocument = row.section_id.startsWith('systemic:')
    const sectionTitle = isDocument ? 'Entire document' : sectionTitleFor(row.section_id, sectionsById)
    if (!sectionTitle) return []
    return [{
      sourceMode: 'published' as const,
      rowId: row.id,
      sectionId: row.section_id,
      sectionTitle,
      issue: buildIssue({
        issueKeyRaw: row.issue_key ?? row.section_id.split('systemic:')[1],
        statusRaw: row.status,
        severityRaw: row.severity,
        gapNote: row.gap_note,
        remediationNote: row.remediation_note,
        excerpt: row.citations?.[0]?.excerpt ?? row.citation_summary_text,
        sectionTitle,
        legalAnchors: row.primary_legal_anchor ?? [],
      }),
    }].map((seed) => ({
      ...seed,
      issue: {
        ...seed.issue,
        citations: (row.citations ?? [])
          .filter((c) => sanitizeUserFacingText(c.excerpt))
          .map((c) => ({
            source_section_title: sectionTitle,
            excerpt_text: sanitizeOrFallback(c.excerpt),
            gdpr_articles: [`GDPR Article ${c.article_number}`],
            evidence_reasoning_link: sanitizeOrFallback(row.gap_reasoning ?? row.gap_note),
          })),
      },
    }))
  })
}

type IssueSeed = {
  sourceMode: SourceMode
  rowId: string
  sectionId: string
  sectionTitle: string
  issue: Issue
}

function normalizeReview(rows: ReviewItemOut[], sectionsById: Record<string, SectionOut>): IssueSeed[] {
  return rows.flatMap((row) => {
    if (row.item_kind === 'review_block' || row.section_id.startsWith('ledger:') || row.section_id.startsWith('review:')) return []
    const isDocument = row.section_id.startsWith('systemic:')
    const sectionTitle = isDocument ? 'Entire document' : sectionTitleFor(row.section_id, sectionsById)
    if (!sectionTitle) return []
    return [{
      sourceMode: 'review' as const,
      rowId: row.id,
      sectionId: row.section_id,
      sectionTitle,
      issue: buildIssue({
        issueKeyRaw: row.issue_type,
        statusRaw: row.status ?? row.final_disposition,
        gapNote: row.gap_note ?? row.reason,
        remediationNote: row.remediation_note,
        excerpt: row.citations?.[0]?.excerpt ?? row.reason ?? row.gap_note,
        sectionTitle,
      }),
    }]
    .map((seed) => ({
      ...seed,
      issue: {
        ...seed.issue,
        citations: (row.citations ?? [])
          .filter((c) => sanitizeUserFacingText(c.excerpt))
          .map((c) => ({
            source_section_title: sectionTitle,
            excerpt_text: sanitizeOrFallback(c.excerpt),
            gdpr_articles: [`GDPR Article ${c.article_number}`],
            evidence_reasoning_link: sanitizeOrFallback(row.reason ?? row.gap_note),
          })),
      },
    }))
  })
}

function normalizeAnalysis(rows: AnalysisItemOut[], sectionsById: Record<string, SectionOut>): IssueSeed[] {
  return rows.flatMap((row) => {
    if (/(support_evidence|meta_section|internal)/i.test(`${row.analysis_type} ${row.artifact_role ?? ''} ${row.section_id}`)) return []
    if (row.section_id.startsWith('ledger:')) return []
    const isDocument = row.section_id.startsWith('systemic:')
    const sectionTitle = isDocument ? 'Entire document' : sectionTitleFor(row.section_id, sectionsById)
    if (!sectionTitle) return []
    return [{
      sourceMode: 'analysis' as const,
      rowId: row.id,
      sectionId: row.section_id,
      sectionTitle,
      issue: buildIssue({
        issueKeyRaw: row.issue_type,
        statusRaw: row.status_candidate,
        gapNote: row.gap_note,
        remediationNote: row.remediation_note,
        excerpt: row.citations?.[0]?.excerpt ?? row.gap_note,
        sectionTitle,
      }),
    }]
  })
}

function collapseToSectionRows(seeds: IssueSeed[]): SectionFinding[] {
  const map = new Map<string, { sourceMode: SourceMode; sectionId: string; sectionTitle: string; scope: 'Section' | 'Document-wide'; issues: Issue[] }>()
  for (const seed of seeds) {
    const scope = seed.sectionId.startsWith('systemic:') ? 'Document-wide' : 'Section'
    const key = `${seed.sourceMode}:${seed.sectionId}`
    const existing = map.get(key)
    if (!existing) {
      map.set(key, { sourceMode: seed.sourceMode, sectionId: seed.sectionId, sectionTitle: seed.sectionTitle, scope, issues: [seed.issue] })
      continue
    }
    if (!existing.issues.some((x) => x.issueLabel === seed.issue.issueLabel)) existing.issues.push(seed.issue)
  }

  return Array.from(map.values()).map((row) => {
    const issues = [...row.issues].sort((a, b) => statusRank(b.status) - statusRank(a.status) || severityRank(b.severity) - severityRank(a.severity))
    const overallStatus = issues.reduce((worst, issue) => (statusRank(issue.status) > statusRank(worst) ? issue.status : worst), 'Compliant' as UserStatus)
    const overallSeverity = issues.reduce((worst, issue) => (severityRank(issue.severity) > severityRank(worst) ? issue.severity : worst), 'Low' as UserSeverity)
    const primaryIssueLabel = issues[0]?.issueLabel ?? 'Governance and compliance disclosure'
    return {
      stable_ui_id: `${row.sourceMode}:${row.sectionId}`,
      scope: row.scope,
      sectionId: row.sectionId,
      sectionTitle: row.sectionTitle,
      overallStatus,
      overallSeverity,
      primaryIssueLabel,
      issueCount: issues.length,
      issues,
      sourceMode: row.sourceMode,
    }
    }).sort((a, b) => {
      if (a.scope !== b.scope) return a.scope === 'Document-wide' ? -1 : 1
      return a.sectionTitle.localeCompare(b.sectionTitle)
    })
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
  const publishedVisibleFindings = params.publishedBlocked ? [] : collapseToSectionRows(normalizePublished(params.publishedRows, params.sectionsById))
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
  pdfMeta?: { pdfRenderedFindingsCount: number; pdfDatasetLabel: string; pdfRows?: SectionFinding[]; pdfStatusCounts?: DatasetSummary },
): { ok: boolean; errors: string[] } {
  const errors = validatePresentationInvariants(presentation, pdfMeta)
  return { ok: errors.length === 0, errors }
}

export function validatePresentationInvariants(
  presentation: FindingsPresentation,
  pdfMeta?: { pdfRenderedFindingsCount: number; pdfDatasetLabel: string; pdfRows?: SectionFinding[]; pdfStatusCounts?: DatasetSummary },
): string[] {
  const errors: string[] = []
  const reportStatusCounts = aggregateCounts(presentation.reportExportFindings)
  const reportIds = presentation.reportExportFindings.map((f) => f.stable_ui_id).sort()

  const pdfCount = pdfMeta?.pdfRenderedFindingsCount ?? presentation.reportExportFindings.length
  const pdfLabel = pdfMeta?.pdfDatasetLabel ?? presentation.reportDatasetLabel
  const pdfRows = pdfMeta?.pdfRows ?? presentation.reportExportFindings
  const pdfCounts = pdfMeta?.pdfStatusCounts ?? aggregateCounts(pdfRows)
  const pdfIds = pdfRows.map((f) => f.stable_ui_id).sort()

  if (presentation.publishedBlocked && JSON.stringify(presentation.reportExportFindings) !== JSON.stringify(presentation.reviewVisibleFindings)) {
    errors.push('Report dataset must equal review dataset when publication is blocked')
  }
  if (pdfCount !== presentation.reportExportFindings.length) errors.push('Report dataset count must match PDF finding count')
  if (pdfLabel !== presentation.reportDatasetLabel) errors.push('Report dataset label must match PDF dataset label')
  if (JSON.stringify(pdfCounts) !== JSON.stringify(reportStatusCounts)) errors.push('Report status counts must match PDF status counts')
  if (JSON.stringify(pdfIds) !== JSON.stringify(reportIds)) errors.push('Report finding IDs must match PDF payload IDs')
  if (presentation.reportExportFindings.length === 0 && reportStatusCounts.total > 0) errors.push('Report dataset is empty while Report Center counts are non-empty')

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
      if (/^section\s+\d+:\s*/i.test(row.sectionTitle)) errors.push(`Machine numbering leaked into section title in ${name}`)
      if (row.scope === 'Section' && row.sectionId.startsWith('systemic:')) errors.push(`Document-wide findings appear in section table for ${name}`)
      if (row.issueCount !== row.issues.length) errors.push(`issueCount mismatch in ${name} for section ${row.sectionId}`)
      if (row.primaryIssueLabel !== row.issues[0]?.issueLabel) errors.push(`primaryIssueLabel mismatch in ${name} for section ${row.sectionId}`)

      for (const issue of row.issues) {
        if (!CANONICAL_ISSUE_LABELS.includes(issue.issueLabel)) errors.push(`Non-canonical issue label in ${name} for section ${row.sectionId}`)
        if (!sanitizeUserFacingText(issue.whyThisMatters)) errors.push(`Missing Why this matters in ${name} for section ${row.sectionId}`)
        if (!sanitizeUserFacingText(issue.recommendedAction)) errors.push(`Missing recommendation in ${name} for section ${row.sectionId}`)
        if (!sanitizeUserFacingText(issue.evidenceText) || (!issue.evidenceText.includes(': "') && !issue.evidenceText.startsWith(ABSENCE_PREFIX))) {
          errors.push(`Evidence not human-readable in ${name} for section ${row.sectionId}`)
        }
        if (hasInternalText(issue.whyThisMatters) || hasInternalText(issue.evidenceText) || hasInternalText(issue.recommendedAction)) {
          errors.push(`Unsanitized content in ${name} for section ${row.sectionId}`)
        }
        if (name !== 'analysisVisibleFindings' && row.scope === 'Section' && issue.citations.length === 0) {
          errors.push(`Missing citations for section finding in ${name} for section ${row.sectionId}`)
        }
      }
    }
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

export function splitFindingsByScope(rows: SectionFinding[]): { documentFindings: DocumentFinding[]; sectionFindings: SectionFinding[] } {
  const documentByIssue = new Map<string, DocumentFinding>()
  for (const row of rows.filter((x) => x.sectionId.startsWith('systemic:'))) {
    for (const issue of row.issues) {
      const existing = documentByIssue.get(issue.issueKey)
      const candidate: DocumentFinding = {
        stable_ui_id: `${row.sourceMode}:document:${issue.issueKey}`,
        issueKey: issue.issueKey,
        title: issue.issueLabel,
        status: issue.status,
        severity: issue.severity,
        whyThisMatters: issue.whyThisMatters,
        recommendation: issue.recommendedAction,
        evidence: issue.evidenceText,
        sourceMode: row.sourceMode,
      }
      if (!existing || statusRank(candidate.status) > statusRank(existing.status)) documentByIssue.set(issue.issueKey, candidate)
    }
  }

  return {
    documentFindings: Array.from(documentByIssue.values()).sort((a, b) => a.title.localeCompare(b.title)),
    sectionFindings: rows.filter((row) => !row.sectionId.startsWith('systemic:')),
  }
}

export function severityDisplayForStatus(status: UserStatus, severity: UserSeverity): UserSeverity | null {
  if (status === 'Compliant' || status === 'Not applicable') return null
  return severity
}

export function assertPdfDatasetIntegrity(pdfFindings: SectionFinding[], reportExportFindings: SectionFinding[]): void {
  if (pdfFindings.length !== reportExportFindings.length) throw new Error('PDF dataset mismatch')
  if (JSON.stringify(pdfFindings) !== JSON.stringify(reportExportFindings)) throw new Error('PDF dataset mismatch')
}
