from __future__ import annotations

import uuid

from app.api.routes import get_findings
from app.db.base import Base
from app.models.audit import Audit, Finding, FindingCitation
from app.services.reports import build_export_contract, canonical_published_findings, final_findings_dataset
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return SessionLocal()


def _make_canonical_finding(db: Session, audit_id: str, section_id: str) -> Finding:
    row = Finding(
        audit_id=audit_id,
        section_id=section_id,
        status="gap",
        severity="high",
        publication_state="publishable",
        finding_type="systemic",
        classification="systemic_violation",
        legal_requirement="GDPR Article 13(1)(f)",
        gap_note="Transfer safeguards are not disclosed.",
        remediation_note="Add transfer safeguard details.",
        policy_evidence_excerpt="Data may be transferred outside the EEA.",
        primary_legal_anchor='["GDPR Article 13(1)(f)"]',
    )
    db.add(row)
    db.flush()
    db.add(
        FindingCitation(
            finding_id=row.id,
            chunk_id="chunk-transfer",
            article_number="13",
            paragraph_ref="1(f)",
            article_title="Transfer disclosure",
            excerpt="Data may be transferred outside the EEA.",
        )
    )
    return row


def test_get_findings_uses_canonical_export_dataset():
    with _db() as db:
        audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), user_id="test-user", status="complete")
        db.add(audit)
        db.flush()
        _make_canonical_finding(db, audit.id, "systemic:missing_transfer_notice")
        db.commit()

        rows = get_findings(audit.id, "test-user", db)
        canonical = canonical_published_findings(db, audit.id)
        contract, export_rows, _ = build_export_contract(db, audit.id)

        assert len(rows) >= 1
        assert len(rows) == len(canonical) == len(export_rows) == contract["counts_by_status"]["total"]
        assert sorted(r.id for r in rows) == sorted(r.id for r in canonical)


def test_invalid_publishable_rows_are_not_exported_or_displayed():
    with _db() as db:
        audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), user_id="test-user", status="complete")
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
        assert get_findings(audit.id, "test-user", db) == []
