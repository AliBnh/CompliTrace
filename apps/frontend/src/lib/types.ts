export type UUID = string

export type DocumentOut = {
  id: UUID
  title: string
  filename: string
  status: 'pending' | 'parsed' | 'failed'
  section_count: number
  error_message?: string | null
}

export type SectionOut = {
  id: UUID
  document_id: UUID
  section_order: number
  section_title: string
  content: string
  page_start: number | null
  page_end: number | null
}

export type AuditOut = {
  id: UUID
  document_id: UUID
  status: 'pending' | 'running' | 'complete' | 'failed'
  started_at: string
  completed_at?: string | null
  model_provider: string
  model_name: string
  model_temperature: number
  prompt_template_version: string
  embedding_model: string
  corpus_version: string
}

export type CitationOut = {
  chunk_id: string
  article_number: string
  paragraph_ref: string | null
  article_title: string
  excerpt: string
}

export type FindingOut = {
  id: UUID
  section_id: UUID
  status: 'compliant' | 'partial' | 'gap' | 'needs review' | 'not applicable'
  severity: 'low' | 'medium' | 'high' | null
  gap_note: string | null
  remediation_note: string | null
  citations: CitationOut[]
}

export type ReportOut = {
  id: UUID
  audit_id: UUID
  status: 'pending' | 'ready' | 'failed'
  pdf_path: string | null
  created_at: string
}
