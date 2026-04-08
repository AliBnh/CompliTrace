import { useEffect, useMemo, useState } from 'react'

import { useAppState } from '../../app/state'
import { StatusBadge } from '../../components/StatusBadge'
import { getAnalysis, getAudit, getFindings, getReview, getSections } from '../../lib/api'
import type { AnalysisItemOut, FindingOut, ReviewItemOut, SectionOut } from '../../lib/types'

const SYSTEMIC_LABELS: Record<string, string> = {
  missing_controller_identity: 'Missing controller identity disclosure',
  missing_legal_basis: 'Missing legal basis disclosure',
  missing_retention_period: 'Missing retention period disclosure',
  missing_rights_notice: 'Missing rights notice disclosure',
  missing_complaint_right: 'Missing complaint-right disclosure',
}

export function FindingsPage() {
  const { auditId, documentId } = useAppState()
  const [findings, setFindings] = useState<FindingOut[]>([])
  const [analysisItems, setAnalysisItems] = useState<AnalysisItemOut[]>([])
  const [reviewItems, setReviewItems] = useState<ReviewItemOut[]>([])
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>({})
  const [selectedByView, setSelectedByView] = useState<Record<'published' | 'review' | 'analysis', string | null>>({
    published: null,
    review: null,
    analysis: null,
  })
  const [viewMode, setViewMode] = useState<'published' | 'review' | 'analysis'>('published')
  const [status, setStatus] = useState<string>('pending')
  const [publishedError, setPublishedError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [sectionsError, setSectionsError] = useState<string | null>(null)
  const [uiNotice, setUiNotice] = useState<string | null>(null)
  const [progress, setProgress] = useState<number>(12)

  useEffect(() => {
    if (!documentId) return
    getSections(documentId)
      .then((sections) => {
        const mapping = Object.fromEntries(sections.map((s) => [s.id, s]))
        setSectionsById(mapping)
      })
      .catch((e) => setSectionsError(e.message))
  }, [documentId])

  useEffect(() => {
    if (!auditId) return
    const currentAuditId = auditId
    let cancelled = false

    async function tick() {
      try {
        const audit = await getAudit(currentAuditId)
        if (cancelled) return
        setStatus(audit.status)
        if (audit.status === 'complete') {
          setProgress(100)
        } else if (audit.status === 'running' || audit.status === 'pending') {
          setProgress((previous) => Math.min(previous + Math.random() * 6 + 2, 92))
        }
        const [publishedResult, reviewResult, analysisResult] = await Promise.allSettled([
          getFindings(currentAuditId),
          getReview(currentAuditId),
          getAnalysis(currentAuditId),
        ])
        if (cancelled) return
        if (publishedResult.status === 'fulfilled') {
          setFindings(publishedResult.value)
          setPublishedError(null)
        } else {
          setFindings([])
          const msg = normalizeUiError(publishedResult.reason, 'Unable to load Published findings.')
          setPublishedError(msg)
        }
        if (reviewResult.status === 'fulfilled') {
          setReviewItems(reviewResult.value)
          setReviewError(null)
        } else {
          setReviewItems([])
          setReviewError(normalizeUiError(reviewResult.reason, 'Unable to load Review findings.'))
        }
        if (analysisResult.status === 'fulfilled') {
          setAnalysisItems(analysisResult.value)
          setAnalysisError(null)
        } else {
          setAnalysisItems([])
          setAnalysisError(normalizeUiError(analysisResult.reason, 'Unable to load Analysis findings.'))
        }
      } catch (e) {
        if (!cancelled) setPublishedError(e instanceof Error ? e.message : 'Failed to load findings')
      }
    }

    tick()
    const timer = setInterval(tick, 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [auditId])

  const orderedFindings = useMemo(() => {
    return [...findings].sort((a, b) => {
      const aSystemic = a.finding_type === 'systemic' ? 1 : 0
      const bSystemic = b.finding_type === 'systemic' ? 1 : 0
      if (aSystemic !== bSystemic) return aSystemic - bSystemic
      const aOrder = sectionsById[a.section_id]?.section_order ?? Number.MAX_SAFE_INTEGER
      const bOrder = sectionsById[b.section_id]?.section_order ?? Number.MAX_SAFE_INTEGER
      if (aOrder !== bOrder) return aOrder - bOrder
      return a.id.localeCompare(b.id)
    })
  }, [findings, sectionsById])

  const orderedReviewItems = useMemo(() => {
    return [...reviewItems]
      .filter((item) => !item.section_id.startsWith('ledger:'))
      .filter((item) => {
        if (item.item_kind !== 'review_block') return true
        return (item.final_disposition ?? '').toLowerCase() !== 'satisfied'
      })
      .sort((a, b) => {
        const rank = (row: ReviewItemOut) => {
          if (row.item_kind === 'review_block' && row.review_group === 'core_duties') return 0
          if (row.item_kind === 'review_block' && row.review_group === 'specialist_families') return 1
          if (row.item_kind === 'finding') return 2
          return 3
        }
        const r = rank(a) - rank(b)
        return r !== 0 ? r : a.id.localeCompare(b.id)
      })
  }, [reviewItems])

  const orderedAnalysisItems = useMemo(() => {
    return [...analysisItems].filter((item) => !item.section_id.startsWith('ledger:')).sort((a, b) => a.id.localeCompare(b.id))
  }, [analysisItems])

  const activeRows = viewMode === 'published' ? orderedFindings : viewMode === 'review' ? orderedReviewItems : orderedAnalysisItems
  const selectedId = selectedByView[viewMode]
  const selectedPublished = viewMode === 'published' ? orderedFindings.find((f) => f.id === selectedId) ?? null : null
  const selectedReview = viewMode === 'review' ? orderedReviewItems.find((r) => r.id === selectedId) ?? null : null
  const selectedAnalysis = viewMode === 'analysis' ? orderedAnalysisItems.find((r) => r.id === selectedId) ?? null : null
  const counts = useMemo(() => {
    const base = { compliant: 0, partial: 0, gap: 0, 'needs review': 0, 'not applicable': 0 }
    for (const row of activeRows) {
      const mapped = normalizeStatus(rowStatus(row))
      if (mapped in base) base[mapped] += 1
    }
    return base
  }, [activeRows])
  const publicationBlocked = !!publishedError?.toLowerCase().includes('blocked')
  const blockerCount = useMemo(() => {
    return reviewItems.filter((r) => r.item_kind === 'review_block' && r.final_disposition && !['satisfied'].includes(r.final_disposition)).length
  }, [reviewItems])

  useEffect(() => {
    if (viewMode !== 'published') return
    if (!publishedError?.toLowerCase().includes('blocked')) return
    if (!orderedReviewItems.length) return
    setViewMode('review')
    setUiNotice('Published findings are blocked until review issues are resolved. Showing Review findings instead.')
  }, [publishedError, orderedReviewItems.length, viewMode])

  useEffect(() => {
    setSelectedByView((current) => {
      const existing = current[viewMode]
      if (!activeRows.length) return { ...current, [viewMode]: null }
      if (existing && activeRows.some((row) => row.id === existing)) return current
      return { ...current, [viewMode]: activeRows[0].id }
    })
  }, [viewMode, activeRows])

  if (!auditId) return <EmptyState message="No audit in progress. Trigger an audit from Sections page." />

  return (
    <section className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="space-y-4">
        <header className="surface-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="section-title">Findings workspace</h1>
              <p className="section-subtitle">Audit status: <span className="font-medium text-slate-700 capitalize">{status}</span></p>
            </div>
            <div className="flex items-center gap-3">
              {(status === 'running' || status === 'pending') && (
                <div className="relative h-14 w-14">
                  <svg className="h-14 w-14 -rotate-90" viewBox="0 0 100 100" aria-label="Audit progress">
                    <circle cx="50" cy="50" r="42" strokeWidth="9" className="fill-none stroke-slate-200" />
                    <circle
                      cx="50"
                      cy="50"
                      r="42"
                      strokeWidth="9"
                      strokeDasharray={264}
                      strokeDashoffset={264 - (264 * progress) / 100}
                      className="fill-none stroke-sky-500 transition-all duration-700"
                    />
                  </svg>
                  <span className="absolute inset-0 grid place-items-center text-xs font-semibold text-sky-700">{Math.round(progress)}%</span>
                </div>
              )}
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">{activeRows.length} records</span>
              {publicationBlocked && (
                <span className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800">
                  Published: Blocked {blockerCount > 0 ? `• Blockers ${blockerCount}` : ''}
                </span>
              )}
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {(['published', 'review', 'analysis'] as const).map((mode) => (
              <button
                key={mode}
                className={`rounded-full px-4 py-1.5 text-xs font-medium transition ${viewMode === mode ? 'bg-slate-900 text-white shadow-sm' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                onClick={() => setViewMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {Object.entries(counts).map(([label, count]) => (
              <div key={label} className={`metric-card ${countChipClass(label as FindingOut['status'])}`}>
                <div className="text-[11px] uppercase tracking-wide opacity-80">{label}</div>
                <div className="mt-1 text-xl font-semibold">{count}</div>
              </div>
            ))}
          </div>
          {publishedError && viewMode === 'published' && (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <div className="font-semibold">Publication blocked</div>
              <div className="mt-1">Published findings are unavailable until review blockers are resolved.</div>
              <button className="mt-2 rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white" onClick={() => setViewMode('review')}>
                View review findings
              </button>
            </div>
          )}
        </header>
        {uiNotice && <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-700">{uiNotice}</div>}
        {sectionsError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{sectionsError}</div>}
        {viewMode === 'review' && reviewError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{reviewError}</div>}
        {viewMode === 'analysis' && analysisError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{analysisError}</div>}

        <div className="surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-100/80 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Section</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Severity / type</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.length === 0 ? (
                <tr className="border-t border-slate-200/80 bg-white">
                  <td className="px-4 py-6 text-sm text-slate-500" colSpan={3}>
                    {viewMode === 'review'
                      ? 'No unresolved review artifacts. Switch to Published or Analysis for detailed records.'
                      : 'No records available for this view yet.'}
                  </td>
                </tr>
              ) : (
                activeRows.map((finding) => {
                  const sectionLabel = displaySectionTitle(finding, sectionsById)
                  return (
                    <tr
                      key={finding.id}
                      onClick={() => setSelectedByView((current) => ({ ...current, [viewMode]: finding.id }))}
                      className={`cursor-pointer border-t border-slate-200/80 transition-colors hover:bg-sky-50/50 ${selectedId === finding.id ? 'bg-sky-50/80' : 'bg-white'}`}
                    >
                      <td className="px-4 py-3 text-slate-800">{sectionLabel}</td>
                      <td className="px-4 py-3"><StatusBadge status={rowStatus(finding)} /></td>
                      <td className="px-4 py-3 text-slate-600">{rowSeverityOrKind(finding)}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="surface-card sticky top-24 h-fit p-5">
        {!selectedPublished && !selectedReview && !selectedAnalysis ? (
          <p className="text-sm text-slate-600">Select a finding on the left to inspect legal context and remediation details.</p>
        ) : (
          <div className="space-y-4">
            {selectedPublished && <PublishedDetail finding={selectedPublished} sectionText={sectionsById[selectedPublished.section_id]?.content ?? null} />}
            {selectedReview && <ReviewDetail item={selectedReview} />}
            {selectedAnalysis && <AnalysisDetail item={selectedAnalysis} />}
          </div>
        )}
      </aside>
    </section>
  )
}

function displaySectionTitle(finding: { section_id: string }, sectionsById: Record<string, SectionOut>): string {
  const section = sectionsById[finding.section_id]
  if (section) return section.section_title
  if (finding.section_id === 'review:core_duties') return 'Review block: Core duties'
  if (finding.section_id === 'review:specialist_families') return 'Review block: Specialist families'
  if (finding.section_id.startsWith('review:')) return `Review block: ${humanize(finding.section_id.replace('review:', ''))}`
  if (finding.section_id.startsWith('systemic:')) {
    const issueId = finding.section_id.split('systemic:')[1]
    return `Systemic: ${SYSTEMIC_LABELS[issueId] ?? humanize(issueId)}`
  }
  return finding.section_id
}

function rowStatus(row: FindingOut | ReviewItemOut | AnalysisItemOut): string {
  if ('status' in row && row.status) return row.status
  if ('status_candidate' in row && row.status_candidate) return row.status_candidate
  return 'not applicable'
}

function rowSeverityOrKind(row: FindingOut | ReviewItemOut | AnalysisItemOut): string {
  if ('severity' in row) return row.severity ?? 'n/a'
  if ('item_kind' in row) {
    const reviewLabel = row.issue_type ?? row.family ?? row.review_group ?? row.item_kind
    return humanize(reviewLabel)
  }
  if ('analysis_type' in row) return row.analysis_type
  return 'n/a'
}

function normalizeUiError(reason: unknown, fallback: string): string {
  const raw = reason instanceof Error ? reason.message : String(reason ?? fallback)
  if (raw.toLowerCase().includes('published findings blocked')) {
    return 'Published findings are blocked until review issues are resolved.'
  }
  return fallback
}

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-block">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</h3>
      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{value}</p>
    </div>
  )
}

function PublishedDetail({ finding, sectionText }: { finding: FindingOut; sectionText: string | null }) {
  return (
    <>
      <h2 className="text-lg font-semibold text-slate-900">Published finding</h2>
      <div className="flex flex-wrap gap-2">
        <StatusBadge status={finding.status} />
        {finding.finding_type && <Pill value={finding.finding_type} />}
        {finding.classification && <Pill value={finding.classification} />}
        {finding.confidence_level && <Pill value={`confidence ${finding.confidence_level}`} />}
      </div>
      <Detail label="Gap note" value={finding.gap_note ?? 'n/a'} />
      <Detail label="Remediation" value={finding.remediation_note ?? 'n/a'} />
      <Detail label="Legal anchors" value={finding.primary_legal_anchor?.join(', ') ?? 'n/a'} />
      <Detail label="Secondary anchors" value={finding.secondary_legal_anchors?.join(', ') ?? 'n/a'} />
      <Detail label="Section text" value={sectionText ?? 'Systemic finding (document-level synthesis)'} />
      <CitationList title="Citations" items={finding.citations} />
    </>
  )
}

function ReviewDetail({ item }: { item: ReviewItemOut }) {
  return (
    <>
      <h2 className="text-lg font-semibold text-slate-900">Review artifact</h2>
      <div className="flex flex-wrap gap-2">
        <Pill value={`source: ${item.item_kind}`} />
        {item.status && <StatusBadge status={item.status} />}
        {item.artifact_role && <Pill value={item.artifact_role} />}
        {item.publication_state && <Pill value={item.publication_state} />}
      </div>
      <Detail label="Classification" value={item.classification ?? 'n/a'} />
      <Detail label="Issue type" value={item.issue_type ?? 'n/a'} />
      <Detail label="Finding level" value={item.finding_level ?? 'n/a'} />
      <Detail label="Suppression reason" value={item.suppression_reason ?? 'n/a'} />
      <Detail label="Completeness map" value={item.completeness_map ?? 'n/a'} />
      <Detail label="Gap note" value={item.gap_note ?? 'n/a'} />
      <Detail label="Remediation" value={item.remediation_note ?? 'n/a'} />
    </>
  )
}

function AnalysisDetail({ item }: { item: AnalysisItemOut }) {
  return (
    <>
      <h2 className="text-lg font-semibold text-slate-900">Analysis artifact</h2>
      <div className="flex flex-wrap gap-2">
        {item.status_candidate && <StatusBadge status={item.status_candidate} />}
        {item.analysis_stage && <Pill value={item.analysis_stage} />}
        <Pill value={item.analysis_type} />
        {item.artifact_role && <Pill value={item.artifact_role} />}
        {item.publication_state_candidate && <Pill value={item.publication_state_candidate} />}
      </div>
      <Detail label="Issue type" value={item.issue_type ?? 'n/a'} />
      <Detail label="Classification candidate" value={item.classification_candidate ?? 'n/a'} />
      <Detail label="Suppression reason" value={item.suppression_reason ?? 'n/a'} />
      <Detail label="Gap note" value={item.gap_note ?? 'n/a'} />
      <Detail label="Remediation" value={item.remediation_note ?? 'n/a'} />
      <CitationList title="Analysis citations" items={item.citations} />
    </>
  )
}

function CitationList({ title, items }: { title: string; items: { chunk_id: string; article_number: string; article_title: string; excerpt: string }[] }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <ul className="mt-2 space-y-2 text-sm">
        {items.length === 0 ? (
          <li className="detail-block text-slate-500">No citations.</li>
        ) : (
          items.map((c, idx) => (
            <li key={`${c.chunk_id}-${idx}`} className="detail-block">
              <div className="font-medium text-slate-800">{c.article_number} — {c.article_title}</div>
              <p className="mt-1 text-slate-600">{sanitizeCitationText(c.excerpt)}</p>
            </li>
          ))
        )}
      </ul>
    </div>
  )
}

function Pill({ value }: { value: string }) {
  const token = value.toLowerCase()
  let tone = 'border-slate-200 bg-slate-100 text-slate-700'
  if (token.includes('support_only') || token.includes('internal_only')) tone = 'border-sky-200 bg-sky-50 text-sky-700'
  if (token.includes('publishable') || token.includes('systemic')) tone = 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (token.includes('candidate') || token.includes('probable')) tone = 'border-amber-200 bg-amber-50 text-amber-700'
  if (token.includes('gap') || token.includes('blocked')) tone = 'border-rose-200 bg-rose-50 text-rose-700'
  return <span className={`rounded-full border px-2.5 py-1 text-xs ${tone}`}>{value}</span>
}

function countChipClass(status: FindingOut['status']): string {
  if (status === 'gap') return 'border-rose-200 bg-rose-50 text-rose-700'
  if (status === 'partial' || status === 'needs review') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (status === 'compliant') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function normalizeStatus(status: string): FindingOut['status'] {
  const s = status.toLowerCase()
  if (s === 'candidate_gap' || s === 'gap' || s === 'blocked') return 'gap'
  if (s === 'candidate_partial' || s === 'partial') return 'partial'
  if (s === 'candidate_compliant' || s === 'compliant') return 'compliant'
  if (s === 'needs_review' || s === 'needs review') return 'needs review'
  return 'not applicable'
}

function sanitizeCitationText(text: string): string {
  return text
    .replace(/section:[a-f0-9-]{12,}:/gi, 'section: ')
    .replace(/obligation_map:[^,\]]+/gi, 'obligation map signal')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

function EmptyState({ message }: { message: string }) {
  return <div className="surface-card p-6 text-slate-600">{message}</div>
}
