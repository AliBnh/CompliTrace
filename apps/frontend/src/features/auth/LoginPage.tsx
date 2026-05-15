import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { useAppState } from '../../app/state'
import { login } from '../../lib/api'
import { FileText, Scale, ShieldCheck } from 'lucide-react'

export function LoginPage() {
  const navigate = useNavigate()
  const { token, signIn } = useAppState()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (token) return <Navigate to="/" replace />

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const result = await login({ email, password })
      signIn(result.access_token, result.user)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="grid min-h-screen grid-cols-1 bg-slate-50 lg:grid-cols-[1.1fr_0.9fr]">
      <div className="relative hidden overflow-hidden bg-slate-900 p-14 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-sky-400/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-16 left-10 h-52 w-52 rounded-full bg-blue-500/20 blur-3xl" />
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Compli<span className="text-sky-300">Trace</span>
          </h1>
          <p className="mt-3 max-w-md text-sm text-slate-300">Enterprise-grade GDPR audits with cleaner workflows, consistent evidence, and executive-ready reporting.</p>
          <div className="mt-8 grid max-w-md grid-cols-3 gap-3">
            <FeatureIconCard icon={<FileText className="h-5 w-5" />} title="Documents" desc="Lifecycle versions and exports." />
            <FeatureIconCard icon={<Scale className="h-5 w-5" />} title="Deterministic" desc="Clear findings with evidence." />
            <FeatureIconCard icon={<ShieldCheck className="h-5 w-5" />} title="Trust" desc="Audit-ready reporting." />
          </div>
          <div className="mt-8 space-y-3">
            <div className="rounded-xl border border-white/15 bg-white/5 p-3">
              <p className="text-xs uppercase tracking-widest text-slate-300">Workflow coverage</p>
              <p className="mt-1 text-sm text-white">Upload to Sections to Findings to Remediation to Report</p>
            </div>
            <div className="rounded-xl border border-white/15 bg-white/5 p-3">
              <p className="text-xs uppercase tracking-widest text-slate-300">Evidence-first</p>
              <p className="mt-1 text-sm text-white">Each decision is traceable to source excerpts and legal anchors.</p>
            </div>
          </div>
        </div>
        <p className="text-xs text-slate-400">Trusted by legal, privacy, and compliance teams.</p>
      </div>
      <div className="flex items-center justify-center p-6">
        <article className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-[0_12px_40px_rgba(15,23,42,0.08)]">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-900">Sign in</h2>
            <p className="mt-1 text-sm text-gray-500">Continue to your audit workspace.</p>
          </div>
          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            <Field label="Email" type="email" value={email} onChange={setEmail} />
            <Field label="Password" type="password" value={password} onChange={setPassword} />
            {error && <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            <button className="btn-primary w-full" disabled={loading}>
              {loading ? 'Signing in...' : 'Sign in'}
            </button>
          </form>
          <p className="mt-4 text-center text-sm text-gray-500">
            New to CompliTrace? <Link to="/signup" className="text-sky-600 hover:underline">Create an account</Link>
          </p>
        </article>
      </div>
    </section>
  )
}

function FeatureIconCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-white/10 text-sky-200">
        {icon}
      </div>
      <div className="mt-2 text-sm font-semibold text-white">{title}</div>
      <div className="mt-0.5 text-xs text-slate-300">{desc}</div>
    </div>
  )
}

function Field({
  label,
  type,
  value,
  onChange,
}: {
  label: string
  type: string
  value: string
  onChange: (next: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-sky-400"
      />
    </label>
  )
}
