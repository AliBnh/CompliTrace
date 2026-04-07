import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    model_provider: Mapped[str] = mapped_column(String(64), default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    model_temperature: Mapped[float] = mapped_column(Float, default=0.1)
    prompt_template_version: Mapped[str] = mapped_column(String(32), default="")
    embedding_model: Mapped[str] = mapped_column(String(128), default="")
    corpus_version: Mapped[str] = mapped_column(String(64), default="")

    findings: Mapped[list["Finding"]] = relationship(back_populates="audit", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="audit", cascade="all, delete-orphan")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_evidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_applicability: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_article_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_synthesis: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    finding_type: Mapped[str] = mapped_column(String(32), default="local")
    publish_flag: Mapped[str] = mapped_column(String(8), default="yes")
    artifact_role: Mapped[str] = mapped_column(String(32), default="publishable_finding")
    finding_level: Mapped[str] = mapped_column(String(16), default="local")
    publication_state: Mapped[str] = mapped_column(String(16), default="publishable")
    missing_from_section: Mapped[str | None] = mapped_column(String(8), nullable=True)
    missing_from_document: Mapped[str | None] = mapped_column(String(8), nullable=True)
    not_visible_in_excerpt: Mapped[str | None] = mapped_column(String(8), nullable=True)
    obligation_under_review: Mapped[str | None] = mapped_column(String(64), nullable=True)
    collection_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    applicability_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    visibility_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    section_vs_document_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    missing_fact_if_unresolved: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    gap_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assessment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    severity_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_legal_anchor: Mapped[str | None] = mapped_column(Text, nullable=True)
    secondary_legal_anchors: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_evidence_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    citation_summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_complete: Mapped[str | None] = mapped_column(String(8), nullable=True)
    omission_basis: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_scope_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    referenced_unseen_sections: Mapped[str | None] = mapped_column(Text, nullable=True)
    assertion_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gap_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    audit: Mapped[Audit] = relationship(back_populates="findings")
    citations: Mapped[list["FindingCitation"]] = relationship(back_populates="finding", cascade="all, delete-orphan")


class FindingCitation(Base):
    __tablename__ = "finding_citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id: Mapped[str] = mapped_column(String(36), ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(128))
    article_number: Mapped[str] = mapped_column(String(32))
    paragraph_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    article_title: Mapped[str] = mapped_column(String(512), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")

    finding: Mapped[Finding] = relationship(back_populates="citations")


class AuditAnalysisItem(Base):
    __tablename__ = "audit_analysis_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(128), index=True)
    analysis_stage: Mapped[str] = mapped_column(String(64), default="section_processing")
    analysis_type: Mapped[str] = mapped_column(String(64), default="provisional_local")
    issue_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status_candidate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    classification_candidate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_role: Mapped[str] = mapped_column(String(32), default="analysis_candidate")
    finding_level_candidate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    publication_state_candidate: Mapped[str | None] = mapped_column(String(16), nullable=True)
    analysis_outcome: Mapped[str] = mapped_column(String(64), default="candidate_gap")
    candidate_issue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    policy_evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_requirement_candidate: Mapped[str | None] = mapped_column(Text, nullable=True)
    article_candidates: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieval_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_sufficiency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    applicability: Mapped[str | None] = mapped_column(String(64), nullable=True)
    citation_fit_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    applicability_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contradiction_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    citation_fit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    support_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    excerpt_scope_facts: Mapped[str | None] = mapped_column(Text, nullable=True)
    referenced_unseen_sections: Mapped[str | None] = mapped_column(Text, nullable=True)
    suppression_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    publishability_candidate: Mapped[str] = mapped_column(String(16), default="unknown")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_evidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_applicability: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_article_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    finding_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finding_classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finding_severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gap_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    citations: Mapped[list["AnalysisCitation"]] = relationship(back_populates="analysis_item", cascade="all, delete-orphan")


class AnalysisCitation(Base):
    __tablename__ = "analysis_citations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_analysis_items.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str] = mapped_column(String(128))
    article_number: Mapped[str] = mapped_column(String(32))
    paragraph_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    article_title: Mapped[str] = mapped_column(String(512), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")

    analysis_item: Mapped[AuditAnalysisItem] = relationship(back_populates="citations")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    audit: Mapped[Audit] = relationship(back_populates="reports")
