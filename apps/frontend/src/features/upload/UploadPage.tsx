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
      <article className="surface-card p-8">
        <h1 className="text-3xl font-semibold">Upload Policy Document</h1>
        <p className="mt-3 text-slate-600">Upload a PDF policy to start section extraction and GDPR pre-audit analysis.</p>

        <label className="mt-8 block rounded-xl border border-dashed border-slate-300 bg-slate-50 p-8 text-center hover:border-cyan-500/50">
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div className="text-sm text-slate-600">Click to choose a PDF (max 20 MB)</div>
          <div className="mt-2 font-medium text-cyan-700">{file?.name ?? 'No file selected'}</div>
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

      <aside className="surface-card p-6">
        <h2 className="text-lg font-semibold">Workflow</h2>
        <ol className="mt-4 space-y-3 text-sm text-slate-600">
          <li>1. Upload policy PDF</li>
          <li>2. Review extracted sections</li>
          <li>3. Trigger audit and inspect findings</li>
          <li>4. Generate and download report</li>
        </ol>
      </aside>
    </section>
  )
}
