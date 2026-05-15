import type {
  AnalysisItemOut,
  AuthResponse,
  AuthUser,
  AuditOut,
  DocumentOut,
  ExportContractOut,
  PublishedFindingOut,
  GroupOut,
  RemediationItemOut,
  RemediationStatusOut,
  ReportOut,
  ReviewItemOut,
  SectionOut,
} from './types'

const INGESTION_BASE = import.meta.env.VITE_INGESTION_URL ?? 'http://localhost:8001'
const ORCHESTRATION_BASE = import.meta.env.VITE_ORCHESTRATION_URL ?? 'http://localhost:8003'
const AUTH_BASE = import.meta.env.VITE_AUTH_URL ?? 'http://localhost:8004'

let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler
}

function getToken(): string | null {
  return localStorage.getItem('auth_token')
}

function clearSessionAndNotify() {
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
  onUnauthorized?.()
}

async function parseResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    clearSessionAndNotify()
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed with ${res.status}`)
  }
  return res.json() as Promise<T>
}

async function orchestrationFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return fetch(`${ORCHESTRATION_BASE}${path}`, { ...init, headers })
}

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${AUTH_BASE}${path}`, init)
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

export async function createAudit(documentId: string, groupId?: string | null): Promise<AuditOut> {
  const res = await orchestrationFetch('/audits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_id: documentId, group_id: groupId ?? null }),
  })
  return parseResponse<AuditOut>(res)
}

export async function getAudit(auditId: string): Promise<AuditOut> {
  const res = await orchestrationFetch(`/audits/${auditId}`)
  return parseResponse<AuditOut>(res)
}

export async function getFindings(auditId: string): Promise<PublishedFindingOut[]> {
  const res = await orchestrationFetch(`/audits/${auditId}/findings`)
  return parseResponse<PublishedFindingOut[]>(res)
}

export async function getAnalysis(auditId: string): Promise<AnalysisItemOut[]> {
  const res = await orchestrationFetch(`/audits/${auditId}/analysis`)
  return parseResponse<AnalysisItemOut[]>(res)
}

export async function getReview(auditId: string): Promise<ReviewItemOut[]> {
  const res = await orchestrationFetch(`/audits/${auditId}/review`)
  return parseResponse<ReviewItemOut[]>(res)
}

export async function createReport(auditId: string): Promise<{ report_id: string; status: string }> {
  const res = await orchestrationFetch(`/audits/${auditId}/report`, {
    method: 'POST',
  })
  return parseResponse<{ report_id: string; status: string }>(res)
}

export async function getReport(auditId: string): Promise<ReportOut> {
  const res = await orchestrationFetch(`/audits/${auditId}/report`)
  return parseResponse<ReportOut>(res)
}

export async function getExportContract(auditId: string): Promise<ExportContractOut> {
  const res = await orchestrationFetch(`/audits/${auditId}/export-contract`)
  return parseResponse<ExportContractOut>(res)
}

export function reportDownloadUrl(auditId: string): string {
  return `${ORCHESTRATION_BASE}/audits/${auditId}/report/download`
}

export async function downloadReport(auditId: string): Promise<Blob> {
  const res = await orchestrationFetch(`/audits/${auditId}/report/download`)
  if (res.status === 401) {
    clearSessionAndNotify()
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed with ${res.status}`)
  }
  return res.blob()
}

export async function triggerRemediation(auditId: string): Promise<{ status: string; message: string }> {
  const res = await orchestrationFetch(`/audits/${auditId}/remediation`, { method: 'POST' })
  return parseResponse<{ status: string; message: string }>(res)
}

export async function getRemediation(auditId: string): Promise<RemediationItemOut[]> {
  const res = await orchestrationFetch(`/audits/${auditId}/remediation`)
  return parseResponse<RemediationItemOut[]>(res)
}

export async function getRemediationStatus(auditId: string): Promise<RemediationStatusOut> {
  const res = await orchestrationFetch(`/audits/${auditId}/remediation/status`)
  return parseResponse<RemediationStatusOut>(res)
}

export async function getGroups(): Promise<GroupOut[]> {
  const res = await orchestrationFetch('/groups')
  return parseResponse<GroupOut[]>(res)
}

export async function createGroup(name: string): Promise<GroupOut> {
  const res = await orchestrationFetch('/groups', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return parseResponse<GroupOut>(res)
}

export async function renameGroup(groupId: string, name: string): Promise<GroupOut> {
  const res = await orchestrationFetch(`/groups/${groupId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return parseResponse<GroupOut>(res)
}

export async function deleteGroup(groupId: string): Promise<void> {
  const res = await orchestrationFetch(`/groups/${groupId}`, { method: 'DELETE' })
  if (res.status === 401) clearSessionAndNotify()
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed with ${res.status}`)
  }
}

export async function signup(payload: {
  first_name: string
  last_name: string
  email: string
  password: string
  organization_name: string
}): Promise<AuthResponse> {
  const res = await authFetch('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseResponse<AuthResponse>(res)
}

export async function login(payload: { email: string; password: string }): Promise<AuthResponse> {
  const res = await authFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return parseResponse<AuthResponse>(res)
}

export async function getMe(token: string): Promise<AuthUser> {
  const res = await authFetch('/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  return parseResponse<AuthUser>(res)
}
