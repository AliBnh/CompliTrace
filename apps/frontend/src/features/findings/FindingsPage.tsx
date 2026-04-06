import { useEffect, useMemo, useState } from 'react'

import { useAppState } from '../../app/state'
import { StatusBadge } from '../../components/StatusBadge'
import { getAudit, getFindings, getSections } from '../../lib/api'
import type { FindingOut, SectionOut } from '../../lib/types'

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
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>({})
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>('pending')
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<number>(12)

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
        const rows = await getFindings(currentAuditId)
        if (cancelled) return
        setFindings(rows)
        setSelectedId((previous) => previous ?? rows[0]?.id ?? null)
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

  const selected = orderedFindings.find((f) => f.id === selectedId) ?? null
  const counts = useMemo(() => {
    const base = { compliant: 0, partial: 0, gap: 0, 'needs review': 0, 'not applicable': 0 }
    for (const finding of orderedFindings) base[finding.status] += 1
    return base
  }, [orderedFindings])

  if (!auditId) return <EmptyState message="No audit in progress. Trigger an audit from Sections page." />

  return (
    <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div>
        <header className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Findings</h1>
            <p className="text-sm text-slate-600">Audit status: <span className="font-medium">{status}</span></p>
          </div>
          {(status === 'running' || status === 'pending') && (
            <div className="relative grid h-20 w-20 place-items-center">
              <svg className="h-20 w-20 -rotate-90" viewBox="0 0 100 100" aria-label="Audit progress">
                <circle cx="50" cy="50" r="42" strokeWidth="8" className="fill-none stroke-slate-200" />
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  strokeWidth="8"
                  strokeDasharray={264}
                  strokeDashoffset={264 - (264 * progress) / 100}
                  className="fill-none stroke-cyan-500 transition-all duration-700"
                />
              </svg>
              <span className="absolute text-sm font-semibold text-cyan-700">{Math.round(progress)}%</span>
            </div>
          )}
          <div className="flex gap-2 text-xs">
            {Object.entries(counts).map(([label, count]) => (
              <span key={label} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-slate-600">
                {label}: {count}
              </span>
            ))}
          </div>
        </header>

        {error && <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}

        <div className="surface-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-100 text-left text-slate-600">
              <tr>
                <th className="px-4 py-3">Section</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Severity</th>
              </tr>
            </thead>
            <tbody>
              {orderedFindings.map((finding) => {
                const sectionLabel = displaySectionTitle(finding, sectionsById)
                return (
                  <tr
                    key={finding.id}
                    onClick={() => setSelectedId(finding.id)}
                    className={`cursor-pointer border-t border-slate-200 hover:bg-slate-50 ${selectedId === finding.id ? 'bg-cyan-50' : ''}`}
                  >
                    <td className="px-4 py-3 text-slate-800">{sectionLabel}</td>
                    <td className="px-4 py-3"><StatusBadge status={finding.status} /></td>
                    <td className="px-4 py-3 text-slate-600">{finding.severity ?? 'n/a'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="surface-card p-5">
        {!selected ? (
          <p className="text-slate-600">Select a finding to inspect full details.</p>
        ) : (
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">{displaySectionTitle(selected, sectionsById)}</h2>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={selected.status} />
              {selected.finding_type && <TypeBadge label={selected.finding_type === 'systemic' ? 'systemic' : 'section-level'} />}
              {selected.assessment_type && <TypeBadge label={selected.assessment_type} />}
              {selected.confidence_level && <TypeBadge label={`confidence: ${selected.confidence_level}`} />}
            </div>
            <Detail label="Section text" value={sectionsById[selected.section_id]?.content ?? 'Systemic synthesized finding (no direct section text).'} />
            <Detail label="Gap note" value={selected.gap_note ?? 'n/a'} />
            <Detail label="Remediation" value={selected.remediation_note ?? 'n/a'} />
            <Detail label="Legal requirement" value={selected.legal_requirement ?? 'n/a'} />
            <Detail label="Gap reasoning" value={selected.gap_reasoning ?? 'n/a'} />
            <Detail label="Severity rationale" value={selected.severity_rationale ?? 'n/a'} />
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

function displaySectionTitle(finding: FindingOut, sectionsById: Record<string, SectionOut>): string {
  const section = sectionsById[finding.section_id]
  if (section) return section.section_title
  if (finding.section_id.startsWith('systemic:')) {
    const issueId = finding.section_id.split('systemic:')[1]
    return `Systemic: ${SYSTEMIC_LABELS[issueId] ?? humanize(issueId)}`
  }
  return finding.section_id
}

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function TypeBadge({ label }: { label: string }) {
  return <span className="rounded-full border border-slate-300 bg-slate-100 px-2 py-1 text-xs text-slate-700">{label}</span>
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
  return <div className="surface-card p-6 text-slate-600">{message}</div>
}
