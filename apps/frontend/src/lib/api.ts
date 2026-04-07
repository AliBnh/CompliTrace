import type { AnalysisItemOut, AuditOut, DocumentOut, FindingOut, ReportOut, ReviewItemOut, SectionOut } from './types'

const INGESTION_BASE = import.meta.env.VITE_INGESTION_URL ?? 'http://localhost:8001'
const ORCHESTRATION_BASE = import.meta.env.VITE_ORCHESTRATION_URL ?? 'http://localhost:8003'

async function parseResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed with ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function uploadDocument(file: File, onProgress?: (percent: number) => void): Promise<DocumentOut> {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    const req = new XMLHttpRequest()
    req.open('POST', `${INGESTION_BASE}/documents`)
    req.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return
      onProgress(Math.round((event.loaded / event.total) * 100))
    }
    req.onload = () => {
      if (req.status >= 200 && req.status < 300) {
        resolve(JSON.parse(req.responseText) as DocumentOut)
        return
      }
      reject(new Error(req.responseText || `Upload failed with ${req.status}`))
    }
    req.onerror = () => reject(new Error('Upload failed due to a network error'))
    req.send(form)
  })
}

export async function getDocument(documentId: string): Promise<DocumentOut> {
  const res = await fetch(`${INGESTION_BASE}/documents/${documentId}`)
  return parseResponse<DocumentOut>(res)
}

export async function getSections(documentId: string): Promise<SectionOut[]> {
  const res = await fetch(`${INGESTION_BASE}/documents/${documentId}/sections`)
  return parseResponse<SectionOut[]>(res)
}

export async function createAudit(documentId: string): Promise<AuditOut> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_id: documentId }),
  })
  return parseResponse<AuditOut>(res)
}

export async function getAudit(auditId: string): Promise<AuditOut> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits/${auditId}`)
  return parseResponse<AuditOut>(res)
}

export async function getFindings(auditId: string): Promise<FindingOut[]> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits/${auditId}/findings`)
  return parseResponse<FindingOut[]>(res)
}

export async function getAnalysis(auditId: string): Promise<AnalysisItemOut[]> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits/${auditId}/analysis`)
  return parseResponse<AnalysisItemOut[]>(res)
}

export async function getReview(auditId: string): Promise<ReviewItemOut[]> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits/${auditId}/review`)
  return parseResponse<ReviewItemOut[]>(res)
}

export async function createReport(auditId: string): Promise<{ report_id: string; status: string }> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits/${auditId}/report`, {
    method: 'POST',
  })
  return parseResponse<{ report_id: string; status: string }>(res)
}

export async function getReport(auditId: string): Promise<ReportOut> {
  const res = await fetch(`${ORCHESTRATION_BASE}/audits/${auditId}/report`)
  return parseResponse<ReportOut>(res)
}

export function reportDownloadUrl(auditId: string): string {
  return `${ORCHESTRATION_BASE}/audits/${auditId}/report/download`
}
