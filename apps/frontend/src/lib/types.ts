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
  status: 'pending' | 'running' | 'complete' | 'failed' | 'review_required' | 'audit_incomplete'
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
  evidence_id?: string | null
  source_type?: string | null
  source_ref?: string | null
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
  publication_blocked?: boolean | null
  issue_key?: string | null
  blocker_reason?: string | null
  missing_requirements?: string[] | null
  affected_sections?: string[] | null
  where_evidence_found?: string[] | null
  where_disclosure_missing?: string[] | null
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

export type ExportContractOut = {
  report_type: 'Published report' | 'Review report (final publication pending)'
  dataset_used: 'published' | 'review'
  export_allowed: boolean
  blocker_reasons: string[]
  counts_by_status: {
    compliant: number
    partially_compliant: number
    non_compliant: number
    not_applicable: number
    total: number
  }
  finding_ids: string[]
  document_wide_finding_ids: string[]
  section_finding_ids: string[]
  generated_from_audit_id: UUID
  generated_at: string
}

export type AnalysisCitationOut = CitationOut

export type AnalysisItemOut = {
  id: UUID
  section_id: string
  analysis_stage?: string | null
  analysis_type: string
  issue_type?: string | null
  status_candidate?: string | null
  classification_candidate?: string | null
  artifact_role?: string | null
  finding_level_candidate?: string | null
  publication_state_candidate?: string | null
  suppression_reason?: string | null
  gap_note?: string | null
  remediation_note?: string | null
  citations: AnalysisCitationOut[]
}

export type ReviewItemOut = {
  item_kind: 'finding' | 'analysis' | 'review_block'
  id: UUID
  section_id: string
  issue_type?: string | null
  status?: string | null
  classification?: string | null
  artifact_role?: string | null
  finding_level?: string | null
  publication_state?: string | null
  suppression_reason?: string | null
  completeness_map?: string | null
  gap_note?: string | null
  remediation_note?: string | null
  review_group?: string | null
  duty?: string | null
  family?: string | null
  triggered?: boolean | null
  final_disposition?: string | null
  reason?: string | null
  source_scope_dependency?: string | null
  publication_recommendation?: string | null
  citations?: CitationOut[] | null
}
