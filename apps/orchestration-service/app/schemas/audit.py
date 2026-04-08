from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CitationOut(BaseModel):
    chunk_id: str
    evidence_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    article_number: str
    paragraph_ref: str | None
    article_title: str
    excerpt: str


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
    gap_note: str | None
    remediation_note: str | None
    citations: list[CitationOut]


class AuditCreate(BaseModel):
    document_id: str


class AuditOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    document_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    model_provider: str
    model_name: str
    embedding_model: str
    corpus_version: str


class ReportOut(BaseModel):
    id: str
    status: str
    created_at: datetime


class ReportTriggerOut(BaseModel):
    report_id: str
    status: str


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
