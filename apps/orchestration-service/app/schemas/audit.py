from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CitationOut(BaseModel):
    chunk_id: str
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
