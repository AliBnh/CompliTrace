"""
Tests proving the canonical published findings contract:

  1. API /findings count == export-contract count == canonical_published_findings count
  2. Report generation uses the same dataset as canonical_published_findings
  3. Non-publishable artifacts (support_only, internal_only, candidate_gap, etc.)
     never appear in canonical output
  4. Banned / internal / debug tokens are excluded from canonical output
  5. PDF generation uses the canonical dataset
  6. canonical_published_findings is the sole source used by every output path
"""

from __future__ import annotations

import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from app.api.routes import get_findings
from app.core.config import settings
from app.db.base import Base
from app.models.audit import Audit, Finding, FindingCitation
from app.services.reports import (
    _is_clean_human_text,
    build_export_contract,
    canonical_published_findings,
    generate_report_text,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


def _audit(db: Session, status: str = "complete") -> Audit:
    audit = Audit(id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), user_id="test-user", status=status)
    db.add(audit)
    db.flush()
    return audit


def _canonical_finding(
    db: Session,
    audit_id: str,
    section_id: str = "systemic:missing_legal_basis",
    *,
    gap_note: str = "The notice does not state the lawful basis for processing.",
    remediation_note: str = "Add a lawful basis statement for each processing purpose.",
    policy_evidence_excerpt: str = "We collect and process personal data to provide the service.",
    anchor: str = '["GDPR Article 13(1)(c)"]',
    article_number: str = "13",
    paragraph_ref: str = "1(c)",
    chunk_excerpt: str = "We collect and process personal data to provide the service.",
) -> Finding:
    row = Finding(
        audit_id=audit_id,
        section_id=section_id,
        status="gap",
        severity="high",
        publication_state="publishable",
        finding_type="systemic",
        classification="systemic_violation",
        legal_requirement=f"GDPR Article {article_number}({paragraph_ref})",
        gap_note=gap_note,
        remediation_note=remediation_note,
        policy_evidence_excerpt=policy_evidence_excerpt,
        primary_legal_anchor=anchor,
    )
    db.add(row)
    db.flush()
    db.add(
        FindingCitation(
            finding_id=row.id,
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            article_number=article_number,
            paragraph_ref=paragraph_ref,
            article_title="Transparency obligation",
            excerpt=chunk_excerpt,
        )
    )
    return row


# ---------------------------------------------------------------------------
# Contract: API == export-contract == canonical_published_findings
# ---------------------------------------------------------------------------


class TestPublishedCountContract:
    def test_api_count_equals_export_contract_count(self):
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id, "systemic:missing_legal_basis")
            _canonical_finding(
                db,
                audit.id,
                "systemic:missing_retention_period",
                anchor='["GDPR Article 13(2)(a)"]',
                article_number="13",
                paragraph_ref="2(a)",
                gap_note="The notice does not state retention periods.",
                remediation_note="Add retention criteria.",
                chunk_excerpt="Data is kept for service delivery.",
            )
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)
            contract, export_rows, _ = build_export_contract(db, audit.id)

            assert len(api_rows) >= 1
            assert len(api_rows) == len(canonical), (
                f"API returned {len(api_rows)} findings but canonical set has {len(canonical)}"
            )
            assert len(export_rows) == contract["counts_by_status"]["total"], (
                "export-contract row list does not match its own total count"
            )
            assert len(canonical) == len(export_rows), (
                f"canonical_published_findings ({len(canonical)}) != export_contract rows ({len(export_rows)})"
            )

    def test_api_finding_ids_match_canonical_ids(self):
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id)
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)

            assert sorted(r.id for r in api_rows) == sorted(r.id for r in canonical)

    def test_export_contract_dataset_matches_canonical(self):
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id)
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            _, export_rows, _ = build_export_contract(db, audit.id)

            assert sorted(r.id for r in canonical) == sorted(r.id for r in export_rows)


# ---------------------------------------------------------------------------
# Contract: non-publishable artifacts never appear in output
# ---------------------------------------------------------------------------


class TestNonPublishableExclusion:
    @pytest.mark.parametrize(
        "artifact_role,publication_state",
        [
            ("support_only", "internal_only"),
            ("support_only", "publishable"),  # wrong role even if state looks ok
            ("publishable_finding", "internal_only"),  # wrong state even if role looks ok
            ("publishable_finding", "blocked"),
        ],
    )
    def test_non_canonical_rows_excluded(self, artifact_role, publication_state):
        with _db() as db:
            audit = _audit(db)
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id="systemic:missing_legal_basis",
                    status="gap",
                    severity="high",
                    artifact_role=artifact_role,
                    publication_state=publication_state,
                    gap_note="Legal basis is missing.",
                    remediation_note="Add legal basis.",
                    policy_evidence_excerpt="We process data.",
                    primary_legal_anchor='["GDPR Article 13(1)(c)"]',
                )
            )
            db.commit()
            assert canonical_published_findings(db, audit.id) == []

    def test_ledger_row_excluded(self):
        with _db() as db:
            audit = _audit(db)
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id="ledger:missing_legal_basis",
                    status="gap",
                    severity="high",
                    publication_state="publishable",
                    gap_note="Ledger entry.",
                    remediation_note="Fix it.",
                    policy_evidence_excerpt="We process data.",
                    primary_legal_anchor='["GDPR Article 13(1)(c)"]',
                )
            )
            db.commit()
            assert canonical_published_findings(db, audit.id) == []

    def test_row_without_citation_excluded(self):
        with _db() as db:
            audit = _audit(db)
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id="systemic:missing_legal_basis",
                    status="gap",
                    severity="high",
                    publication_state="publishable",
                    classification="probable_gap",
                    legal_requirement="GDPR Article 13(1)(c)",
                    gap_note="The notice does not state the lawful basis.",
                    remediation_note="Add lawful basis statement.",
                    policy_evidence_excerpt="We collect data.",
                    primary_legal_anchor='["GDPR Article 13(1)(c)"]',
                )
            )
            db.commit()
            # canonical requires at least one real citation
            assert canonical_published_findings(db, audit.id) == []

    def test_row_without_anchor_excluded(self):
        with _db() as db:
            audit = _audit(db)
            row = Finding(
                audit_id=audit.id,
                section_id="systemic:missing_legal_basis",
                status="gap",
                severity="high",
                publication_state="publishable",
                classification="probable_gap",
                gap_note="The notice does not state the lawful basis.",
                remediation_note="Add lawful basis statement.",
                policy_evidence_excerpt="We collect data.",
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id="chunk-x",
                    article_number="13",
                    paragraph_ref="1(c)",
                    article_title="Legal basis",
                    excerpt="We collect data.",
                )
            )
            db.commit()
            # no primary_legal_anchor and no GDPR article in legal_requirement
            assert canonical_published_findings(db, audit.id) == []


# ---------------------------------------------------------------------------
# Contract: banned / debug tokens never appear in canonical output
# ---------------------------------------------------------------------------


class TestBannedTokenExclusion:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("gap_note", "support_only classification finding"),
            ("gap_note", "internal_only diagnostic row"),
            ("gap_note", "candidate_gap item not promoted"),
            ("gap_note", "not_assessable from reviewed excerpt"),
            ("gap_note", "post_reviewer_snapshot entry"),
            ("remediation_note", "provisional_local finding suppressed"),
            ("gap_note", "additional context required for assessment"),
            ("gap_note", "."),
            ("gap_note", "validator matched internal rule"),
        ],
    )
    def test_banned_text_in_field_excludes_row(self, field, value):
        with _db() as db:
            audit = _audit(db)
            kwargs = {
                "gap_note": "The notice is missing required disclosure.",
                "remediation_note": "Add the required disclosure.",
            }
            kwargs[field] = value
            row = Finding(
                audit_id=audit.id,
                section_id="systemic:missing_legal_basis",
                status="gap",
                severity="high",
                publication_state="publishable",
                classification="probable_gap",
                legal_requirement="GDPR Article 13(1)(c)",
                policy_evidence_excerpt="We collect data for service delivery.",
                primary_legal_anchor='["GDPR Article 13(1)(c)"]',
                **kwargs,
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="1(c)",
                    article_title="Legal basis",
                    excerpt="We collect data for service delivery.",
                )
            )
            db.commit()
            assert canonical_published_findings(db, audit.id) == [], (
                f"Row with banned text '{value}' in '{field}' should be excluded"
            )


# ---------------------------------------------------------------------------
# Contract: report generation uses canonical dataset
# ---------------------------------------------------------------------------


class TestReportUsesCanonicalDataset:
    def test_pdf_generation_uses_canonical_published_findings(self):
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id)
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            _, export_rows, _ = build_export_contract(db, audit.id)

            assert sorted(r.id for r in canonical) == sorted(r.id for r in export_rows), (
                "build_export_contract must use canonical_published_findings dataset"
            )

    def test_zero_findings_audit_produces_zero_report(self):
        with _db() as db:
            audit = _audit(db)
            # Add an internal-only finding that should NOT appear in report
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id="systemic:missing_legal_basis",
                    status="gap",
                    severity="high",
                    artifact_role="support_only",
                    publication_state="internal_only",
                    gap_note="internal only",
                    remediation_note="n/a",
                )
            )
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            contract, export_rows, _ = build_export_contract(db, audit.id)

            assert canonical == []
            assert export_rows == []
            assert contract["dataset_used"] == "zero"

    def test_full_report_pdf_generated_from_canonical_set(self):
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id)
            db.commit()

            prev_dir = settings.reports_dir
            with TemporaryDirectory() as tmp:
                settings.reports_dir = Path(tmp)
                try:
                    report, out_path = generate_report_text(db, audit.id)
                    assert report.status == "ready"
                    assert Path(out_path).exists()
                    # Verify PDF is non-trivially sized (real content, not empty shell)
                    assert Path(out_path).stat().st_size > 500
                finally:
                    settings.reports_dir = prev_dir


# ---------------------------------------------------------------------------
# Contract: _is_clean_human_text does not false-positive on legitimate words
# ---------------------------------------------------------------------------


class TestIsCleanHumanText:
    """Regression tests for _is_clean_human_text false-positive fix.

    The word 'internal' appears legitimately in GDPR notices (e.g., 'internal
    policies', 'internal governance'). Blocking on the bare word 'internal' was
    a bug that caused findings with policy_evidence_excerpt containing 'internal
    policies' to be silently excluded from the published output.

    The fix changed the debug token from 'internal' to 'internal_only'.
    """

    def test_internal_policies_phrase_is_clean(self):
        text = (
            "6.2 Safeguards such as contractual clauses and internal policies are "
            "implemented where practical; however, the level of protection may vary."
        )
        assert _is_clean_human_text(text), "Legitimate GDPR text containing 'internal policies' must not be flagged"

    def test_internal_governance_phrase_is_clean(self):
        assert _is_clean_human_text(
            "The company maintains internal governance structures including compliance reviews."
        )

    def test_bare_internal_word_is_clean(self):
        # "internal" alone must no longer block clean text (fix for false-positive
        # on 'internal policies').  internal_only is caught earlier by the raw
        # BANNED_TOKENS_LOWER scan in canonical_published_findings, not here.
        assert _is_clean_human_text("internal policies are implemented where practical")

    def test_internal_only_blocked_in_field_excludes_finding(self):
        with _db() as db:
            audit = _audit(db)
            row = Finding(
                audit_id=audit.id,
                section_id="systemic:missing_legal_basis",
                status="gap",
                severity="high",
                publication_state="publishable",
                classification="probable_gap",
                legal_requirement="GDPR Article 13(1)(c)",
                gap_note="The policy_evidence_excerpt contains internal_only debug text.",
                remediation_note="Fix the disclosure.",
                policy_evidence_excerpt="We process data. [internal_only]",
                primary_legal_anchor='["GDPR Article 13(1)(c)"]',
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="1(c)",
                    article_title="Legal basis",
                    excerpt="We process data.",
                )
            )
            db.commit()
            assert canonical_published_findings(db, audit.id) == []

    def test_finding_with_internal_policies_in_evidence_is_published(self):
        """Regression: finding blocked by 'internal' false-positive is now published."""
        with _db() as db:
            audit = _audit(db)
            row = Finding(
                audit_id=audit.id,
                section_id="sec-transfers",
                status="gap",
                severity="high",
                publication_state="publishable",
                artifact_role="publishable_finding",
                classification="clear_non_compliance",
                legal_requirement="GDPR Art. 13(1)(f)",
                gap_note="The notice does not identify transfer mechanisms for data sent outside the EEA.",
                remediation_note="Disclose whether third-country transfers occur and identify the safeguard.",
                policy_evidence_excerpt=(
                    "Safeguards such as contractual clauses and internal policies are implemented where practical."
                ),
                primary_legal_anchor='["GDPR Art. 13(1)(f)"]',
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="1(f)",
                    article_title="Transfer safeguards",
                    excerpt="Safeguards such as contractual clauses and internal policies are implemented.",
                )
            )
            db.commit()
            results = canonical_published_findings(db, audit.id)
            assert len(results) == 1, "Finding with 'internal policies' in evidence must reach canonical output"


# ---------------------------------------------------------------------------
# Contract: review_required audit blocks all published output
# ---------------------------------------------------------------------------


class TestReviewRequiredBlocksPublication:
    def test_review_required_blocks_api_endpoint(self):
        from fastapi import HTTPException

        with _db() as db:
            audit = _audit(db, status="review_required")
            _canonical_finding(db, audit.id)
            db.commit()

            import pytest as pt

            with pt.raises(HTTPException) as exc_info:
                get_findings(audit.id, "test-user", db)
            assert exc_info.value.status_code == 409

    def test_complete_audit_returns_canonical_findings(self):
        with _db() as db:
            audit = _audit(db, status="complete")
            _canonical_finding(db, audit.id)
            db.commit()

            rows = get_findings(audit.id, "test-user", db)
            assert len(rows) >= 1
            for r in rows:
                # artifact_role and publication_state are intentionally nullified by
                # _to_audit_ready_view before the API response is returned.
                assert r.issue_key is not None
                assert r.issue_label is not None
                assert r.severity is not None
                assert r.status is not None


# ---------------------------------------------------------------------------
# Contract: published API count == report count (no rows silently dropped)
# ---------------------------------------------------------------------------

_CANONICAL_ISSUE_TAXONOMY_KEYS = frozenset(
    {
        "missing_legal_basis",
        "missing_rights_notice",
        "missing_complaint_right",
        "missing_retention_period",
        "missing_transfer_notice",
        "profiling_disclosure_gap",
        "cookie_disclosure_gap",
        "missing_controller_contact",
        "missing_controller_identity",
        "purpose_specificity_gap",
        "recipients_disclosure_gap",
        "controller_processor_role_ambiguity",
        "invalid_consent_or_legal_basis",
        "cookies_tracking_consent_gap",
        "article14_source_transparency_gap",
        "article_14_indirect_collection_gap",
        "special_category_basis_unclear",
        "dpo_contact_gap",
        "lawful_basis_and_consent",
    }
)


def _retention_finding(db: Session, audit_id: str) -> Finding:
    """Local section finding whose issue_key must be derived from anchor 13(2)(a)."""
    row = Finding(
        audit_id=audit_id,
        section_id="sec-retention-section",
        status="gap",
        severity="medium",
        publication_state="publishable",
        artifact_role="publishable_finding",
        classification="probable_gap",
        legal_requirement="GDPR Article 13(2)(a)",
        gap_note="The notice does not state how long personal data is kept.",
        remediation_note="Add a retention period or objective retention criteria.",
        policy_evidence_excerpt="We keep your data for service delivery purposes.",
        primary_legal_anchor='["GDPR Article 13(2)(a)"]',
    )
    db.add(row)
    db.flush()
    db.add(
        FindingCitation(
            finding_id=row.id,
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            article_number="13",
            paragraph_ref="2(a)",
            article_title="Retention period",
            excerpt="We keep your data for service delivery purposes.",
        )
    )
    return row


def _rights_finding(db: Session, audit_id: str) -> Finding:
    """Local section finding whose issue_key must be derived from anchor 13(2)(b)."""
    row = Finding(
        audit_id=audit_id,
        section_id="sec-rights-section",
        status="gap",
        severity="high",
        publication_state="publishable",
        artifact_role="publishable_finding",
        classification="probable_gap",
        legal_requirement="GDPR Article 13(2)(b)",
        gap_note="The notice does not explain data subject rights.",
        remediation_note="Add a complete rights section.",
        policy_evidence_excerpt="Your privacy matters to us.",
        primary_legal_anchor='["GDPR Article 13(2)(b)"]',
    )
    db.add(row)
    db.flush()
    db.add(
        FindingCitation(
            finding_id=row.id,
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            article_number="13",
            paragraph_ref="2(b)",
            article_title="Right of access",
            excerpt="Your privacy matters to us.",
        )
    )
    return row


class TestPublishedAPIContractEquality:
    """
    Published API count MUST equal canonical_published_findings count for every
    audit — no rows may be silently dropped between the two.  This mirrors the
    pp_NonCompliant.pdf / pp_Compliant.pdf acceptance checks described in the
    published-findings contract spec.
    """

    def test_api_count_equals_canonical_for_retention_anchor(self):
        """Retention findings (anchor 13(2)(a)) must not be dropped by the API."""
        with _db() as db:
            audit = _audit(db)
            _retention_finding(db, audit.id)
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)

            assert len(api_rows) == len(canonical), (
                f"API returned {len(api_rows)} but canonical set has {len(canonical)} "
                "— retention-anchor row was silently dropped"
            )
            assert any(r.issue_key == "missing_retention_period" for r in api_rows), (
                "missing_retention_period not found in API response"
            )

    def test_api_count_equals_canonical_for_rights_anchor(self):
        """Rights findings (anchor 13(2)(b)) must not be dropped by the API."""
        with _db() as db:
            audit = _audit(db)
            _rights_finding(db, audit.id)
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)

            assert len(api_rows) == len(canonical), (
                f"API returned {len(api_rows)} but canonical set has {len(canonical)} "
                "— rights-anchor row was silently dropped"
            )
            assert any(r.issue_key == "missing_rights_notice" for r in api_rows)

    def test_noncompliant_doc_api_count_equals_report_count(self):
        """
        Simulates pp_NonCompliant.pdf: multiple published findings.
        API count must equal export-contract total (= report count).
        """
        with _db() as db:
            audit = _audit(db)
            # Systemic findings (section_id encodes issue key)
            _canonical_finding(db, audit.id, "systemic:missing_legal_basis")
            _canonical_finding(
                db,
                audit.id,
                "systemic:missing_retention_period",
                anchor='["GDPR Article 13(2)(a)"]',
                article_number="13",
                paragraph_ref="2(a)",
                gap_note="No retention period is stated.",
                remediation_note="Add retention criteria.",
                chunk_excerpt="Data kept for service delivery.",
            )
            _canonical_finding(
                db,
                audit.id,
                "systemic:missing_rights_notice",
                anchor='["GDPR Article 13(2)(b)"]',
                article_number="13",
                paragraph_ref="2(b)",
                gap_note="Rights are not fully described.",
                remediation_note="Add a complete rights section.",
                chunk_excerpt="Your rights under GDPR.",
            )
            # Local finding with retention anchor
            _retention_finding(db, audit.id)
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)
            contract, export_rows, _ = build_export_contract(db, audit.id)

            assert len(api_rows) >= 1, "non-compliant doc must have published findings"
            assert len(api_rows) == len(canonical), f"API {len(api_rows)} != canonical {len(canonical)}"
            assert len(api_rows) == contract["counts_by_status"]["total"], (
                f"API count {len(api_rows)} != report count {contract['counts_by_status']['total']}"
            )

    def test_compliant_doc_api_count_equals_report_count_zero(self):
        """Simulates pp_Compliant.pdf: zero published findings everywhere."""
        with _db() as db:
            audit = _audit(db)
            # Add only internal-only findings (should never appear in published output)
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id="systemic:missing_legal_basis",
                    status="gap",
                    severity="high",
                    artifact_role="support_only",
                    publication_state="internal_only",
                    gap_note="All obligations satisfied.",
                    remediation_note="n/a",
                )
            )
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)
            contract, export_rows, _ = build_export_contract(db, audit.id)

            assert len(api_rows) == 0, "compliant doc must have zero published findings in API"
            assert len(canonical) == 0
            assert contract["counts_by_status"]["total"] == 0, (
                f"report count should be 0 for compliant doc, got {contract['counts_by_status']['total']}"
            )
            assert contract["dataset_used"] == "zero"

    def test_no_diagnostic_rows_in_published_api(self):
        """Rows bearing diagnostic suppression notes must not appear in API output."""
        with _db() as db:
            audit = _audit(db)
            # Row that looks publishable except for the diagnostic gap_note.
            row = Finding(
                audit_id=audit.id,
                section_id="sec-local-no-anchor",
                status="gap",
                severity="high",
                publication_state="publishable",
                artifact_role="publishable_finding",
                classification="probable_gap",
                legal_requirement="GDPR Article 13(1)(c)",
                gap_note=(
                    "Local finding suppressed: required GDPR article anchor is absent. "
                    "Finding classified as internal diagnostic only."
                ),
                remediation_note="Fix the disclosure.",
                policy_evidence_excerpt="We process data.",
                primary_legal_anchor='["GDPR Article 13(1)(c)"]',
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="1(c)",
                    article_title="Legal basis",
                    excerpt="We process data.",
                )
            )
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)

            assert api_rows == [], "Diagnostic suppression note must exclude row from published API"
            assert canonical == [], "Diagnostic suppression note must exclude row from canonical dataset"

    def test_non_canonical_systemic_key_excluded_from_api(self):
        """
        A systemic finding with a non-canonical issue key (not in CANONICAL_ISSUE_TAXONOMY)
        must be excluded from the published API rather than causing a 500 error.
        """
        with _db() as db:
            audit = _audit(db)
            row = Finding(
                audit_id=audit.id,
                section_id="systemic:governance_disclosure_gap",  # NOT in taxonomy
                status="gap",
                severity="medium",
                publication_state="publishable",
                artifact_role="publishable_finding",
                classification="probable_gap",
                legal_requirement="GDPR Article 13(1)(c)",
                gap_note="Governance disclosure is insufficient.",
                remediation_note="Add governance details.",
                policy_evidence_excerpt="We process data responsibly.",
                primary_legal_anchor='["GDPR Article 13(1)(c)"]',
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="1(c)",
                    article_title="Legal basis",
                    excerpt="We process data responsibly.",
                )
            )
            db.commit()

            # Must not raise ValueError / 500; must return empty (non-canonical key filtered)
            api_rows = get_findings(audit.id, "test-user", db)
            assert api_rows == [], "Non-canonical systemic key must be excluded from published API without error"

    def test_all_published_api_rows_have_canonical_issue_key_and_label(self):
        """Every row in the published API must have issue_key and issue_label in the taxonomy."""
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id, "systemic:missing_legal_basis")
            _canonical_finding(
                db,
                audit.id,
                "systemic:missing_transfer_notice",
                anchor='["GDPR Article 13(1)(f)"]',
                article_number="13",
                paragraph_ref="1(f)",
                gap_note="Transfer safeguards not stated.",
                remediation_note="Add safeguard details.",
                chunk_excerpt="Data may be transferred outside the EEA.",
            )
            _retention_finding(db, audit.id)
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) >= 1

            for r in api_rows:
                assert r.issue_key and r.issue_key.strip(), f"Missing issue_key for row {r.id}"
                assert r.issue_label and r.issue_label.strip(), f"Missing issue_label for row {r.id}"
                assert r.issue_key in _CANONICAL_ISSUE_TAXONOMY_KEYS, (
                    f"issue_key '{r.issue_key}' is not in CANONICAL_ISSUE_TAXONOMY"
                )

    def test_get_findings_does_not_mutate_db(self):
        """
        get_findings is a read-only operation; it must not modify publication_state,
        artifact_role, or publish_flag of any Finding row.
        """
        with _db() as db:
            audit = _audit(db)
            f = _canonical_finding(db, audit.id)
            db.commit()

            # Snapshot state before
            before_pub_state = f.publication_state
            before_artifact = f.artifact_role

            get_findings(audit.id, "test-user", db)

            db.refresh(f)
            assert f.publication_state == before_pub_state, "get_findings must not modify publication_state"
            assert f.artifact_role == before_artifact, "get_findings must not modify artifact_role"


# ---------------------------------------------------------------------------
# Contract: domain consolidation merges lawful-basis / consent / tracking
# ---------------------------------------------------------------------------


def _domain_finding(
    db: Session,
    audit_id: str,
    section_id: str,
    anchor: str,
    article_number: str,
    paragraph_ref: str,
    gap_note: str,
    remediation_note: str,
    chunk_excerpt: str = "We process data to provide the service.",
) -> Finding:
    row = Finding(
        audit_id=audit_id,
        section_id=section_id,
        status="gap",
        severity="high",
        publication_state="publishable",
        artifact_role="publishable_finding",
        classification="systemic_violation" if section_id.startswith("systemic:") else "probable_gap",
        legal_requirement=f"GDPR Article {article_number}({paragraph_ref})",
        gap_note=gap_note,
        remediation_note=remediation_note,
        policy_evidence_excerpt="We collect and process your personal data.",
        primary_legal_anchor=anchor,
    )
    db.add(row)
    db.flush()
    db.add(
        FindingCitation(
            finding_id=row.id,
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            article_number=article_number,
            paragraph_ref=paragraph_ref,
            article_title="Transparency obligation",
            excerpt=chunk_excerpt,
        )
    )
    return row


class TestDomainConsolidation:
    """Domain consolidation: missing_legal_basis + invalid_consent_or_legal_basis +
    cookies_tracking_consent_gap merge into one lawful_basis_and_consent finding."""

    def test_two_domain_siblings_merge_into_one(self):
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis per Article 6(1).",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)", "GDPR Article 7"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent mechanism is deficient.",
                remediation_note="Obtain valid consent per Article 7.",
            )
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            assert len(canonical) == 1, f"Two domain siblings must merge into one finding; got {len(canonical)}"
            assert getattr(canonical[0], "_domain_merged_key", None) == "lawful_basis_and_consent"

    def test_three_domain_siblings_merge_into_one(self):
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis per Article 6(1).",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent is not freely given.",
                remediation_note="Fix consent collection.",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:cookies_tracking_consent_gap",
                anchor='["GDPR Article 6(1)", "GDPR Article 5(1)(a)"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="No legal basis stated for tracking cookies.",
                remediation_note="Add consent mechanism for tracking.",
            )
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            assert len(canonical) == 1, f"Three domain siblings must merge into one finding; got {len(canonical)}"
            assert getattr(canonical[0], "_domain_merged_key", None) == "lawful_basis_and_consent"

    def test_merged_finding_has_lawful_basis_and_consent_key_in_api(self):
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis per Article 6(1).",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent is not freely given.",
                remediation_note="Fix consent collection.",
            )
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) == 1
            assert api_rows[0].issue_key == "lawful_basis_and_consent"
            assert api_rows[0].issue_label == "Lawful basis and consent"

    def test_single_domain_member_is_not_merged(self):
        """A lone missing_legal_basis finding must NOT be promoted to lawful_basis_and_consent."""
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id, "systemic:missing_legal_basis")
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            assert len(canonical) == 1
            # No domain merge occurred; key stays as-is
            assert getattr(canonical[0], "_domain_merged_key", None) is None

            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) == 1
            assert api_rows[0].issue_key == "missing_legal_basis"

    def test_non_domain_findings_survive_consolidation(self):
        """Retention and transfer findings must not be affected by domain consolidation."""
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis.",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent is deficient.",
                remediation_note="Fix consent.",
            )
            _canonical_finding(
                db,
                audit.id,
                "systemic:missing_retention_period",
                anchor='["GDPR Article 13(2)(a)"]',
                article_number="13",
                paragraph_ref="2(a)",
                gap_note="No retention period stated.",
                remediation_note="Add retention criteria.",
                chunk_excerpt="Data kept for service delivery.",
            )
            db.commit()

            canonical = canonical_published_findings(db, audit.id)
            keys = {getattr(r, "_domain_merged_key", None) or r.section_id.split("systemic:")[-1] for r in canonical}
            assert len(canonical) == 2, (
                f"Domain siblings merge into 1 + retention stays = 2 total; got {len(canonical)}"
            )
            assert "missing_retention_period" in keys or any("retention" in k for k in keys)

    def test_api_count_equals_canonical_after_domain_merge(self):
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis per Article 6(1).",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent is not freely given.",
                remediation_note="Fix consent collection.",
            )
            _canonical_finding(
                db,
                audit.id,
                "systemic:missing_retention_period",
                anchor='["GDPR Article 13(2)(a)"]',
                article_number="13",
                paragraph_ref="2(a)",
                gap_note="No retention period stated.",
                remediation_note="Add retention criteria.",
                chunk_excerpt="Data kept for service delivery.",
            )
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            canonical = canonical_published_findings(db, audit.id)
            assert len(api_rows) == len(canonical), (
                f"API count {len(api_rows)} must equal canonical count {len(canonical)} after domain merge"
            )

    def test_merged_anchors_include_all_domain_siblings(self):
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis.",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)", "GDPR Article 7"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent is deficient.",
                remediation_note="Fix consent.",
            )
            db.commit()

            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) == 1
            anchors = api_rows[0].primary_legal_anchor or []
            anchor_str = " ".join(anchors).lower()
            assert "13(1)(c)" in anchor_str, "Merged anchors must include Article 13(1)(c)"
            assert "6(1)" in anchor_str, "Merged anchors must include Article 6(1)"


# ---------------------------------------------------------------------------
# Contract: published field quality — no machine/debug text in user-facing fields
# ---------------------------------------------------------------------------

# These phrases must never appear in any published API field.
_BANNED_PUBLISHED_PHRASES: list[str] = [
    "gdpr compliance assessment for",
    "obligation-specific notice wording",
    "required gdpr article anchor",
    "internal diagnostic",
    "classified as internal diagnostic",
    "unknown issue",
    "required gdpr transparency disclosure is missing or insufficient for this obligation",
    "update the notice to include the required gdpr disclosure language for this obligation",
]

_QUALITY_CHECKED_FIELDS: list[str] = [
    "gap_note",
    "remediation_note",
    "citation_summary_text",
    "policy_evidence_excerpt",
    "omission_statement",
]


class TestPublishedFieldQuality:
    """No machine-generated fallback or debug text may appear in user-facing API fields."""

    def _check_fields(self, api_rows: list) -> None:
        for row in api_rows:
            for field in _QUALITY_CHECKED_FIELDS:
                value = (getattr(row, field, None) or "").lower()
                for phrase in _BANNED_PUBLISHED_PHRASES:
                    assert phrase not in value, (
                        f"Banned phrase '{phrase}' found in field '{field}' "
                        f"for issue_key '{row.issue_key}': {value[:120]!r}"
                    )

    def test_no_machine_text_in_standard_finding_fields(self):
        with _db() as db:
            audit = _audit(db)
            _canonical_finding(db, audit.id, "systemic:missing_legal_basis")
            db.commit()
            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) >= 1
            self._check_fields(api_rows)

    def test_no_machine_text_in_retention_finding_fields(self):
        with _db() as db:
            audit = _audit(db)
            _retention_finding(db, audit.id)
            db.commit()
            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) >= 1
            self._check_fields(api_rows)

    def test_no_machine_text_in_rights_finding_fields(self):
        with _db() as db:
            audit = _audit(db)
            _rights_finding(db, audit.id)
            db.commit()
            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) >= 1
            self._check_fields(api_rows)

    def test_no_machine_text_in_domain_merged_finding_fields(self):
        with _db() as db:
            audit = _audit(db)
            _domain_finding(
                db,
                audit.id,
                "systemic:missing_legal_basis",
                anchor='["GDPR Article 13(1)(c)"]',
                article_number="13",
                paragraph_ref="1(c)",
                gap_note="No lawful basis stated.",
                remediation_note="Add lawful basis per Article 6(1).",
            )
            _domain_finding(
                db,
                audit.id,
                "systemic:invalid_consent_or_legal_basis",
                anchor='["GDPR Article 6(1)"]',
                article_number="6",
                paragraph_ref="1",
                gap_note="Consent is not freely given.",
                remediation_note="Fix consent collection.",
            )
            db.commit()
            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) == 1
            assert api_rows[0].issue_key == "lawful_basis_and_consent"
            self._check_fields(api_rows)

    def test_citation_summary_text_is_always_human_readable(self):
        """citation_summary_text must be a human sentence, never a machine token."""
        with _db() as db:
            audit = _audit(db)
            # Row with no citation_summary_text in DB — must use omission map fallback
            row = Finding(
                audit_id=audit.id,
                section_id="systemic:missing_complaint_right",
                status="gap",
                severity="high",
                publication_state="publishable",
                artifact_role="publishable_finding",
                classification="probable_gap",
                legal_requirement="GDPR Article 13(2)(d)",
                gap_note="The notice does not mention the right to complain.",
                remediation_note="Add complaint-right text.",
                policy_evidence_excerpt="We take your privacy seriously.",
                primary_legal_anchor='["GDPR Article 13(2)(d)"]',
                citation_summary_text=None,
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="2(d)",
                    article_title="Complaint right",
                    excerpt="We take your privacy seriously.",
                )
            )
            db.commit()
            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) == 1
            cst = (api_rows[0].citation_summary_text or "").lower()
            assert "gdpr compliance assessment for" not in cst, (
                f"Machine token leaked into citation_summary_text: {cst!r}"
            )
            assert len(api_rows[0].citation_summary_text or "") > 20, (
                "citation_summary_text must be a meaningful sentence, not empty"
            )

    def test_gap_note_uses_family_fallback_when_db_text_is_generic(self):
        """When the DB gap_note is the generic canonical fallback, FAMILY_FALLBACK_COPY must replace it."""
        with _db() as db:
            audit = _audit(db)
            row = Finding(
                audit_id=audit.id,
                section_id="systemic:missing_transfer_notice",
                status="gap",
                severity="high",
                publication_state="publishable",
                artifact_role="publishable_finding",
                classification="probable_gap",
                legal_requirement="GDPR Article 13(1)(f)",
                gap_note="Based on the reviewed notice, required GDPR disclosure is missing or insufficient for this obligation.",
                remediation_note="Update the notice to include GDPR-required disclosure language for this obligation.",
                policy_evidence_excerpt="We may transfer data to third countries.",
                primary_legal_anchor='["GDPR Article 13(1)(f)"]',
            )
            db.add(row)
            db.flush()
            db.add(
                FindingCitation(
                    finding_id=row.id,
                    chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
                    article_number="13",
                    paragraph_ref="1(f)",
                    article_title="Transfers",
                    excerpt="We may transfer data to third countries.",
                )
            )
            db.commit()
            api_rows = get_findings(audit.id, "test-user", db)
            assert len(api_rows) == 1
            gap = (api_rows[0].gap_note or "").lower()
            assert "required gdpr transparency disclosure is missing or insufficient for this obligation" not in gap
            assert "based on the reviewed notice, required gdpr disclosure is missing or insufficient" not in gap
            assert len(api_rows[0].gap_note or "") > 30
