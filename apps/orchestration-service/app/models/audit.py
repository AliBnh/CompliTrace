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
    section_id: Mapped[str] = mapped_column(String(36), index=True)
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
    missing_from_section: Mapped[str | None] = mapped_column(String(8), nullable=True)
    missing_from_document: Mapped[str | None] = mapped_column(String(8), nullable=True)
    not_visible_in_excerpt: Mapped[str | None] = mapped_column(String(8), nullable=True)
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


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    audit: Mapped[Audit] = relationship(back_populates="reports")
