import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.audit import Audit, Finding, FindingCitation
from app.services.reports import final_exported_findings


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return SessionLocal()


def _audit(db: Session) -> Audit:
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status="complete")
    db.add(audit)
    db.flush()
    return audit


def test_final_exported_findings_blocks_fallback_and_debug_rows():
    with _session() as db:
        audit = _audit(db)
        db.add(
            Finding(
                audit_id=audit.id,
                section_id="sec-1",
                status="gap",
                severity="high",
                publication_state="publishable",
                classification="fallback_projection",
                legal_requirement="GDPR Article 13(1)(c)",
                gap_note="additional context required",
                remediation_note="Add legal basis disclosure",
                policy_evidence_excerpt="Legal basis appears in text",
            )
        )
        db.commit()
        assert final_exported_findings(db, audit.id) == []


def test_final_exported_findings_requires_anchor_and_citation_chain():
    with _session() as db:
        audit = _audit(db)
        row = Finding(
            audit_id=audit.id,
            section_id="sec-1",
            status="gap",
            severity="high",
            publication_state="publishable",
            classification="probable_gap",
            legal_requirement="GDPR Article 13(1)(c)",
            gap_note="Legal basis wording is missing.",
            remediation_note="Add lawful basis for this processing purpose.",
            policy_evidence_excerpt="We collect data to provide the service.",
            document_evidence_refs='["evi:policy:sec-1"]',
            primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        )
        db.add(row)
        db.flush()
        db.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="sec:1",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Information to be provided",
                excerpt="We collect data to provide the service.",
            )
        )
        db.commit()

        exported = final_exported_findings(db, audit.id)
        assert len(exported) == 1
        assert exported[0].section_id == "sec-1"


def test_final_exported_findings_rejects_malformed_internal_evidence():
    with _session() as db:
        audit = _audit(db)
        row = Finding(
            audit_id=audit.id,
            section_id="sec-1",
            status="gap",
            severity="high",
            publication_state="publishable",
            classification="probable_gap",
            legal_requirement="GDPR Article 13(1)(c)",
            gap_note="Missing lawful basis statement.",
            remediation_note="Add lawful basis statement.",
            policy_evidence_excerpt=".",
            document_evidence_refs='["evi:policy:sec-1"]',
            primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        )
        db.add(row)
        db.flush()
        db.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="sec:1",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Information to be provided",
                excerpt="disallowed by strict",
            )
        )
        db.commit()

        assert final_exported_findings(db, audit.id) == []
