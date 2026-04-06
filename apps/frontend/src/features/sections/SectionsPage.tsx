import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { createAudit, getSections } from '../../lib/api'
import type { SectionOut } from '../../lib/types'
import { useAppState } from '../../app/state'

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

  if (!documentId) return <EmptyState message="No document uploaded yet. Start on Upload page." />

  return (
    <section>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Sections Review</h1>
          <p className="text-slate-600">Confirm section extraction before triggering the audit.</p>
        </div>
        <button
          onClick={startAudit}
          disabled={auditLoading || loading || sections.length === 0}
          className="rounded-xl bg-cyan-500 px-5 py-3 font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-40"
        >
          {auditLoading ? 'Starting...' : 'Start Audit'}
        </button>
      </div>

      {error && <div className="mb-4 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
      {loading ? (
        <div className="text-slate-600">Loading sections...</div>
      ) : (
        <div className="space-y-4">
          {sections.map((section) => (
            <article key={section.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-soft">
              <div className="flex items-center justify-between gap-4">
                <h2 className="font-semibold">{section.section_order}. {section.section_title || 'Untitled section'}</h2>
                <span className="text-xs text-slate-400">{formatPageRange(section.page_start, section.page_end)}</span>
              </div>
              <p className="mt-3 line-clamp-3 text-sm text-slate-600">{section.content}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function formatPageRange(start: number | null, end: number | null) {
  if (start == null && end == null) return 'Page n/a'
  if (start != null && end != null && start !== end) return `Pages ${start}-${end}`
  return `Page ${start ?? end}`
}

function EmptyState({ message }: { message: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-6 text-slate-600 shadow-soft">{message}</div>
}
