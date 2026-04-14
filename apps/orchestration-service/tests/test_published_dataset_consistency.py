from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import get_findings
from app.db.base import Base
from app.models.audit import Audit, Finding
from app.services.reports import build_export_contract, final_findings_dataset


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return SessionLocal()


def test_get_findings_uses_canonical_export_dataset():
    with _db() as db:
        audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status="complete")
        db.add(audit)
        db.flush()
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="systemic:missing_transfer_notice",
                status="gap",
                severity="high",
                publication_state="publishable",
                finding_type="systemic",
                legal_requirement="GDPR Art 13(1)(f)",
                gap_note="Transfer safeguards are not disclosed.",
                remediation_note="Add transfer safeguards.",
            )
        )
        db.commit()

        rows = get_findings(audit.id, db)
        canonical = final_findings_dataset(db, audit.id)
        contract, export_rows, _ = build_export_contract(db, audit.id)

        assert len(rows) == len(canonical) == len(export_rows) == contract["counts_by_status"]["total"]
        assert sorted(r.id for r in rows) == sorted(r.id for r in canonical)


def test_invalid_publishable_rows_are_not_exported_or_displayed():
    with _db() as db:
        audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status="complete")
        db.add(audit)
        db.flush()
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="systemic:missing_legal_basis",
                status="gap",
                severity="high",
                publication_state="publishable",
                finding_type="systemic",
                legal_requirement=None,
                gap_note=".",
                remediation_note="Fix legal basis disclosure.",
            )
        )
        db.commit()

        assert final_findings_dataset(db, audit.id) == []
        assert get_findings(audit.id, db) == []
