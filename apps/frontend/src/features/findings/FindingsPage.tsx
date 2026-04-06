import { useEffect, useMemo, useState } from 'react'

import { getAudit, getFindings, getSections } from '../../lib/api'
import type { FindingOut, SectionOut } from '../../lib/types'
import { useAppState } from '../../app/state'
import { StatusBadge } from '../../components/StatusBadge'

export function FindingsPage() {
  const { auditId, documentId } = useAppState()
  const [findings, setFindings] = useState<FindingOut[]>([])
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>({})
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('pending')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!documentId) return
    getSections(documentId)
      .then((sections) => {
        const mapping = Object.fromEntries(sections.map((s) => [s.id, s]))
        setSectionsById(mapping)
      })
      .catch((e) => setError(e.message))
  }, [documentId])

  useEffect(() => {
    if (!auditId) return
    let cancelled = false

    async function tick() {
      try {
        const audit = await getAudit(auditId)
        if (cancelled) return
        setStatus(audit.status)
        const rows = await getFindings(auditId)
        if (cancelled) return
        setFindings(rows)
        if (!selectedId && rows.length) setSelectedId(rows[0].id)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load findings')
      }
    }

    tick()
    const timer = setInterval(tick, 3000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [auditId, selectedId])

  const selected = findings.find((f) => f.id === selectedId) ?? null
  const counts = useMemo(() => {
    const base = { compliant: 0, partial: 0, gap: 0, 'needs review': 0, 'not applicable': 0 }
    for (const finding of findings) base[finding.status] += 1
    return base
  }, [findings])

  if (!auditId) return <EmptyState message="No audit in progress. Trigger an audit from Sections page." />

  return (
    <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div>
        <header className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Findings</h1>
            <p className="text-sm text-slate-600">Audit status: <span className="font-medium">{status}</span></p>
          </div>
          <div className="flex gap-2 text-xs">
            {Object.entries(counts).map(([label, count]) => (
              <span key={label} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-slate-600">
                {label}: {count}
              </span>
            ))}
          </div>
        </header>

        {error && <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-soft">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-600">
              <tr>
                <th className="px-4 py-3">Section</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Severity</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => {
                const section = sectionsById[finding.section_id]
                return (
                  <tr
                    key={finding.id}
                    onClick={() => setSelectedId(finding.id)}
                    className={`cursor-pointer border-t border-slate-200 hover:bg-slate-50 ${selectedId === finding.id ? 'bg-cyan-50' : ''}`}
                  >
                    <td className="px-4 py-3 text-slate-800">{section?.section_title ?? finding.section_id}</td>
                    <td className="px-4 py-3"><StatusBadge status={finding.status} /></td>
                    <td className="px-4 py-3 text-slate-600">{finding.severity ?? 'n/a'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="rounded-xl border border-slate-200 bg-white p-5 shadow-soft">
        {!selected ? (
          <p className="text-slate-600">Select a finding to inspect full details.</p>
        ) : (
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">{sectionsById[selected.section_id]?.section_title ?? 'Finding details'}</h2>
            <div><StatusBadge status={selected.status} /></div>
            <Detail label="Section text" value={sectionsById[selected.section_id]?.content ?? 'Unavailable'} />
            <Detail label="Gap note" value={selected.gap_note ?? 'n/a'} />
            <Detail label="Remediation" value={selected.remediation_note ?? 'n/a'} />
            <div>
              <h3 className="text-sm font-semibold text-slate-700">GDPR evidence</h3>
              <ul className="mt-2 space-y-2 text-sm text-slate-600">
                {selected.citations.length === 0 ? <li>No citations.</li> : selected.citations.map((c, idx) => (
                  <li key={`${c.chunk_id}-${idx}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <div className="font-medium">Article {c.article_number}: {c.article_title}</div>
                    <div className="text-xs text-slate-400">Paragraph: {c.paragraph_ref ?? 'n/a'}</div>
                    <p className="mt-2 text-slate-600">{c.excerpt}</p>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </aside>
    </section>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-700">{label}</h3>
      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">{value}</p>
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-6 text-slate-600 shadow-soft">{message}</div>
}
