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
  classification?: string | null
  finding_type?: string | null
  publish_flag?: string | null
  confidence?: number | null
  confidence_level?: string | null
  assessment_type?: string | null
  primary_legal_anchor?: string[] | null
  secondary_legal_anchors?: string[] | null
  document_evidence_refs?: string[] | null
  citation_summary_text?: string | null
  support_complete?: boolean | null
  omission_basis?: boolean | null
  source_scope?: 'full_notice' | 'partial_notice_excerpt' | 'uncertain_scope' | null
  source_scope_confidence?: number | null
  referenced_unseen_sections?: string[] | null
  assertion_level?: 'confirmed_document_gap' | 'excerpt_limited_gap' | 'referenced_but_unseen' | 'not_assessable' | null
  legal_requirement?: string | null
  gap_reasoning?: string | null
  severity_rationale?: string | null
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
