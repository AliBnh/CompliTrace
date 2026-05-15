const styles: Record<string, string> = {
  compliant: 'bg-emerald-500 text-white',
  'partially compliant': 'bg-amber-500 text-white',
  'non-compliant': 'bg-red-500 text-white',
  'not applicable': 'bg-slate-400 text-white',
  partial: 'bg-amber-500 text-white',
  gap: 'bg-red-500 text-white',
  'needs review': 'bg-blue-500 text-white',
  candidate_compliant: 'bg-emerald-500 text-white',
  candidate_partial: 'bg-amber-500 text-white',
  candidate_gap: 'bg-red-500 text-white',
  not_applicable: 'bg-slate-400 text-white',
  needs_review: 'bg-blue-500 text-white',
  supporting_evidence: 'bg-cyan-500 text-white',
  blocked: 'bg-red-500 text-white',
}

export function StatusBadge({ status }: { status: string }) {
  const key = status.replace(/_/g, ' ').toLowerCase()
  const label = key
    .split(' ')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
  return (
    <span
      className={`inline-flex h-6 min-w-[7.25rem] items-center justify-center whitespace-nowrap rounded-full px-3 text-xs font-medium leading-none ${styles[key] ?? 'bg-slate-400 text-white'}`}
    >
      {label}
    </span>
  )
}
