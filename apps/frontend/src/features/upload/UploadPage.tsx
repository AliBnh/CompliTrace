import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { uploadDocument } from '../../lib/api'
import { useAppState } from '../../app/state'

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number>(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const { setDocumentId, setAuditId } = useAppState()

  async function onUpload() {
    if (!file) return
    setLoading(true)
    setError(null)
    setProgress(0)
    try {
      const doc = await uploadDocument(file, setProgress)
      setDocumentId(doc.id)
      setAuditId(null)
      navigate('/sections')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      <article className="surface-card p-8 animate-rise">
        <h1 className="section-title">Upload Policy Document</h1>
        <p className="section-subtitle">Upload a PDF policy to start section extraction and GDPR pre-audit analysis.</p>

        <label className="group mt-8 block cursor-pointer rounded-2xl border-2 border-dashed border-cyan-300 bg-gradient-to-br from-cyan-50 to-blue-50 p-8 text-center transition-all duration-300 hover:-translate-y-0.5 hover:border-cyan-500 hover:shadow-lg">
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full bg-white text-2xl shadow-md transition group-hover:scale-105">
            📄
          </div>
          <div className="text-sm font-medium text-slate-700">Click to choose a PDF (max 20 MB)</div>
          <div className="mt-1 text-xs text-cyan-700">Browse files and select your policy document</div>
          <div className="mt-3 font-medium text-cyan-800">{file?.name ?? 'No file selected'}</div>
        </label>

        {loading && (
          <div className="mt-6">
            <div className="mb-2 text-sm text-slate-600">Uploading and parsing... {progress}%</div>
            <div className="h-2 rounded-full bg-slate-200">
              <div className="h-full rounded-full bg-cyan-500 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {error && <div className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}

        <button onClick={onUpload} disabled={!file || loading} className="btn-primary mt-8">
          {loading ? 'Uploading...' : 'Upload & Parse'}
        </button>
      </article>

      <aside className="surface-card p-6 animate-rise">
        <h2 className="text-lg font-semibold">Workflow</h2>
        <ol className="mt-4 space-y-3">
          {[
            { title: 'Upload policy PDF', tone: 'from-cyan-500 to-blue-500', desc: 'Add your policy file to begin analysis.' },
            { title: 'Review extracted sections', tone: 'from-indigo-500 to-violet-500', desc: 'Validate parser output before audit.' },
            { title: 'Run audit and inspect findings', tone: 'from-violet-500 to-fuchsia-500', desc: 'Analyze compliance gaps and evidence.' },
            { title: 'Generate and download report', tone: 'from-emerald-500 to-teal-500', desc: 'Export executive-ready PDF report.' },
          ].map((step, index) => (
            <li key={step.title} className="relative">
              {index < 3 && <div className="absolute left-[26px] top-[40px] h-[40px] w-[2px] bg-slate-200" />}
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white/80 p-3 transition hover:border-slate-300 hover:shadow-sm">
                <span className={`mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${step.tone} text-xs font-bold text-white shadow`}>
                  {index + 1}
                </span>
                <div>
                  <p className="text-sm font-semibold text-slate-800">{step.title}</p>
                  <p className="text-xs text-slate-500">{step.desc}</p>
                </div>
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </section>
  )
}
