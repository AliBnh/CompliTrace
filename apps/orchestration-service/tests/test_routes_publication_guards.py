from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import _sanitize_published_text, create_report, get_findings
from app.db.base import Base
from app.models.audit import Audit


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    with SessionLocal() as db:
        yield db


def _create_audit(db: Session, *, status: str) -> Audit:
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status=status)
    db.add(audit)
    db.commit()
    return audit


def test_get_findings_blocks_publication_when_review_required(db_session: Session):
    audit = _create_audit(db_session, status="review_required")

    with pytest.raises(HTTPException) as exc:
        get_findings(audit.id, db_session)

    assert exc.value.status_code == 409
    assert "requires review" in str(exc.value.detail)


def test_create_report_blocks_generation_when_review_required(db_session: Session):
    audit = _create_audit(db_session, status="review_required")

    with pytest.raises(HTTPException) as exc:
        create_report(audit.id, db_session)

    assert exc.value.status_code == 409
    assert "reviewer resolution" in str(exc.value.detail)


def test_sanitize_published_text_strips_internal_markers():
    raw = (
        "Gap text [withheld by final publication validator] "
        "suppression_validator=final_disposition_map "
        "state_invariant_violation:blocked_publish_yes"
    )

    cleaned = _sanitize_published_text(raw)

    assert cleaned == "Gap text"
