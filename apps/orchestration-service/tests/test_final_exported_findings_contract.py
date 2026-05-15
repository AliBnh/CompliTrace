import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.audit import Audit, Finding, FindingCitation
from app.services.reports import (
    build_export_contract,
    canonical_published_findings,
    final_exported_findings,
    generate_report_text,
)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    return SessionLocal()


def _audit(db: Session) -> Audit:
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), user_id="test-user", status="complete")
    db.add(audit)
    db.flush()
    return audit


def test_final_exported_findings_keeps_review_publishable_rows_as_single_source_of_truth():
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
            gap_note="The notice does not state the lawful basis for processing.",
            remediation_note="Add a lawful basis statement for each purpose.",
            policy_evidence_excerpt="We collect and process personal data to provide the service.",
            primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        )
        db.add(row)
        db.flush()
        db.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="chunk-lb",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Lawful basis",
                excerpt="We collect and process personal data to provide the service.",
            )
        )
        db.commit()
        exported = final_exported_findings(db, audit.id)
        assert len(exported) == 1
        assert exported[0].classification == "probable_gap"


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


def test_final_exported_findings_replaces_unreadable_evidence_with_readable_fallback():
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
        # First citation has clean excerpt — canonical function finds it and uses as fallback.
        db.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="sec:1",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Information to be provided",
                excerpt="We process personal data for service delivery and legal compliance.",
            )
        )
        db.commit()

        exported = final_exported_findings(db, audit.id)
        assert len(exported) == 1
        assert exported[0].policy_evidence_excerpt.startswith("Based on the reviewed notice:")


def test_final_exported_findings_requires_at_least_one_citation():
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
            policy_evidence_excerpt="We process personal data for service operations.",
            document_evidence_refs='["evi:policy:sec-1"]',
            primary_legal_anchor='["GDPR Article 13(1)(c)"]',
        )
        db.add(row)
        db.flush()
        # canonical_published_findings requires at least one real citation
        db.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="chunk-lb-2",
                article_number="13",
                paragraph_ref="1(c)",
                article_title="Legal basis",
                excerpt="We process personal data for service operations.",
            )
        )
        db.commit()
        exported = final_exported_findings(db, audit.id)
        assert len(exported) == 1
        assert exported[0].section_id == "sec-1"


def test_non_compliant_export_still_generates_downloadable_report_when_citations_exist():
    with _session() as db:
        audit = _audit(db)
        row = Finding(
            audit_id=audit.id,
            section_id="sec-1",
            status="gap",
            severity="high",
            publication_state="publishable",
            classification="probable_gap",
            legal_requirement="GDPR Article 13(1)(f)",
            gap_note="Transfer safeguards are missing.",
            remediation_note="Add transfer safeguard details.",
            policy_evidence_excerpt="Transfers are referenced but safeguards are absent.",
            primary_legal_anchor='["GDPR Article 13(1)(f)"]',
        )
        db.add(row)
        db.flush()
        db.add(
            FindingCitation(
                finding_id=row.id,
                chunk_id="sec:transfer",
                article_number="13",
                paragraph_ref="1(f)",
                article_title="Information to be provided",
                excerpt="Transfers are referenced but safeguards are absent.",
            )
        )
        db.commit()

        contract, rows, _ = build_export_contract(db, audit.id)
        assert contract["dataset_used"] == "published"
        assert rows

        previous_reports_dir = settings.reports_dir
        with TemporaryDirectory() as tmp_dir:
            settings.reports_dir = Path(tmp_dir)
            report, out_path = generate_report_text(db, audit.id)
            assert report.status == "ready"
            assert Path(out_path).exists()
        settings.reports_dir = previous_reports_dir
