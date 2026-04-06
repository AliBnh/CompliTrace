const styles: Record<string, string> = {
  compliant: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/40',
  partial: 'bg-amber-500/15 text-amber-300 border-amber-400/40',
  gap: 'bg-rose-500/15 text-rose-300 border-rose-400/40',
  'needs review': 'bg-sky-500/15 text-sky-300 border-sky-400/40',
  'not applicable': 'bg-slate-500/20 text-slate-200 border-slate-300/40',
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${styles[status] ?? styles['needs review']}`}>{status}</span>
}
