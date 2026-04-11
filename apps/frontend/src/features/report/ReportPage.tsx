import { useEffect, useMemo, useState } from 'react'

import { useAppState } from '../../app/state'
import { createReport, getReport, getReview, reportDownloadUrl } from '../../lib/api'
import type { ReportOut, ReviewItemOut } from '../../lib/types'

export function ReportPage() {
  const { auditId } = useAppState()
  const [reviewRows, setReviewRows] = useState<ReviewItemOut[]>([])
  const [report, setReport] = useState<ReportOut | null>(null)
  const [status, setStatus] = useState<'idle' | 'generating' | 'ready'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!auditId) return
    getReview(auditId).then(setReviewRows).catch((e) => setError(e.message))
  }, [auditId])

  useEffect(() => {
    if (!auditId || status !== 'generating') return
    const timer = setInterval(async () => {
      try {
        const r = await getReport(auditId)
        setReport(r)
        if (r.status === 'ready') setStatus('ready')
      } catch {
        // ignore polling failures temporarily
      }
    }, 2500)
    return () => clearInterval(timer)
  }, [auditId, status])

  const counts = useMemo(() => {
    const base = { compliant: 0, partial: 0, gap: 0, 'needs review': 0, 'not applicable': 0 }
    const visibleRows = reviewRows
      .filter((row) => !row.section_id.startsWith('ledger:'))
      .filter((row) => !row.section_id.startsWith('review:'))
    for (const row of visibleRows) {
      const mapped = normalizeStatus(row.status)
      base[mapped] += 1
    }
    return base
  }, [reviewRows])

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
        <p className="section-subtitle">Generate an executive-ready PDF with current audit outcomes and evidence references.</p>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {Object.entries(counts).map(([label, count]) => (
            <article key={label} className={`metric-card ${metricTone(label)}`}>
              <div className="text-xs uppercase tracking-wide opacity-75">{label}</div>
              <div className="mt-2 text-2xl font-semibold">{count}</div>
            </article>
          ))}
        </div>
      </header>

      <article className="surface-card p-6">
        <h2 className="text-lg font-semibold text-slate-900">PDF generation</h2>
        <p className="mt-1 text-sm text-slate-500">Use the latest review data to create a shareable compliance report.</p>

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
  if (label === 'compliant') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (label === 'partial') return 'border-amber-200 bg-amber-50 text-amber-800'
  if (label === 'gap') return 'border-rose-200 bg-rose-50 text-rose-800'
  if (label === 'needs review') return 'border-violet-200 bg-violet-50 text-violet-800'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

function normalizeStatus(status?: string | null): 'compliant' | 'partial' | 'gap' | 'needs review' | 'not applicable' {
  const s = (status ?? '').toLowerCase()
  if (s === 'candidate_gap' || s === 'gap' || s === 'blocked') return 'gap'
  if (s === 'candidate_partial' || s === 'partial') return 'partial'
  if (s === 'candidate_compliant' || s === 'compliant') return 'compliant'
  if (s === 'needs_review' || s === 'needs review') return 'needs review'
  return 'not applicable'
}
