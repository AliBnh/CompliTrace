import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAppState } from '../../app/state'
import { createAudit, getSections } from '../../lib/api'
import type { SectionOut } from '../../lib/types'

export function SectionsPage() {
  const { documentId, setAuditId } = useAppState()
  const [sections, setSections] = useState<SectionOut[]>([])
  const [loading, setLoading] = useState(true)
  const [auditLoading, setAuditLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    if (!documentId) {
      setLoading(false)
      return
    }
    setLoading(true)
    getSections(documentId)
      .then(setSections)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [documentId])

  const extractionStats = useMemo(() => {
    const contentChars = sections.reduce((sum, section) => sum + section.content.length, 0)
    return {
      sections: sections.length,
      avgLength: sections.length ? Math.round(contentChars / sections.length) : 0,
      withPageRef: sections.filter((item) => item.page_start != null || item.page_end != null).length,
    }
  }, [sections])

  async function startAudit() {
    if (!documentId) return
    setAuditLoading(true)
    setError(null)
    try {
      const audit = await createAudit(documentId)
      setAuditId(audit.id)
      navigate('/findings')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start audit')
    } finally {
      setAuditLoading(false)
    }
  }

  if (!documentId) return <EmptyState message="No document uploaded yet. Start on the Upload page." />

  return (
    <section className="space-y-5">
      <header className="surface-card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="section-title">Sections review</h1>
            <p className="section-subtitle">Validate extracted policy structure before launching the GDPR audit.</p>
          </div>
          <div className="flex items-center gap-3">
            {auditLoading && <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">Preparing audit…</span>}
            <button onClick={startAudit} disabled={auditLoading || loading || sections.length === 0} className="btn-primary">
              {auditLoading ? 'Starting…' : 'Start audit'}
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <MetricCard label="Sections" value={String(extractionStats.sections)} />
          <MetricCard label="Avg chars / section" value={String(extractionStats.avgLength)} />
          <MetricCard label="With page reference" value={String(extractionStats.withPageRef)} />
        </div>
      </header>

      {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</div>}

      {loading ? (
        <div className="surface-card p-6 text-sm text-slate-500">Loading extracted sections…</div>
      ) : (
        <div className="space-y-3">
          {sections.map((section) => (
            <article key={section.id} className="surface-card animate-rise p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-900">
                  {section.section_order}. {section.section_title || 'Untitled section'}
                </h2>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600">{formatPageRange(section.page_start, section.page_end)}</span>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-600">{section.content}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <article className="metric-card">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p>
    </article>
  )
}

function formatPageRange(start: number | null, end: number | null) {
  if (start == null && end == null) return 'Page n/a'
  if (start != null && end != null && start !== end) return `Pages ${start}-${end}`
  return `Page ${start ?? end}`
}

function EmptyState({ message }: { message: string }) {
  return <div className="surface-card p-6 text-slate-600">{message}</div>
}
