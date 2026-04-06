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
