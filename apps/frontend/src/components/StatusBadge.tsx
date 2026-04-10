const styles: Record<string, string> = {
  compliant: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  partial: 'bg-amber-50 text-amber-700 border-amber-200',
  gap: 'bg-rose-50 text-rose-700 border-rose-200',
  'needs review': 'bg-sky-50 text-sky-700 border-sky-200',
  'not applicable': 'bg-slate-100 text-slate-700 border-slate-200',
  candidate_compliant: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  candidate_partial: 'bg-amber-50 text-amber-700 border-amber-200',
  candidate_gap: 'bg-rose-50 text-rose-700 border-rose-200',
  not_applicable: 'bg-slate-100 text-slate-700 border-slate-200',
  needs_review: 'bg-sky-50 text-sky-700 border-sky-200',
  supporting_evidence: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  blocked: 'bg-rose-50 text-rose-700 border-rose-200',
}

export function StatusBadge({ status }: { status: string }) {
  const label = status.replace(/_/g, ' ')
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${styles[status] ?? styles['needs review']}`}>{label}</span>
}
