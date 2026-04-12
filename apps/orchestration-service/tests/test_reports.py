from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.audit import Audit, Finding
from app.services.clients import DocumentData
from app.services.clients import SectionData
from app.services.reports import _format_citation_label, _sanitize_user_text, _section_report_meta, generate_report_text


def test_generate_report_writes_valid_pdf(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    old_reports_dir = settings.reports_dir
    settings.reports_dir = tmp_path
    try:
        with SessionLocal() as db:
            audit = Audit(
                id=str(uuid.uuid4()),
                document_id=str(uuid.uuid4()),
                status="complete",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                model_provider="test",
                model_name="test-model",
                model_temperature=0.1,
                prompt_template_version="v1",
                embedding_model="embed",
                corpus_version="corpus-v1",
            )
            db.add(audit)
            db.flush()
            db.add(
                Finding(
                    id=str(uuid.uuid4()),
                    audit_id=audit.id,
                    section_id=str(uuid.uuid4()),
                    status="gap",
                    severity="high",
                    gap_note="Missing legal basis disclosure.",
                    remediation_note="Add Article 13(1)(c) basis statement.",
                )
            )
            db.commit()

            report, out_path = generate_report_text(db, audit.id)
            assert report.status == "ready"
            assert out_path.exists()
            payload = out_path.read_bytes()
            header = payload[:5]
            assert header == b"%PDF-"
            decoded = payload.decode("latin-1", errors="ignore")
            assert "Document title:" in decoded
            assert "Audit started at:" in decoded
            assert "Audit completed at:" in decoded
            assert "Dataset used:" in decoded
            assert "Report generation metadata" not in decoded
            assert "Embedding model:" not in decoded
    finally:
        settings.reports_dir = old_reports_dir


def test_section_report_meta_uses_human_readable_titles(monkeypatch):
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status="complete")

    class FakeIngestionClient:
        def __init__(self, _base_url: str):
            pass

        def get_document(self, _document_id: str):
            return DocumentData(
                id="doc-1",
                title="Employee Privacy Policy",
                filename="employee_privacy_policy.pdf",
                status="parsed",
                section_count=1,
            )

        def get_sections(self, _document_id: str):
            return [
                SectionData(
                    id="sec-1",
                    section_order=1,
                    section_title="Purpose and Scope",
                    content="...",
                    page_start=1,
                    page_end=1,
                )
            ]

    monkeypatch.setattr("app.services.reports.IngestionClient", FakeIngestionClient)
    title, labels = _section_report_meta(audit)

    assert title == "Employee Privacy Policy"
    assert labels["sec-1"].label == "Section 1: Purpose and Scope"
    assert labels["sec-1"].page_range == "Page 1"


def test_format_citation_label_is_user_friendly():
    assert _format_citation_label("13", "Information to be provided", "1") == (
        "GDPR Article 13 - Information to be provided (Paragraph 1)"
    )


def test_sanitize_user_text_removes_chunk_ids():
    text = "Cite: gdpr-art-13-p-1-sp-a-c-seg-1-a2bba5c6f1c4 and chunk_id=gdpr-art-44-p-null-seg-1-f240f12f1cf8."
    cleaned = _sanitize_user_text(text)
    assert cleaned is not None
    assert "gdpr-art-" not in cleaned
    assert "GDPR evidence reference" in cleaned


def test_sanitize_user_text_strips_diagnostics():
    text = "Substantive finding withheld. Diagnostic: citation mismatch across anchors."
    cleaned = _sanitize_user_text(text)
    assert cleaned is not None
    assert "Diagnostic:" not in cleaned


def test_report_pdf_omits_internal_debug_terms(tmp_path: Path):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    old_reports_dir = settings.reports_dir
    settings.reports_dir = tmp_path
    try:
        with SessionLocal() as db:
            audit = Audit(
                id=str(uuid.uuid4()),
                document_id=str(uuid.uuid4()),
                status="complete",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                model_provider="internal-provider",
                model_name="internal-model",
                model_temperature=0.1,
                prompt_template_version="v1",
                embedding_model="internal-embed",
                corpus_version="corpus-v1",
            )
            db.add(audit)
            db.flush()
            db.add(
                Finding(
                    id=str(uuid.uuid4()),
                    audit_id=audit.id,
                    section_id="systemic:missing_legal_basis",
                    status="gap",
                    severity=None,
                    gap_note="withheld by final publication validator",
                    remediation_note="Add legal basis disclosure.",
                    publication_state="blocked",
                )
            )
            db.commit()
            _, out_path = generate_report_text(db, audit.id)
            decoded = out_path.read_bytes().decode("latin-1", errors="ignore").lower()
            assert "validator" not in decoded
            assert "embedding model" not in decoded
            assert "corpus version" not in decoded
            assert "dataset used: review findings" in decoded
    finally:
        settings.reports_dir = old_reports_dir
