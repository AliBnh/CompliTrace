export type UUID = string

export type AuthUser = {
  id: UUID
  first_name: string
  last_name: string
  email: string
  organization_name: string
}

export type AuthResponse = {
  access_token: string
  token_type: string
  user: AuthUser
}

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
  user_id?: UUID | null
  document_group_id?: UUID | null
  version_number?: number | null
  started_at: string
  completed_at?: string | null
  model_provider: string
  model_name: string
  model_temperature: number
  prompt_template_version: string
  embedding_model: string
  corpus_version: string
  compliance_score: number | null
}

export type GroupVersionOut = {
  document_id: UUID
  audit_id: UUID
  version_number: number
  compliance_score: number | null
  created_at: string
}

export type GroupOut = {
  id: UUID
  name: string
  created_at: string
  versions: GroupVersionOut[]
  latest_compliance_score: number | null
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

/**
 * Clean client-facing schema for the published /findings endpoint.
 * Contains only client-safe fields — no internal publication-control state.
 */
export type PublishedFindingOut = {
  id: UUID
  section_id: string
  issue_key: string
  issue_label: string
  status: string
  severity: string
  confidence_level?: string | null
  confidence_overall?: number | null
  affected_sections: string[]
  policy_evidence_excerpt?: string | null
  legal_requirement?: string | null
  primary_legal_anchor?: string[] | null
  gap_note: string
  omission_statement?: string | null
  gap_reasoning?: string | null
  remediation_note: string
  severity_rationale?: string | null
  citation_summary_text?: string | null
  citations: CitationOut[]
}

/** @deprecated Internal schema kept for review/analysis views — not used by the published endpoint. */
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
  issue_label?: string | null
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
  report_type: 'Published report' | 'Review report (final publication pending)' | 'Preliminary analysis report' | 'Zero-findings report'
  dataset_used: 'published' | 'review' | 'analysis' | 'zero'
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

export type RemediationSuggestionOut = {
  id: string
  generation_status: 'pending' | 'complete' | 'failed'
  suggested_fix_text: string | null
}

export type RemediationItemOut = {
  id: string
  audit_id: string
  finding_id: string
  issue_key: string
  issue_label: string
  severity: 'high' | 'medium' | 'low'
  score_impact_points: number
  order_index: number
  section_id: string | null
  suggestion: RemediationSuggestionOut | null
}

export type RemediationStatusOut = {
  total: number
  pending: number
  complete: number
  failed: number
  is_compliant: boolean
}

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
  item_kind: 'finding' | 'analysis' | 'review_block' | 'diagnostics_summary'
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
  diagnostics_count?: number | null
}
