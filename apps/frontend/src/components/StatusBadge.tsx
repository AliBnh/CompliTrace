const styles: Record<string, string> = {
  compliant: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  'partially compliant': 'bg-amber-50 text-amber-700 border-amber-200',
  'non-compliant': 'bg-rose-50 text-rose-700 border-rose-200',
  'not applicable': 'bg-slate-100 text-slate-700 border-slate-200',
  partial: 'bg-amber-50 text-amber-700 border-amber-200',
  gap: 'bg-rose-50 text-rose-700 border-rose-200',
  'needs review': 'bg-sky-50 text-sky-700 border-sky-200',
  candidate_compliant: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  candidate_partial: 'bg-amber-50 text-amber-700 border-amber-200',
  candidate_gap: 'bg-rose-50 text-rose-700 border-rose-200',
  not_applicable: 'bg-slate-100 text-slate-700 border-slate-200',
  needs_review: 'bg-sky-50 text-sky-700 border-sky-200',
  supporting_evidence: 'bg-cyan-50 text-cyan-700 border-cyan-200',
  blocked: 'bg-rose-50 text-rose-700 border-rose-200',
}

export function StatusBadge({ status }: { status: string }) {
  const key = status.replace(/_/g, ' ').toLowerCase()
  const label = key
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
  return <span className={`inline-flex h-6 min-w-[7.25rem] items-center justify-center whitespace-nowrap rounded-full border px-3 text-xs font-medium leading-none ${styles[key] ?? styles['needs review']}`}>{label}</span>
}
