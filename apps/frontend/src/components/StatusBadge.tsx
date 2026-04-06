const styles: Record<string, string> = {
  compliant: 'bg-emerald-100 text-emerald-700 border-emerald-300',
  partial: 'bg-amber-100 text-amber-700 border-amber-300',
  gap: 'bg-rose-100 text-rose-700 border-rose-300',
  'needs review': 'bg-sky-100 text-sky-700 border-sky-300',
  'not applicable': 'bg-slate-100 text-slate-700 border-slate-300',
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize ${styles[status] ?? styles['needs review']}`}>{status}</span>
}
