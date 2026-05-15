from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class CitationOut(BaseModel):
    chunk_id: str
    evidence_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    article_number: str
    paragraph_ref: str | None
    article_title: str
    excerpt: str


class PublishedFindingOut(BaseModel):
    """Clean client-facing schema for the published /findings endpoint.

    Contains only client-safe fields — no internal publication-control state,
    no raw confidence components, no debug/internal metadata.
    """

    id: str
    section_id: str
    issue_key: str
    issue_label: str
    status: str
    severity: str
    confidence_level: str | None = None
    confidence_overall: float | None = None
    affected_sections: list[str]
    policy_evidence_excerpt: str | None = None
    legal_requirement: str | None = None
    primary_legal_anchor: list[str] | None = None
    gap_note: str
    omission_statement: str | None = None
    gap_reasoning: str | None = None
    remediation_note: str
    severity_rationale: str | None = None
    citation_summary_text: str | None = None
    citations: list[CitationOut] = []

    @field_validator("issue_key")
    @classmethod
    def _issue_key_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("issue_key must not be empty")
        return v

    @field_validator("issue_label")
    @classmethod
    def _issue_label_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("issue_label must not be empty")
        return v

    @field_validator("severity")
    @classmethod
    def _severity_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("severity must not be empty")
        return v


class FindingOut(BaseModel):
    id: str
    section_id: str
    status: str
    severity: str | None
    classification: str | None = None
    finding_type: str | None = None
    publish_flag: str | None = None
    artifact_role: str | None = None
    finding_level: str | None = None
    publication_state: str | None = None
    confidence: float | None = None
    confidence_evidence: float | None = None
    confidence_applicability: float | None = None
    confidence_article_fit: float | None = None
    confidence_synthesis: float | None = None
    confidence_overall: float | None = None
    missing_from_section: str | None = None
    missing_from_document: str | None = None
    not_visible_in_excerpt: str | None = None
    obligation_under_review: str | None = None
    collection_mode: str | None = None
    applicability_status: str | None = None
    visibility_status: str | None = None
    section_vs_document_scope: str | None = None
    missing_fact_if_unresolved: str | None = None
    policy_evidence_excerpt: str | None = None
    legal_requirement: str | None = None
    gap_reasoning: str | None = None
    confidence_level: str | None = None
    assessment_type: str | None = None
    severity_rationale: str | None = None
    primary_legal_anchor: list[str] | None = None
    secondary_legal_anchors: list[str] | None = None
    document_evidence_refs: list[str] | None = None
    citation_summary_text: str | None = None
    support_complete: bool | None = None
    omission_basis: bool | None = None
    source_scope: str | None = None
    source_scope_confidence: float | None = None
    referenced_unseen_sections: list[str] | None = None
    assertion_level: str | None = None
    publication_blocked: bool | None = None
    issue_key: str | None = None
    issue_label: str | None = None
    blocker_reason: str | None = None
    missing_requirements: list[str] | None = None
    affected_sections: list[str] | None = None
    where_evidence_found: list[str] | None = None
    where_disclosure_missing: list[str] | None = None
    document_evidence: str | None = None
    legal_rule: str | None = None
    legal_analysis: str | None = None
    final_legal_outcome: str | None = None
    gap_note: str | None
    remediation_note: str | None
    citations: list[CitationOut]


class RemediationSuggestionOut(BaseModel):
    id: str
    generation_status: str
    suggested_fix_text: str | None = None


class RemediationItemOut(BaseModel):
    id: str
    audit_id: str
    finding_id: str
    issue_key: str
    issue_label: str
    severity: str
    score_impact_points: int
    order_index: int
    section_id: str | None = None
    suggestion: RemediationSuggestionOut | None = None


class RemediationStatusOut(BaseModel):
    total: int
    pending: int
    complete: int
    failed: int
    is_compliant: bool


class AuditCreate(BaseModel):
    document_id: str
    group_id: str | None = None


class AuditOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    document_id: str
    user_id: str | None = None
    document_group_id: str | None = None
    version_number: int | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None
    model_provider: str
    model_name: str
    embedding_model: str
    corpus_version: str
    compliance_score: int | None = None


class ReportOut(BaseModel):
    id: str
    status: str
    created_at: datetime


class ReportTriggerOut(BaseModel):
    report_id: str
    status: str


class ExportContractOut(BaseModel):
    report_type: str
    dataset_used: str
    export_allowed: bool
    blocker_reasons: list[str]
    counts_by_status: dict[str, int]
    finding_ids: list[str]
    document_wide_finding_ids: list[str]
    section_finding_ids: list[str]
    generated_from_audit_id: str
    generated_at: str


class FinalDecisionLedgerRowOut(BaseModel):
    canonical_issue_key: str
    scope_type: str
    scope_id: str
    scope_title: str | None = None
    issue_type: str
    issue_subtype: str
    final_status: str
    final_severity: str | None = None
    legal_anchors: list[str]
    evidence_refs: list[str]
    evidence_mode: str
    review_visible: bool
    published_visible: bool
    report_visible: bool
    export_visible: bool
    blocker_reason_codes: list[str]
    normalization_metadata: dict[str, str] | None = None


class AnalysisCitationOut(BaseModel):
    chunk_id: str
    evidence_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    article_number: str
    paragraph_ref: str | None
    article_title: str
    excerpt: str


class AnalysisItemOut(BaseModel):
    id: str
    section_id: str
    analysis_stage: str | None = None
    analysis_type: str
    issue_type: str | None = None
    status_candidate: str | None = None
    classification_candidate: str | None = None
    artifact_role: str | None = None
    finding_level_candidate: str | None = None
    publication_state_candidate: str | None = None
    analysis_outcome: str
    candidate_issue: str | None = None
    policy_evidence_excerpt: str | None = None
    legal_requirement_candidate: str | None = None
    article_candidates: list[str] | None = None
    retrieval_summary: str | None = None
    qualification_summary: str | None = None
    evidence_sufficiency: str | None = None
    applicability: str | None = None
    citation_fit_status: str | None = None
    applicability_status: str | None = None
    contradiction_status: str | None = None
    citation_fit: str | None = None
    support_role: str | None = None
    source_scope: str | None = None
    excerpt_scope_facts: str | None = None
    referenced_unseen_sections: list[str] | None = None
    suppression_reason: str | None = None
    publishability_candidate: str
    confidence: float | None = None
    confidence_evidence: float | None = None
    confidence_applicability: float | None = None
    confidence_article_fit: float | None = None
    confidence_overall: float | None = None
    finding_status: str | None = None
    finding_classification: str | None = None
    finding_severity: str | None = None
    gap_note: str | None = None
    remediation_note: str | None = None
    citations: list[AnalysisCitationOut]


class ReviewItemOut(BaseModel):
    item_kind: str
    id: str
    section_id: str
    issue_type: str | None = None
    status: str | None = None
    classification: str | None = None
    artifact_role: str | None = None
    finding_level: str | None = None
    publication_state: str | None = None
    suppression_reason: str | None = None
    completeness_map: str | None = None
    gap_note: str | None = None
    remediation_note: str | None = None
    review_group: str | None = None
    duty: str | None = None
    family: str | None = None
    triggered: bool | None = None
    final_disposition: str | None = None
    reason: str | None = None
    source_scope_dependency: str | None = None
    publication_recommendation: str | None = None
    citations: list[CitationOut] | None = None
    diagnostics_count: int | None = None


class GroupCreate(BaseModel):
    name: str


class GroupUpdate(BaseModel):
    name: str


class GroupVersionCreate(BaseModel):
    document_id: str


class GroupVersionOut(BaseModel):
    document_id: str
    audit_id: str
    version_number: int
    compliance_score: int | None = None
    created_at: datetime


class GroupOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    versions: list[GroupVersionOut]
    latest_compliance_score: int | None = None
