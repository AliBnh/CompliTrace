import { useEffect, useMemo, useState } from 'react'

import { useAppState } from '../../app/state'
import { StatusBadge } from '../../components/StatusBadge'
import { getAnalysis, getAudit, getFindings, getReview, getSections } from '../../lib/api'
import { aggregateCounts, buildFindingsPresentation, buildReviewSummary, type NormalizedFinding } from '../../lib/presentation'
import type { AnalysisItemOut, FindingOut, ReviewItemOut, SectionOut } from '../../lib/types'

export function FindingsPage() {
  const { auditId, documentId } = useAppState()
  const [findings, setFindings] = useState<FindingOut[]>([])
  const [reviewItems, setReviewItems] = useState<ReviewItemOut[]>([])
  const [analysisItems, setAnalysisItems] = useState<AnalysisItemOut[]>([])
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>({})
  const [selectedByView, setSelectedByView] = useState<Record<'published' | 'review' | 'analysis', string | null>>({
    published: null,
    review: null,
    analysis: null,
  })
  const [viewMode, setViewMode] = useState<'published' | 'review' | 'analysis'>('published')
  const [status, setStatus] = useState<string>('pending')
  const [publishedError, setPublishedError] = useState<string | null>(null)

  useEffect(() => {
    if (!documentId) return
    getSections(documentId)
      .then((sections) => setSectionsById(Object.fromEntries(sections.map((s) => [s.id, s]))))
      .catch(() => setSectionsById({}))
  }, [documentId])

  useEffect(() => {
    if (!auditId) return
    const id = auditId
    let cancelled = false
    async function tick() {
      const audit = await getAudit(id)
      if (cancelled) return
      setStatus(audit.status)
      const [p, r, a] = await Promise.allSettled([getFindings(id), getReview(id), getAnalysis(id)])
      if (cancelled) return
      if (p.status === 'fulfilled') {
        setFindings(p.value)
        setPublishedError(null)
      } else {
        setFindings([])
        setPublishedError('Final published findings are not yet available because some findings still require review.')
      }
      setReviewItems(r.status === 'fulfilled' ? r.value : [])
      setAnalysisItems(a.status === 'fulfilled' ? a.value : [])
    }
    tick()
    const timer = setInterval(tick, 3500)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [auditId])

  const presentation = useMemo(
    () => buildFindingsPresentation({
      publishedRows: findings,
      reviewRows: reviewItems,
      analysisRows: analysisItems,
      sectionsById,
      publishedBlocked: Boolean(publishedError) || reviewItems.some((x) => x.item_kind === 'review_block' && (x.final_disposition ?? '').toLowerCase() !== 'satisfied'),
    }),
    [findings, reviewItems, analysisItems, sectionsById, publishedError],
  )

  const activeRows = viewMode === 'published'
    ? presentation.publishedVisibleFindings
    : viewMode === 'review'
      ? presentation.reviewVisibleFindings
      : presentation.analysisVisibleFindings
  const counts = aggregateCounts(activeRows)
  const reviewSummary = buildReviewSummary(presentation.reviewVisibleFindings)

  useEffect(() => {
    setSelectedByView((current) => {
      const existing = current[viewMode]
      if (!activeRows.length) return { ...current, [viewMode]: null }
      if (existing && activeRows.some((row) => row.stable_ui_id === existing)) return current
      return { ...current, [viewMode]: activeRows[0].stable_ui_id }
    })
  }, [activeRows, viewMode])

  if (!auditId) return <EmptyState message="No audit in progress. Trigger an audit from Sections page." />

  const selected = activeRows.find((x) => x.stable_ui_id === selectedByView[viewMode]) ?? null

  return (
    <section className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="space-y-4">
        <header className="surface-card p-5">
          <h1 className="section-title">Findings workspace</h1>
          <p className="section-subtitle">Audit status: <span className="font-medium text-slate-700 capitalize">{status}</span></p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(['published', 'review', 'analysis'] as const).map((mode) => (
              <button key={mode} className={`rounded-full px-4 py-1.5 text-xs font-medium ${viewMode === mode ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'}`} onClick={() => setViewMode(mode)}>
                {mode}
              </button>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-600">
            {viewMode === 'published' && (presentation.publishedBlocked
              ? 'Final published findings are not yet available because some findings still require review.'
              : `Using dataset: ${presentation.datasetLabels.publishedVisibleFindings}.`)}
            {viewMode === 'review' && `Using dataset: ${presentation.datasetLabels.reviewVisibleFindings}.`}
            {viewMode === 'analysis' && `Using dataset: ${presentation.datasetLabels.analysisVisibleFindings}.`}
          </p>
          {presentation.publishedBlocked && viewMode === 'published' && (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              Final published findings are not yet available because some findings still require review.
            </div>
          )}
          {viewMode === 'review' && reviewSummary && (
            <div className="mt-3 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900">
              {reviewSummary}
            </div>
          )}
          <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {[
              ['Compliant', counts.compliant],
              ['Partially compliant', counts.partially_compliant],
              ['Non-compliant', counts.non_compliant],
              ['Not applicable', counts.not_applicable],
              ['Total', counts.total],
            ].map(([label, value]) => (
              <article key={String(label)} className={`metric-card ${countChipClass(String(label))}`}><div className="text-xs">{label}</div><div className="text-xl font-semibold">{value}</div></article>
            ))}
          </div>
        </header>

        <div className="surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-100/80 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr><th className="px-4 py-3">Title</th><th className="px-4 py-3">Issue</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Severity</th></tr>
            </thead>
            <tbody>
              {activeRows.length === 0 ? <tr className="border-t"><td className="px-4 py-6 text-slate-500" colSpan={4}>No findings in this dataset.</td></tr> : activeRows.map((finding) => (
                <tr key={finding.stable_ui_id} onClick={() => setSelectedByView((c) => ({ ...c, [viewMode]: finding.stable_ui_id }))} className={`cursor-pointer border-t ${selected?.stable_ui_id === finding.stable_ui_id ? 'bg-sky-50/80' : 'bg-white'}`}>
                  <td className="px-4 py-3">{finding.title}</td>
                  <td className="px-4 py-3">{finding.issue_label}</td>
                  <td className="px-4 py-3"><StatusBadge status={finding.status.toLowerCase()} /></td>
                  <td className="px-4 py-3">{finding.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="surface-card sticky top-24 h-fit p-5">
        {!selected ? <p className="text-sm text-slate-600">Select a finding to view details.</p> : <FindingDetail finding={selected} />}
      </aside>
    </section>
  )
}

function FindingDetail({ finding }: { finding: NormalizedFinding }) {
  return <div className="space-y-3">
    <h2 className="text-lg font-semibold text-slate-900">{finding.title}</h2>
    <div className="flex gap-2"><StatusBadge status={finding.status.toLowerCase()} /><span className="rounded-full border px-2.5 py-1 text-xs">Severity {finding.severity}</span></div>
    <Detail label="Dataset" value={finding.source_mode === 'published' ? 'Final published findings' : finding.source_mode === 'review' ? 'Review findings' : 'Analysis findings'} />
    <Detail label="Scope" value={finding.section_title ?? finding.scope_label} />
    <Detail label="Issue" value={finding.issue_label} />
    <Detail label="Why this matters" value={finding.why_this_matters} />
    <Detail label="Recommended action" value={finding.recommended_action} />
    {!!finding.legal_anchors.length && <Detail label="Legal anchors" value={finding.legal_anchors.join(', ')} />}
    <Detail label="Evidence" value={finding.evidence_text} />
    {!!finding.details.length && <Detail label="Additional merged details" value={finding.details.join('\n')} />}
  </div>
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="detail-block"><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</h3><p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{value}</p></div>
}

function countChipClass(status: string): string {
  if (status === 'Non-compliant') return 'border-rose-200 bg-rose-50 text-rose-700'
  if (status === 'Partially compliant') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (status === 'Compliant') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function EmptyState({ message }: { message: string }) {
  return <div className="surface-card p-6 text-slate-600">{message}</div>
}
