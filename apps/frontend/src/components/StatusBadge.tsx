const styles: Record<string, string> = {
  compliant: 'bg-emerald-100 text-emerald-700 border-emerald-300',
  partial: 'bg-amber-100 text-amber-700 border-amber-300',
  gap: 'bg-rose-100 text-rose-700 border-rose-300',
  'needs review': 'bg-sky-100 text-sky-700 border-sky-300',
  'not applicable': 'bg-slate-100 text-slate-700 border-slate-300',
  candidate_compliant: 'bg-emerald-50 text-emerald-700 border-emerald-300',
  candidate_partial: 'bg-amber-50 text-amber-700 border-amber-300',
  candidate_gap: 'bg-rose-50 text-rose-700 border-rose-300',
  not_applicable: 'bg-slate-100 text-slate-700 border-slate-300',
  needs_review: 'bg-sky-100 text-sky-700 border-sky-300',
  supporting_evidence: 'bg-sky-50 text-sky-700 border-sky-300',
  blocked: 'bg-rose-50 text-rose-700 border-rose-300',
}

export function StatusBadge({ status }: { status: string }) {
  const label = status.replace(/_/g, ' ')
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${styles[status] ?? styles['needs review']}`}>{label}</span>
}
