from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.audit import Audit, Finding
from app.services.reports import generate_report_text


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
            with out_path.open("rb") as f:
                header = f.read(5)
            assert header == b"%PDF-"
    finally:
        settings.reports_dir = old_reports_dir
