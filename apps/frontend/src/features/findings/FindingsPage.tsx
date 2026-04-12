import { useEffect, useMemo, useState } from 'react'

import { useAppState } from '../../app/state'
import { StatusBadge } from '../../components/StatusBadge'
import { getAudit, getFindings, getReview, getSections } from '../../lib/api'
import { buildFindingsSnapshot, formatLegalAnchors, mapUserSeverity } from '../../lib/presentation'
import type { FindingOut, ReviewItemOut, SectionOut } from '../../lib/types'

export function FindingsPage() {
  const { auditId, documentId } = useAppState()
  const [findings, setFindings] = useState<FindingOut[]>([])
  const [reviewItems, setReviewItems] = useState<ReviewItemOut[]>([])
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>({})
  const [selectedByView, setSelectedByView] = useState<Record<'published' | 'review', string | null>>({
    published: null,
    review: null,
  })
  const [viewMode, setViewMode] = useState<'published' | 'review'>('published')
  const [status, setStatus] = useState<string>('pending')
  const [publishedError, setPublishedError] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)
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
        const [publishedResult, reviewResult] = await Promise.allSettled([
          getFindings(currentAuditId),
          getReview(currentAuditId),
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
    const visibleRows = [...reviewItems]
      .filter((item) => !item.section_id.startsWith('ledger:'))
      .filter((item) => !item.section_id.startsWith('review:'))
      .filter((item) => Boolean(sectionsById[item.section_id]))
      .filter((item) => {
        if (item.item_kind !== 'review_block') return true
        return (item.final_disposition ?? '').toLowerCase() !== 'satisfied'
      })
    return dedupeReviewRows(visibleRows).sort((a, b) => {
      const aOrder = sectionsById[a.section_id]?.section_order ?? Number.MAX_SAFE_INTEGER
      const bOrder = sectionsById[b.section_id]?.section_order ?? Number.MAX_SAFE_INTEGER
      if (aOrder !== bOrder) return aOrder - bOrder
      return a.id.localeCompare(b.id)
    })
  }, [reviewItems, sectionsById])

  const publicationBlocked = !!publishedError?.toLowerCase().includes('blocked')
  const snapshot = useMemo(
    () => buildFindingsSnapshot({ publishedRows: orderedFindings, reviewRows: orderedReviewItems, publishedBlocked: publicationBlocked }),
    [orderedFindings, orderedReviewItems, publicationBlocked],
  )
  const activeRows = snapshot.rows
  const selectedId = selectedByView[viewMode]
  const selectedPublished = viewMode === 'published' ? orderedFindings.find((f) => f.id === selectedId) ?? null : null
  const selectedReview = viewMode === 'review' ? orderedReviewItems.find((r) => r.id === selectedId) ?? null : null
  const blockerCount = snapshot.blockers.length

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
            {(['published', 'review'] as const).map((mode) => (
              <button
                key={mode}
                className={`rounded-full px-4 py-1.5 text-xs font-medium transition ${viewMode === mode ? 'bg-slate-900 text-white shadow-sm' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
                onClick={() => setViewMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(snapshot.counts).map(([label, count]) => (
              <div key={label} className={`metric-card ${countChipClass(label)}`}>
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
        {(uiNotice || snapshot.message) && <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-700">{snapshot.message ?? uiNotice}</div>}
        {sectionsError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{sectionsError}</div>}
        {viewMode === 'review' && reviewError && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{reviewError}</div>}

        <div className="surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-100/80 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Section</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3">Severity</th>
              </tr>
            </thead>
            <tbody>
              {activeRows.length === 0 ? (
                <tr className="border-t border-slate-200/80 bg-white">
                  <td className="px-4 py-6 text-sm text-slate-500" colSpan={3}>
                    {viewMode === 'review'
                      ? 'No unresolved review artifacts. Switch to Published or Analysis for detailed records.'
                      : 'No published findings are currently available for this audit.'}
                  </td>
                </tr>
              ) : (
                activeRows.map((finding) => {
                  const sectionLabel = finding.title
                  return (
                    <tr
                      key={finding.id}
                      onClick={() => setSelectedByView((current) => ({ ...current, [viewMode]: finding.id }))}
                      className={`cursor-pointer border-t border-slate-200/80 transition-colors hover:bg-sky-50/50 ${selectedId === finding.id ? 'bg-sky-50/80' : 'bg-white'}`}
                    >
                      <td className="px-4 py-3 text-slate-800">{sectionLabel}</td>
                      <td className="px-4 py-3"><StatusBadge status={finding.status.toLowerCase()} /></td>
                      <td className="px-4 py-3 text-slate-600">{finding.scope}</td>
                      <td className="px-4 py-3 text-slate-600">{finding.severity ?? '-'}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="surface-card sticky top-24 h-fit p-5">
        {!selectedPublished && !selectedReview ? (
          <p className="text-sm text-slate-600">Select a finding on the left to inspect legal context and remediation details.</p>
        ) : (
          <div className="space-y-4">
            {selectedPublished && <PublishedDetail finding={selectedPublished} sectionText={sectionsById[selectedPublished.section_id]?.content ?? null} />}
            {selectedReview && <ReviewDetail item={selectedReview} />}
          </div>
        )}
      </aside>
    </section>
  )
}

function rowStatus(row: FindingOut | ReviewItemOut): string {
  if ('status' in row && row.status) return row.status
  return 'not applicable'
}

function normalizeUiError(reason: unknown, fallback: string): string {
  const raw = reason instanceof Error ? reason.message : String(reason ?? fallback)
  if (raw.toLowerCase().includes('published findings blocked')) {
    return 'Published findings are blocked until review issues are resolved.'
  }
  return fallback
}

function dedupeReviewRows(rows: ReviewItemOut[]): ReviewItemOut[] {
  const deduped = new Map<string, ReviewItemOut>()
  for (const row of rows) {
    const key = [
      row.section_id,
      (row.issue_type ?? '').toLowerCase(),
      (row.gap_note ?? '').toLowerCase(),
      (row.remediation_note ?? '').toLowerCase(),
    ].join('|')
    const existing = deduped.get(key)
    if (!existing || reviewRowPriority(row) > reviewRowPriority(existing)) {
      deduped.set(key, row)
    }
  }
  return [...deduped.values()]
}

function reviewRowPriority(row: ReviewItemOut): number {
  const status = (row.status ?? '').toLowerCase()
  const isCandidate = status.startsWith('candidate')
  if (row.item_kind === 'finding' && !isCandidate) return 5
  if (!isCandidate) return 4
  if (row.item_kind === 'finding') return 3
  if (row.item_kind === 'analysis') return 2
  return 1
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
        <StatusBadge status={mapDisplayStatus(finding.status)} />
        {mapUserSeverity(finding.severity) && <Pill value={`Severity ${mapUserSeverity(finding.severity)}`} />}
      </div>
      {finding.gap_note && <Detail label="Why this matters" value={sanitizeCitationText(finding.gap_note)} />}
      {finding.remediation_note && <Detail label="Recommended action" value={sanitizeCitationText(finding.remediation_note)} />}
      {formatLegalAnchors(finding.primary_legal_anchor) && <Detail label="Legal anchors" value={formatLegalAnchors(finding.primary_legal_anchor) ?? ''} />}
      <Detail label="Evidence summary" value={sanitizeCitationText(finding.citation_summary_text ?? 'No supporting excerpt available in the current view.')} />
      {sectionText && <Detail label="Section text" value={sectionText} />}
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
        {item.status && <StatusBadge status={mapDisplayStatus(item.status)} />}
      </div>
      {item.gap_note && <Detail label="Why this matters" value={sanitizeCitationText(item.gap_note)} />}
      {item.remediation_note && <Detail label="Recommended action" value={sanitizeCitationText(item.remediation_note)} />}
    </>
  )
}

function CitationList({ title, items }: { title: string; items: { chunk_id: string; article_number: string; article_title: string; excerpt: string }[] }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      <ul className="mt-2 space-y-2 text-sm">
        {items.length === 0 ? (
          <li className="detail-block text-slate-500">No supporting excerpt available in the current view.</li>
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

function countChipClass(status: string): string {
  if (status === 'Non-compliant') return 'border-rose-200 bg-rose-50 text-rose-700'
  if (status === 'Partially compliant') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (status === 'Compliant') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function mapDisplayStatus(status: string): string {
  const s = status.toLowerCase()
  if (s === 'candidate_gap' || s === 'gap' || s === 'blocked' || s.includes('non')) return 'non-compliant'
  if (s === 'candidate_partial' || s === 'partial') return 'partially compliant'
  if (s === 'candidate_compliant' || s === 'compliant' || s === 'satisfied') return 'compliant'
  return 'not applicable'
}

function sanitizeCitationText(text: string): string {
  return text
    .replace(/section:[a-f0-9-]{12,}:/gi, 'section: ')
    .replace(/obligation_map:[^,\]]+/gi, '')
    .replace(/evi:[a-z]+:[a-z0-9:_-]+/gi, '')
    .replace(/support_only|internal_only|post_reviewer_snapshot|confirmed_document_gap|probable_document_gap/gi, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

function EmptyState({ message }: { message: string }) {
  return <div className="surface-card p-6 text-slate-600">{message}</div>
}
