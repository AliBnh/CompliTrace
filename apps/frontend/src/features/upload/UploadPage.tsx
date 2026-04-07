import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAppState } from '../../app/state'
import { uploadDocument } from '../../lib/api'

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
    <section className="grid gap-6 xl:grid-cols-[1.45fr_1fr]">
      <article className="surface-card animate-rise p-8">
        <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="section-title">Upload policy document</h1>
            <p className="section-subtitle">Start by adding a PDF. We extract sections and prepare the audit workspace automatically.</p>
          </div>
          <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">Step 1 of 4</span>
        </div>

        <label className="group block cursor-pointer rounded-2xl border border-dashed border-sky-300 bg-gradient-to-br from-sky-50/90 via-white to-blue-50/90 p-9 text-center transition-all duration-300 hover:-translate-y-0.5 hover:border-sky-400 hover:shadow-lg">
          <input type="file" accept="application/pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full border border-slate-200 bg-white text-2xl shadow-sm transition group-hover:scale-105">📄</div>
          <p className="text-sm font-semibold text-slate-800">Choose a policy PDF (up to 20 MB)</p>
          <p className="mt-1 text-xs text-slate-500">Drag-and-drop is optional; click to browse securely.</p>
          <p className="mt-3 truncate text-sm font-medium text-sky-700">{file?.name ?? 'No file selected yet'}</p>
        </label>

        {loading && (
          <div className="detail-block mt-6">
            <div className="mb-2 flex items-center justify-between text-sm text-slate-600">
              <span>Uploading and parsing</span>
              <span className="font-medium text-slate-700">{progress}%</span>
            </div>
            <div className="h-2 rounded-full bg-slate-200/80">
              <div className="h-full rounded-full bg-gradient-to-r from-sky-500 to-blue-600 transition-all duration-500" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {error && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</div>}

        <div className="mt-7 flex flex-wrap items-center gap-3">
          <button onClick={onUpload} disabled={!file || loading} className="btn-primary min-w-40">
            {loading ? 'Uploading…' : 'Upload & parse'}
          </button>
          <span className="text-xs text-slate-500">PDF content remains associated with this audit workflow.</span>
        </div>
      </article>

      <aside className="surface-card animate-rise p-6">
        <h2 className="text-lg font-semibold text-slate-900">Guided workflow</h2>
        <p className="mt-1 text-sm text-slate-500">Each stage keeps the legal review focused and auditable.</p>
        <ol className="mt-5 space-y-3">
          {[
            { title: 'Upload policy PDF', desc: 'Create a document record and parse sections.' },
            { title: 'Review sections', desc: 'Verify extraction quality before analysis.' },
            { title: 'Inspect findings', desc: 'Navigate published, review, and analysis layers.' },
            { title: 'Export report', desc: 'Generate an executive PDF with audit metrics.' },
          ].map((step, index) => (
            <li key={step.title} className="detail-block flex items-start gap-3">
              <span className="mt-0.5 inline-flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-blue-600 text-xs font-semibold text-white">{index + 1}</span>
              <div>
                <p className="text-sm font-semibold text-slate-800">{step.title}</p>
                <p className="text-xs text-slate-500">{step.desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </section>
  )
}
