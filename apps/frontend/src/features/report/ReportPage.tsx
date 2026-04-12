import { useEffect, useMemo, useState } from 'react'

import { useAppState } from '../../app/state'
import { createReport, getAnalysis, getFindings, getReport, getReview, reportDownloadUrl } from '../../lib/api'
import { aggregateCounts, buildFindingsPresentation } from '../../lib/presentation'
import type { AnalysisItemOut, FindingOut, ReportOut, ReviewItemOut } from '../../lib/types'

export function ReportPage() {
  const { auditId } = useAppState()
  const [reviewRows, setReviewRows] = useState<ReviewItemOut[]>([])
  const [analysisRows, setAnalysisRows] = useState<AnalysisItemOut[]>([])
  const [publishedRows, setPublishedRows] = useState<FindingOut[]>([])
  const [report, setReport] = useState<ReportOut | null>(null)
  const [status, setStatus] = useState<'idle' | 'generating' | 'ready'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!auditId) return
    Promise.allSettled([getReview(auditId), getFindings(auditId), getAnalysis(auditId)]).then(([reviewResult, publishedResult, analysisResult]) => {
      if (reviewResult.status === 'fulfilled') setReviewRows(reviewResult.value)
      else setError('Unable to load review findings')
      if (publishedResult.status === 'fulfilled') setPublishedRows(publishedResult.value)
      else setPublishedRows([])
      setAnalysisRows(analysisResult.status === 'fulfilled' ? analysisResult.value : [])
    })
  }, [auditId])

  useEffect(() => {
    if (!auditId || status !== 'generating') return
    const timer = setInterval(async () => {
      try {
        const r = await getReport(auditId)
        setReport(r)
        if (r.status === 'ready') setStatus('ready')
      } catch {
        // noop
      }
    }, 2500)
    return () => clearInterval(timer)
  }, [auditId, status])

  const presentation = useMemo(() => buildFindingsPresentation({
    publishedRows,
    reviewRows,
    analysisRows,
    sectionsById: {},
    publishedBlocked: reviewRows.some((row) => row.item_kind === 'review_block' && (row.final_disposition ?? '').toLowerCase() !== 'satisfied'),
  }), [publishedRows, reviewRows, analysisRows])
  const counts = aggregateCounts(presentation.reportVisibleFindings)

  async function generate() {
    if (!auditId) return
    setError(null)
    setStatus('generating')
    try {
      await createReport(auditId)
    } catch (e) {
      setStatus('idle')
      setError(e instanceof Error ? e.message : 'Failed to generate report')
    }
  }

  if (!auditId) return <div className="surface-card p-6 text-slate-600">Run an audit first.</div>

  return (
    <section className="space-y-5">
      <header className="surface-card p-6">
        <h1 className="section-title">Report center</h1>
        <p className="section-subtitle">PDF source dataset: <span className="font-medium">{presentation.reportMode === 'published' ? 'Final published findings' : 'Review findings (final publication blocked)'}</span>.</p>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ['Compliant', counts.compliant],
            ['Partially compliant', counts.partially_compliant],
            ['Non-compliant', counts.non_compliant],
            ['Not applicable', counts.not_applicable],
            ['Total', counts.total],
          ].map(([label, count]) => (
            <article key={String(label)} className={`metric-card ${metricTone(String(label))}`}>
              <div className="text-xs uppercase tracking-wide opacity-75">{label}</div>
              <div className="mt-2 text-2xl font-semibold">{count}</div>
            </article>
          ))}
        </div>
      </header>

      <article className="surface-card p-6">
        <h2 className="text-lg font-semibold text-slate-900">PDF generation</h2>
        <p className="mt-1 text-sm text-slate-500">This export uses the same dataset and counts shown above.</p>

        {error && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</div>}

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button onClick={generate} disabled={status === 'generating'} className="btn-primary min-w-40">
            {status === 'generating' ? 'Generating…' : 'Generate PDF'}
          </button>
          {status === 'ready' && (
            <a href={reportDownloadUrl(auditId)} target="_blank" rel="noreferrer" className="btn-secondary">
              Download PDF
            </a>
          )}
          {report?.created_at && <span className="text-xs text-slate-500">Last generated: {new Date(report.created_at).toLocaleString()}</span>}
        </div>
      </article>
    </section>
  )
}

function metricTone(label: string): string {
  if (label === 'Compliant') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (label === 'Partially compliant') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (label === 'Non-compliant') return 'border-rose-200 bg-rose-50 text-rose-800'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}
