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
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'published' | 'review' | 'analysis'>('published')
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
        const [publishedRows, reviewRows, analysisRows] = await Promise.all([
          getFindings(currentAuditId),
          getReview(currentAuditId),
          getAnalysis(currentAuditId),
        ])
        if (cancelled) return
        setFindings(publishedRows)
        setReviewItems(reviewRows)
        setAnalysisItems(analysisRows)
        setSelectedId((previous) => previous ?? publishedRows[0]?.id ?? reviewRows[0]?.id ?? analysisRows[0]?.id ?? null)
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

  const orderedReviewItems = useMemo(() => {
    return [...reviewItems].sort((a, b) => a.id.localeCompare(b.id))
  }, [reviewItems])

  const orderedAnalysisItems = useMemo(() => {
    return [...analysisItems].sort((a, b) => a.id.localeCompare(b.id))
  }, [analysisItems])

  const activeRows = viewMode === 'published' ? orderedFindings : viewMode === 'review' ? orderedReviewItems : orderedAnalysisItems
  const selectedPublished = viewMode === 'published' ? orderedFindings.find((f) => f.id === selectedId) ?? null : null
  const selectedReview = viewMode === 'review' ? orderedReviewItems.find((r) => r.id === selectedId) ?? null : null
  const selectedAnalysis = viewMode === 'analysis' ? orderedAnalysisItems.find((r) => r.id === selectedId) ?? null : null
  const counts = useMemo(() => {
    const base = { compliant: 0, partial: 0, gap: 0, 'needs review': 0, 'not applicable': 0 }
    for (const finding of orderedFindings) base[finding.status] += 1
    return base
  }, [orderedFindings])

  useEffect(() => {
    setSelectedId(activeRows[0]?.id ?? null)
  }, [viewMode, activeRows])

  if (!auditId) return <EmptyState message="No audit in progress. Trigger an audit from Sections page." />

  return (
    <section className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div>
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
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
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(counts).map(([label, count]) => (
              <span key={label} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-slate-600">
                {label}: {count}
              </span>
            ))}
          </div>
          <div className="flex gap-2 text-xs">
            <button className={`rounded-full px-3 py-1 ${viewMode === 'published' ? 'bg-cyan-600 text-white' : 'bg-slate-200 text-slate-700'}`} onClick={() => setViewMode('published')}>Published</button>
            <button className={`rounded-full px-3 py-1 ${viewMode === 'review' ? 'bg-cyan-600 text-white' : 'bg-slate-200 text-slate-700'}`} onClick={() => setViewMode('review')}>Review</button>
            <button className={`rounded-full px-3 py-1 ${viewMode === 'analysis' ? 'bg-cyan-600 text-white' : 'bg-slate-200 text-slate-700'}`} onClick={() => setViewMode('analysis')}>Analysis</button>
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
              {activeRows.map((finding) => {
                const sectionLabel = displaySectionTitle(finding, sectionsById)
                return (
                  <tr
                    key={finding.id}
                    onClick={() => setSelectedId(finding.id)}
                    className={`cursor-pointer border-t border-slate-200 hover:bg-slate-50 ${selectedId === finding.id ? 'bg-cyan-50' : ''}`}
                  >
                    <td className="px-4 py-3 text-slate-800">{sectionLabel}</td>
                    <td className="px-4 py-3"><StatusBadge status={rowStatus(finding)} /></td>
                    <td className="px-4 py-3 text-slate-600">{rowSeverityOrKind(finding)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <aside className="surface-card p-5">
        {!selectedPublished && !selectedReview && !selectedAnalysis ? (
          <p className="text-slate-600">Select a finding to inspect full details.</p>
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
  if (finding.section_id.startsWith('systemic:')) {
    const issueId = finding.section_id.split('systemic:')[1]
    return `Systemic: ${SYSTEMIC_LABELS[issueId] ?? humanize(issueId)}`
  }
  return finding.section_id
}

function rowStatus(row: FindingOut | ReviewItemOut | AnalysisItemOut): FindingOut['status'] {
  if ('status' in row && row.status) return row.status as FindingOut['status']
  if ('status_candidate' in row && row.status_candidate) return row.status_candidate as FindingOut['status']
  return 'not applicable'
}

function rowSeverityOrKind(row: FindingOut | ReviewItemOut | AnalysisItemOut): string {
  if ('severity' in row) return row.severity ?? 'n/a'
  if ('item_kind' in row) return row.item_kind
  if ('analysis_type' in row) return row.analysis_type
  return 'n/a'
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
    <div>
      <h3 className="text-sm font-semibold text-slate-700">{label}</h3>
      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">{value}</p>
    </div>
  )
}

function PublishedDetail({ finding, sectionText }: { finding: FindingOut; sectionText: string | null }) {
  return (
    <>
      <h2 className="text-lg font-semibold">Published finding details</h2>
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
      <div>
        <h3 className="text-sm font-semibold text-slate-700">Citations</h3>
        <ul className="mt-2 space-y-2 text-sm">
          {finding.citations.length === 0 ? (
            <li className="text-slate-500">No citations.</li>
          ) : (
            finding.citations.map((c, idx) => (
              <li key={`${c.chunk_id}-${idx}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="font-medium text-slate-800">{c.article_number} — {c.article_title}</div>
                <p className="mt-1 text-slate-600">{c.excerpt}</p>
              </li>
            ))
          )}
        </ul>
      </div>
    </>
  )
}

function ReviewDetail({ item }: { item: ReviewItemOut }) {
  return (
    <>
      <h2 className="text-lg font-semibold">Review item details</h2>
      <div className="flex flex-wrap gap-2">
        <Pill value={`source: ${item.item_kind}`} />
        {item.status && <StatusBadge status={item.status as FindingOut['status']} />}
        {item.artifact_role && <Pill value={item.artifact_role} />}
        {item.publication_state && <Pill value={item.publication_state} />}
      </div>
      <Detail label="Classification" value={item.classification ?? 'n/a'} />
      <Detail label="Finding level" value={item.finding_level ?? 'n/a'} />
      <Detail label="Gap note" value={item.gap_note ?? 'n/a'} />
      <Detail label="Remediation" value={item.remediation_note ?? 'n/a'} />
    </>
  )
}

function AnalysisDetail({ item }: { item: AnalysisItemOut }) {
  return (
    <>
      <h2 className="text-lg font-semibold">Analysis artifact details</h2>
      <div className="flex flex-wrap gap-2">
        {item.status_candidate && <StatusBadge status={item.status_candidate as FindingOut['status']} />}
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
      <div>
        <h3 className="text-sm font-semibold text-slate-700">Analysis citations</h3>
        <ul className="mt-2 space-y-2 text-sm">
          {item.citations.length === 0 ? (
            <li className="text-slate-500">No citations.</li>
          ) : (
            item.citations.map((c, idx) => (
              <li key={`${c.chunk_id}-${idx}`} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <div className="font-medium text-slate-800">{c.article_number} — {c.article_title}</div>
                <p className="mt-1 text-slate-600">{c.excerpt}</p>
              </li>
            ))
          )}
        </ul>
      </div>
    </>
  )
}

function Pill({ value }: { value: string }) {
  return <span className="rounded-full border border-slate-300 bg-slate-100 px-2 py-1 text-xs text-slate-700">{value}</span>
}

function EmptyState({ message }: { message: string }) {
  return <div className="surface-card p-6 text-slate-600">{message}</div>
}
