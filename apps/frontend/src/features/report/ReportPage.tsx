import { useEffect, useMemo, useState } from 'react'

import { createReport, getFindings, getReport, reportDownloadUrl } from '../../lib/api'
import type { FindingOut, ReportOut } from '../../lib/types'
import { useAppState } from '../../app/state'

export function ReportPage() {
  const { auditId } = useAppState()
  const [findings, setFindings] = useState<FindingOut[]>([])
  const [report, setReport] = useState<ReportOut | null>(null)
  const [status, setStatus] = useState<'idle' | 'generating' | 'ready'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!auditId) return
    getFindings(auditId).then(setFindings).catch((e) => setError(e.message))
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
    for (const finding of findings) base[finding.status] += 1
    return base
  }, [findings])
  const cardStyles: Record<string, string> = {
    compliant: 'from-emerald-50 to-emerald-100 border-emerald-200 text-emerald-900',
    partial: 'from-amber-50 to-amber-100 border-amber-200 text-amber-900',
    gap: 'from-rose-50 to-rose-100 border-rose-200 text-rose-900',
    'needs review': 'from-violet-50 to-violet-100 border-violet-200 text-violet-900',
    'not applicable': 'from-slate-50 to-slate-100 border-slate-200 text-slate-800',
  }

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
    <section>
      <h1 className="section-title">Report</h1>
      <p className="section-subtitle">Executive summary and downloadable PDF artifact.</p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {Object.entries(counts).map(([label, count]) => (
          <article key={label} className={`rounded-2xl border bg-gradient-to-br p-4 shadow-sm transition duration-300 hover:-translate-y-0.5 hover:shadow-md ${cardStyles[label]}`}>
            <div className="text-xs uppercase tracking-wide opacity-75">{label}</div>
            <div className="mt-2 text-2xl font-semibold">{count}</div>
          </article>
        ))}
      </div>

      {error && <div className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button onClick={generate} disabled={status === 'generating'} className="btn-primary">
          {status === 'generating' ? 'Generating...' : 'Generate PDF'}
        </button>
        {status === 'ready' && (
          <a
            href={reportDownloadUrl(auditId)}
            target="_blank"
            rel="noreferrer"
            className="rounded-xl border border-emerald-300 bg-emerald-100 px-5 py-3 font-semibold text-emerald-700"
          >
            Download PDF
          </a>
        )}
        {report?.created_at && <span className="text-sm text-slate-400">Last generated: {new Date(report.created_at).toLocaleString()}</span>}
      </div>
    </section>
  )
}
