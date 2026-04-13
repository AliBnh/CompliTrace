from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.audit import Audit, Finding
from app.services.audit_runner import _enforce_review_publish_invariant
from app.services.reports import build_export_contract, final_findings_dataset, generate_report_text


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return SessionLocal()


def _audit(db: Session) -> Audit:
    audit = Audit(
        id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        status="complete",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        model_provider="test",
        model_name="test",
        model_temperature=0.1,
        prompt_template_version="v1",
        embedding_model="embed",
        corpus_version="v1",
    )
    db.add(audit)
    db.commit()
    return audit


def test_review_gap_publish_always_creates_final_finding():
    with _session() as db:
        audit = _audit(db)
        disposition = {"legal_basis": {"status": "gap", "publication_recommendation": "publish"}}
        _enforce_review_publish_invariant(db, audit.id, disposition)
        rows = final_findings_dataset(db, audit.id)
        assert any(r.section_id == "systemic:missing_legal_basis" for r in rows)


def test_not_assessable_gap_is_promoted_to_publishable_substantive_finding():
    with _session() as db:
        audit = _audit(db)
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="systemic:missing_retention_period",
                status="partial",
                severity="medium",
                classification="not_assessable",
                publish_flag="no",
                publication_state="blocked",
                finding_type="systemic",
            )
        )
        db.commit()
        disposition = {"retention": {"status": "gap", "publication_recommendation": "publish"}}
        _enforce_review_publish_invariant(db, audit.id, disposition)
        row = next(r for r in final_findings_dataset(db, audit.id) if r.section_id == "systemic:missing_retention_period")
        assert row.classification in {"probable_gap", "systemic_violation"}
        assert row.publication_state == "publishable"


def test_export_and_report_use_identical_final_findings_dataset(tmp_path):
    from app.core.config import settings

    with _session() as db:
        old_reports_dir = settings.reports_dir
        settings.reports_dir = tmp_path
        try:
            audit = _audit(db)
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id="systemic:controller_processor_role_ambiguity",
                    status="gap",
                    severity="high",
                    classification="systemic_violation",
                    publish_flag="yes",
                    publication_state="publishable",
                    finding_type="systemic",
                    gap_note="Role split is unclear.",
                    remediation_note="Clearly separate controller and processor contexts.",
                )
            )
            db.commit()
            contract, export_rows, _ = build_export_contract(db, audit.id)
            report, out_path = generate_report_text(db, audit.id)
            assert report.status == "ready"
            canonical_ids = [r.id for r in final_findings_dataset(db, audit.id)]
            assert contract["finding_ids"] == sorted(canonical_ids)
            assert sorted(r.id for r in export_rows) == sorted(canonical_ids)
            payload = out_path.read_bytes().decode("latin-1", errors="ignore")
            for finding_id in canonical_ids:
                assert finding_id in payload
        finally:
            settings.reports_dir = old_reports_dir


def test_fallback_evidence_is_readable_sentence():
    with _session() as db:
        audit = _audit(db)
        disposition = {"purpose_mapping": {"status": "gap", "publication_recommendation": "publish"}}
        _enforce_review_publish_invariant(db, audit.id, disposition)
        row = next(r for r in final_findings_dataset(db, audit.id) if r.section_id == "systemic:purpose_specificity_gap")
        assert row.policy_evidence_excerpt is not None
        assert row.policy_evidence_excerpt.endswith(".")
        assert "required information" in row.policy_evidence_excerpt.lower()
