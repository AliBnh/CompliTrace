import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { useAppState } from '../../app/state'
import { getAudit, getRemediation, getSections, triggerRemediation } from '../../lib/api'
import type { RemediationItemOut, SectionOut } from '../../lib/types'
import { MapPin, Copy, Check } from 'lucide-react'

export function RemediationPage() {
  const { auditId, documentId } = useAppState()
  const [complianceScore, setComplianceScore] = useState<number | null>(null)
  const [items, setItems] = useState<RemediationItemOut[]>([])
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>({})
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!documentId) return
    getSections(documentId)
      .then((sections) => setSectionsById(Object.fromEntries(sections.map((s) => [s.id, s]))))
      .catch(() => {})
  }, [documentId])

  useEffect(() => {
    if (!auditId) return
    getAudit(auditId)
      .then((a) => setComplianceScore(a.compliance_score ?? null))
      .catch(() => {})
    getRemediation(auditId)
      .then((data) => {
        setItems(data)
        if (data.length > 0 && data.every((i) => i.suggestion?.generation_status === 'complete')) {
          setGenerated(true)
        }
      })
      .catch(() => {})
  }, [auditId])

  async function handleGenerate() {
    if (!auditId) return
    setError(null)
    setGenerating(true)
    try {
      await triggerRemediation(auditId)
      const data = await getRemediation(auditId)
      setItems(data)
      setGenerated(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to generate suggestions')
    } finally {
      setGenerating(false)
    }
  }

  function copyToClipboard(text: string, id: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(id)
      if (copiedTimer.current) clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(null), 2000)
    })
  }

  function placementLabel(sectionId: string | null): { label: string; icon: 'doc' | 'section' } {
    if (!sectionId || sectionId.startsWith('systemic:')) {
      return { label: 'Entire document — this clause belongs at the document level in your privacy notice', icon: 'doc' }
    }
    const section = sectionsById[sectionId]
    if (section) {
      const pageNote = section.page_start != null ? ` (page ${section.page_start})` : ''
      return {
        label: `Section ${section.section_order}: "${section.section_title}"${pageNote} — add or update this clause within that section`,
        icon: 'section',
      }
    }
    return { label: 'Specific section of your privacy notice', icon: 'section' }
  }

  if (!auditId) {
    return (
      <div className="surface-card flex flex-col items-center justify-center px-6 py-16 text-center">
        <svg className="mb-3 h-10 w-10 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
        </svg>
        <p className="text-sm text-gray-500">Run an audit first.</p>
      </div>
    )
  }

  if (complianceScore === 100) {
    return (
      <section className="space-y-5">
        <div className="surface-card flex flex-col items-center justify-center px-6 py-16 text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100">
            <svg className="h-9 w-9 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-slate-900">This document is 100% compliant</h1>
          <p className="mt-2 text-sm text-gray-500">No remediation required. All GDPR transparency obligations are satisfied.</p>
          <Link to="/report" className="btn-primary mt-6">Proceed to Report</Link>
        </div>
      </section>
    )
  }

  const totalImpact = items.reduce((sum, i) => sum + i.score_impact_points, 0)

  return (
    <section className="space-y-5">
      <header className="surface-card p-6">
        <h1 className="section-title">Path to 100% Compliance</h1>
        <p className="section-subtitle">
          Each item below identifies a gap in your privacy notice, tells you exactly where to add the fix, and provides a ready-to-adapt GDPR clause.
        </p>

        {complianceScore !== null && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <div className={`flex flex-col items-center rounded-xl border px-5 py-2.5 ${scoreClass(complianceScore)}`}>
              <span className="text-3xl font-bold leading-none">{complianceScore}%</span>
              <span className="mt-1 text-xs font-semibold uppercase tracking-wide opacity-75">Current Score</span>
            </div>
            {items.length > 0 && (
              <>
                <svg className="h-5 w-5 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                </svg>
                <div className="flex flex-col items-center rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-2.5 text-emerald-700">
                  <span className="text-3xl font-bold leading-none">{Math.min(100, complianceScore + totalImpact)}%</span>
                  <span className="mt-1 text-xs font-semibold uppercase tracking-wide opacity-75">After Fixing All</span>
                </div>
              </>
            )}
          </div>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button onClick={handleGenerate} disabled={generating} className="btn-primary min-w-52">
            {generating ? 'Generating fixes…' : generated ? 'Regenerate Suggested Fixes' : 'Generate Suggested Fixes'}
          </button>
          <Link to="/report" className="inline-flex items-center justify-center rounded-xl border-2 border-slate-400 bg-white px-5 py-2.5 text-sm font-semibold text-slate-800 shadow-sm transition-all hover:border-slate-500 hover:bg-slate-50">
            Proceed to Report
          </Link>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
        )}
      </header>

      {items.length === 0 && !generating && (
        <div className="surface-card p-8 text-center">
          <p className="text-sm text-gray-500">Click "Generate Suggested Fixes" to produce AI-drafted GDPR clauses for each gap.</p>
        </div>
      )}

      {items.length > 0 && (
        <div className="space-y-4">
          {items.map((item, idx) => {
            const placement = placementLabel(item.section_id)
            return (
              <article key={item.id} className="surface-card overflow-hidden">
                {/* Header bar */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-6 py-4">
                  <div className="flex items-center gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-500">
                      {idx + 1}
                    </span>
                    <span className={`rounded-md px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide ${severityClass(item.severity)}`}>
                      {item.severity}
                    </span>
                    <h2 className="text-sm font-semibold text-slate-900">{item.issue_label}</h2>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="rounded-full bg-emerald-100 px-3 py-0.5 text-xs font-semibold text-emerald-700">
                      +{item.score_impact_points}% if fixed
                    </span>
                    <Link to="/findings" className="text-xs text-sky-600 hover:underline">View finding →</Link>
                  </div>
                </div>

                <div className="px-6 py-5 space-y-5">
                  {/* WHERE to put it */}
                  <div className="flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                    <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">Placement</p>
                      <p className="mt-0.5 text-sm text-slate-800">{placement.label}</p>
                    </div>
                  </div>

                  {/* Suggested fix */}
                  {item.suggestion?.generation_status === 'complete' && item.suggestion.suggested_fix_text ? (
                    <div>
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-semibold uppercase tracking-widest text-gray-500">Suggested clause — copy and adapt</p>
                        <button
                          onClick={() => copyToClipboard(item.suggestion!.suggested_fix_text!, item.id)}
                          className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
                        >
                          {copied === item.id ? (
                            <><Check className="h-4 w-4 text-emerald-600" />Copied</>
                          ) : (
                            <><Copy className="h-4 w-4" />Copy clause</>
                          )}
                        </button>
                      </div>
                      <blockquote className="mt-2 rounded-xl border border-slate-200 bg-slate-50 p-4 font-mono text-sm leading-relaxed text-slate-700 whitespace-pre-wrap">
                        {item.suggestion.suggested_fix_text}
                      </blockquote>
                      <p className="mt-2 text-xs text-gray-400">
                        Bracketed values like <span className="font-mono">[Organization Name]</span> must be replaced with your organization's specific details before use.
                      </p>
                    </div>
                  ) : item.suggestion?.generation_status === 'failed' ? (
                    <p className="text-sm text-red-600">Suggestion generation failed. Try clicking Regenerate.</p>
                  ) : generating ? (
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Drafting suggested clause…
                    </div>
                  ) : (
                    <p className="text-sm text-gray-400">Click "Generate Suggested Fixes" to get a ready-to-adapt GDPR clause for this gap.</p>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function scoreClass(score: number): string {
  if (score >= 80) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (score >= 50) return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-red-200 bg-red-50 text-red-700'
}

function severityClass(severity: string): string {
  if (severity === 'high') return 'bg-red-100 text-red-700'
  if (severity === 'medium') return 'bg-amber-100 text-amber-700'
  return 'bg-gray-100 text-gray-600'
}
