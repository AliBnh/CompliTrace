import json
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.db.session import get_db
from app.models.audit import (
    AnalysisCitation,
    Audit,
    AuditAnalysisItem,
    DocumentGroup,
    EvidenceRecord,
    Finding,
    FindingCitation,
    RemediationItem,
    RemediationSuggestion,
    Report,
)
from app.schemas.audit import (
    AnalysisCitationOut,
    AnalysisItemOut,
    AuditCreate,
    AuditOut,
    CitationOut,
    ExportContractOut,
    FinalDecisionLedgerRowOut,
    FindingOut,
    GroupCreate,
    GroupOut,
    GroupUpdate,
    GroupVersionCreate,
    GroupVersionOut,
    PublishedFindingOut,
    RemediationItemOut,
    RemediationStatusOut,
    RemediationSuggestionOut,
    ReportOut,
    ReportTriggerOut,
    ReviewItemOut,
)
from app.services.audit_runner import run_audit
from app.services.llm import run_llm_plain_text
from app.services.reports import (
    build_export_contract,
    canonical_published_findings,
    final_exported_findings,
    generate_report_text,
)
from prometheus_client import Counter, Histogram

router = APIRouter()
GENERIC_NOT_ASSESSABLE_GAP = "Not assessable from provided excerpt; additional documentary context is required."
GENERIC_NOT_ASSESSABLE_REMEDIATION = "Provide complete notice excerpts and rerun legal qualification."
FAMILY_FALLBACK_COPY: dict[str, tuple[str, str]] = {
    "missing_controller_identity": (
        "Controller identity/contact details are not clearly visible in the reviewed excerpt.",
        "Provide controller legal-entity identity and direct privacy contact details.",
    ),
    "missing_controller_contact": (
        "Controller contact channel is not clearly visible in the reviewed excerpt.",
        "Add a direct privacy contact route (email/webform/postal address) for data-subject requests.",
    ),
    "missing_transfer_notice": (
        "The notice references data transfers to jurisdictions outside the EEA but does not identify the safeguard or transfer mechanism relied upon (e.g. adequacy decision, SCCs, BCRs).",
        "State the specific transfer mechanism or adequacy basis for each destination country or region where personal data is sent.",
    ),
    "profiling_disclosure_gap": (
        "The notice describes automated processing that generates profiles or influences service outcomes but does not explain the logic involved, the significance of this processing, or its envisaged consequences for data subjects.",
        "Describe the logic of profiling or automated decision-making, its significance for data subjects, and any safeguards or human-review mechanisms available.",
    ),
    "missing_legal_basis": (
        "The notice does not disclose the specific lawful basis under Article 6(1) relied upon for each processing activity described.",
        "For each processing purpose, state the applicable Article 6(1) ground (e.g. consent, contract performance, legitimate interests) and, where relevant, the specific legitimate interest pursued.",
    ),
    "missing_retention_period": (
        "The notice does not state how long personal data is retained or the objective criteria used to determine retention periods.",
        "For each category of personal data, state the specific retention period or the objective criteria used to determine it (e.g. legal obligation, contract duration).",
    ),
    "missing_complaint_right": (
        "The notice does not inform data subjects of their right to lodge a complaint with a supervisory authority.",
        "State that data subjects may lodge a complaint with the relevant supervisory authority and, where possible, identify that authority.",
    ),
    "missing_rights_notice": (
        "The notice does not fully describe the rights available to data subjects under Chapter III of the GDPR.",
        "Describe all applicable rights (access, rectification, erasure, restriction, objection, portability) and the process for exercising them, including response timelines.",
    ),
    "controller_processor_role_ambiguity": (
        "Customer-data/service-allocation language is visible, but the reviewed material does not clearly allocate controller/processor roles.",
        "Provide role-allocation or DPA wording showing when the company acts as controller, processor, or joint controller.",
    ),
    "article_14_indirect_collection_gap": (
        "Indirect/source-of-data signals are visible, but the reviewed material does not show source-category disclosure sufficient for Article 14 assessment.",
        "Provide source-of-data and indirect-collection notice language.",
    ),
    "recipients_disclosure_gap": (
        "Third-party sharing signals are visible, but categories of recipients are not clearly disclosed in the reviewed material.",
        "List recipient categories (e.g., processors, partners, payment/cloud providers) and disclosure contexts.",
    ),
    "purpose_specificity_gap": (
        "Data-category language is visible, but category-to-purpose mapping is not clearly specific in the reviewed material.",
        "Map each key data category to concrete processing purposes and, where relevant, lawful-basis context.",
    ),
    "lawful_basis_and_consent": (
        "The notice does not adequately disclose the lawful basis for processing, does not obtain valid consent where required, and does not clearly explain the legal ground for tracking technologies.",
        "Identify and document the specific Article 6(1) lawful basis for each processing purpose; ensure consent is freely given, specific, informed and unambiguous where relied upon; and clearly explain the legal basis for any tracking or profiling activities.",
    ),
    "cookie_disclosure_gap": (
        "The notice references cookies or tracking technologies but does not explain their purposes, legal basis, or how data subjects can manage their preferences.",
        "Add a dedicated section describing: the types of cookies and tracking technologies used, their purposes (e.g. analytics, functionality, advertising), the legal basis relied upon for each, and how data subjects can adjust or withdraw consent.",
    ),
    "dpo_contact_gap": (
        "The notice does not provide the required contact details for the Data Protection Officer.",
        "Add the Data Protection Officer's designated contact details — at minimum a postal or electronic address — to the notice.",
    ),
    "article14_source_transparency_gap": (
        "The notice does not disclose the source from which personal data was indirectly obtained, as required by GDPR Article 14(2)(f).",
        "State clearly the category of source from which personal data was obtained (e.g. public registers, referral partners, data brokers) and whether it came from publicly available sources.",
    ),
    "invalid_consent_or_legal_basis": (
        "The notice does not clearly state a valid lawful basis for the described processing activities, or the basis stated does not meet GDPR validity requirements.",
        "Review each processing activity and state the specific Article 6(1) ground relied upon. Where consent is the basis, ensure it is freely given, specific, informed and unambiguous, and that it can be withdrawn as easily as given.",
    ),
    "cookies_tracking_consent_gap": (
        "The notice references tracking technologies without disclosing the applicable legal basis or the consent mechanism available to data subjects.",
        "Add a section explaining which tracking technologies are used, their purposes, the legal basis for each (consent or legitimate interests), and how data subjects can opt in or opt out.",
    ),
    "special_category_basis_unclear": (
        "Potential special-category/sensitive-data language is visible, but Article 9 condition/safeguard details are unclear in the reviewed material.",
        "Clarify whether true Article 9 categories are processed and state the Article 9(2) condition plus safeguards.",
    ),
}

# Per-issue omission summaries used as citation_summary_text fallback.
# Must be plain human-readable statements, not machine tokens.
_OMISSION_SUMMARY_MAP: dict[str, str] = {
    "missing_legal_basis": "The notice does not state the lawful basis for any of the described processing activities.",
    "missing_retention_period": "The notice does not state how long personal data is retained or the criteria used to determine retention.",
    "missing_rights_notice": "The notice does not explain the rights available to data subjects under GDPR Chapter III.",
    "missing_complaint_right": "The notice does not inform data subjects of their right to lodge a complaint with a supervisory authority.",
    "missing_transfer_notice": "The notice references data transfers outside the EEA but does not identify the safeguard or transfer mechanism relied upon.",
    "profiling_disclosure_gap": "The notice describes automated processing but does not explain the logic, significance, or envisaged consequences for data subjects.",
    "recipients_disclosure_gap": "The notice references data sharing with third parties but does not identify the categories of recipients.",
    "missing_controller_identity": "The notice does not clearly identify the data controller.",
    "missing_controller_contact": "The notice does not provide a direct contact channel for privacy-related requests.",
    "purpose_specificity_gap": "The notice describes categories of personal data but does not map them to specific processing purposes.",
    "controller_processor_role_ambiguity": "The notice does not clearly allocate controller and processor roles.",
    "cookie_disclosure_gap": "The notice references cookies or tracking technologies but does not explain their purposes, legal basis, or user controls.",
    "invalid_consent_or_legal_basis": "The notice does not state a valid lawful basis for the described processing activities.",
    "cookies_tracking_consent_gap": "The notice references tracking technologies without disclosing the legal basis or consent mechanism.",
    "article14_source_transparency_gap": "The notice does not disclose the source from which personal data was indirectly obtained.",
    "article_14_indirect_collection_gap": "The notice does not describe the categories of personal data collected indirectly or the circumstances of their collection.",
    "special_category_basis_unclear": "The notice references sensitive data processing without identifying the applicable Article 9 condition or safeguards.",
    "dpo_contact_gap": "The notice does not provide the required contact details for the Data Protection Officer.",
    "lawful_basis_and_consent": "The notice does not adequately disclose the lawful basis for processing, does not obtain valid consent where required, and does not address the legal ground for tracking technologies.",
}


def _deserialize_json_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return None


def _deserialize_bool_flag(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.lower() == "true"


def _issue_from_finding_section(section_id: str) -> str | None:
    if section_id.startswith("systemic:"):
        return section_id.split("systemic:", 1)[1]
    if section_id.startswith("ledger:"):
        return "completeness_or_suppression_ledger"
    return None


def _issue_subtype_for_row(row: Finding) -> str:
    text = f"{row.gap_note or ''} {row.remediation_note or ''}".lower()
    if "indefinite" in text or "invalid" in text:
        return "invalid"
    if "contradict" in text:
        return "contradictory"
    if "unclear" in text:
        return "present_but_unclear"
    if "overbroad" in text:
        return "present_but_overbroad"
    if row.status == "partial":
        return "incomplete"
    return "missing"


def _canonical_issue_key(issue: str | None) -> str:
    return (issue or "governance_disclosure_gap").strip().lower()


orchestration_api_requests_total = Counter(
    "orchestration_api_requests_total",
    "Orchestration service API requests",
    ["endpoint", "method", "status"],
)
orchestration_audit_created_total = Counter(
    "orchestration_audit_created_total",
    "Audits created through the orchestration API",
)
orchestration_report_generation_requests_total = Counter(
    "orchestration_report_generation_requests_total",
    "Report generation requests received",
)
orchestration_report_downloads_total = Counter(
    "orchestration_report_downloads_total",
    "Report downloads requested",
)
orchestration_remediation_requests_total = Counter(
    "orchestration_remediation_requests_total",
    "Remediation suggestion requests received",
)
orchestration_audit_creation_latency_seconds = Histogram(
    "orchestration_audit_creation_latency_seconds",
    "Latency for audit creation requests",
)
orchestration_report_generation_latency_seconds = Histogram(
    "orchestration_report_generation_latency_seconds",
    "Latency for report generation",
)
orchestration_remediation_generation_latency_seconds = Histogram(
    "orchestration_remediation_generation_latency_seconds",
    "Latency for remediation generation",
)


def _record_api_request(endpoint: str, method: str, status_code: str) -> None:
    orchestration_api_requests_total.labels(endpoint=endpoint, method=method, status=status_code).inc()


def _apply_family_fallback(
    issue_type: str | None, gap_note: str | None, remediation_note: str | None
) -> tuple[str | None, str | None]:
    if not issue_type:
        return gap_note, remediation_note
    normalized_gap = (gap_note or "").strip().lower()
    normalized_remediation = (remediation_note or "").strip().lower()
    generic_patterns = {
        GENERIC_NOT_ASSESSABLE_GAP.lower(),
        "not assessable from excerpt",
        "additional documentary context is required",
        "manual review required",
        "based on the reviewed notice, required gdpr disclosure is missing",
        "required gdpr disclosure is missing or insufficient",
        "explicit violation validator matched",
        "duty validation marked",
        "finding promoted to substantive non-compliance",
    }
    generic_remediation_patterns = {
        GENERIC_NOT_ASSESSABLE_REMEDIATION.lower(),
        "provide complete notice excerpts",
        "rerun legal qualification",
    }
    is_generic_gap = any(p in normalized_gap for p in generic_patterns)
    is_generic_remediation = any(p in normalized_remediation for p in generic_remediation_patterns)
    if not (is_generic_gap or is_generic_remediation):
        return gap_note, remediation_note
    replacement = FAMILY_FALLBACK_COPY.get(issue_type)
    if not replacement:
        return gap_note, remediation_note
    return replacement


INTERNAL_MARKER_RE = re.compile(
    r"(?:\s*\[withheld by final publication validator\]\s*|suppression_validator=\S+|state_invariant_violation:[^\s,;]+|post-review invariant rewrite|diagnostic_internal_only|\[[^\]]*internal[^\]]*\])",
    flags=re.IGNORECASE,
)
INTERNAL_EVIDENCE_RE = re.compile(
    r"(withheld|suppression|validator|internal[_\s-]?only|diagnostic[_\s-]?internal|state_invariant|publication gate)",
    flags=re.IGNORECASE,
)
INTERNAL_REASONING_RE = re.compile(
    r"(obligation map|suppression|validator|internal engine|state invariant|publication gate|hydration validator)",
    flags=re.IGNORECASE,
)
BANNED_OUTPUT_TOKENS = [
    "coverage_check",
    "absence-proof mode",
    "reviewed sections",
    "result=required disclosure absent",
    "retrieval_summary",
]


def get_current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    verify_url = f"{settings.auth_service_url.rstrip('/')}/auth/verify"
    try:
        response = httpx.get(
            verify_url,
            headers={"Authorization": authorization},
            timeout=5.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    payload = response.json()
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return str(user_id)


def _get_owned_audit_or_404(db: Session, audit_id: str, user_id: str) -> Audit:
    audit = db.scalar(select(Audit).where(Audit.id == audit_id, Audit.user_id == user_id))
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit


def _get_owned_group_or_404(db: Session, group_id: str, user_id: str, *, for_update: bool = False) -> DocumentGroup:
    query = select(DocumentGroup).where(DocumentGroup.id == group_id, DocumentGroup.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    group = db.scalar(query)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


def _assign_next_version_number(db: Session, group_id: str, user_id: str) -> int:
    current_max = db.scalar(
        select(func.max(Audit.version_number)).where(Audit.document_group_id == group_id, Audit.user_id == user_id)
    )
    return 0 if current_max is None else int(current_max) + 1


def _assign_audit_to_group_atomic(db: Session, audit: Audit, group_id: str, user_id: str) -> Audit:
    _get_owned_group_or_404(db, group_id, user_id, for_update=True)
    version_number = _assign_next_version_number(db, group_id, user_id)
    audit.document_group_id = group_id
    audit.version_number = version_number
    db.add(audit)
    return audit


FAMILY_ANCHOR_TEMPLATES: dict[str, list[str]] = {
    "missing_controller_contact": ["GDPR Article 13(1)(a)", "GDPR Article 14(1)(a)"],
    "missing_controller_identity": ["GDPR Article 13(1)(a)", "GDPR Article 14(1)(a)"],
    "missing_legal_basis": ["GDPR Article 13(1)(c)", "GDPR Article 14(1)(c)"],
    "missing_transfer_notice": ["GDPR Article 13(1)(f)", "GDPR Article 14(1)(f)", "GDPR Article 44", "GDPR Article 46"],
    "profiling_disclosure_gap": ["GDPR Article 13(2)(f)", "GDPR Article 14(2)(g)"],
    "recipients_disclosure_gap": ["GDPR Article 13(1)(e)", "GDPR Article 14(1)(e)"],
    "purpose_specificity_gap": ["GDPR Article 13(1)(c)", "GDPR Article 14(1)(c)", "GDPR Article 5(1)(b)"],
    "missing_retention_period": ["GDPR Article 13(2)(a)", "GDPR Article 14(2)(a)"],
    "missing_rights_notice": ["GDPR Article 13(2)(b)", "GDPR Article 14(2)(c)"],
    "missing_complaint_right": ["GDPR Article 13(2)(d)", "GDPR Article 14(2)(e)"],
    "lawful_basis_and_consent": [
        "GDPR Article 13(1)(c)",
        "GDPR Article 14(1)(c)",
        "GDPR Article 6(1)",
        "GDPR Article 7",
    ],
}

CANONICAL_ISSUE_TAXONOMY: dict[str, str] = {
    "missing_legal_basis": "Legal basis disclosure",
    "missing_rights_notice": "Data subject rights",
    "missing_complaint_right": "Right to lodge a complaint",
    "missing_retention_period": "Retention period",
    "missing_transfer_notice": "International transfers",
    "profiling_disclosure_gap": "Automated decision-making / profiling",
    "cookie_disclosure_gap": "Cookie transparency disclosure",
    "missing_controller_contact": "Contact information",
    "missing_controller_identity": "Contact information",
    "purpose_specificity_gap": "Purpose specificity",
    "recipients_disclosure_gap": "Recipients of personal data",
    "controller_processor_role_ambiguity": "Role allocation disclosure",
    "invalid_consent_or_legal_basis": "Valid consent and lawful basis",
    "cookies_tracking_consent_gap": "Tracking technologies and consent",
    "lawful_basis_and_consent": "Lawful basis and consent",
    "article14_source_transparency_gap": "Source of indirectly obtained data",
    "article_14_indirect_collection_gap": "Indirectly collected personal data",
    "special_category_basis_unclear": "Special category data processing basis",
    "dpo_contact_gap": "Data protection officer contact",
}


def _require_issue_label(issue_key: str | None) -> str:
    if not issue_key:
        raise ValueError("published finding missing issue_key")
    if issue_key not in CANONICAL_ISSUE_TAXONOMY:
        raise ValueError(f"unmapped issue_key in published finding: {issue_key}")
    return CANONICAL_ISSUE_TAXONOMY[issue_key]


def _derive_issue_key_for_published_row(row: Finding) -> str | None:
    domain_key = getattr(row, "_domain_merged_key", None)
    if domain_key and domain_key in CANONICAL_ISSUE_TAXONOMY:
        return domain_key
    from_section = _issue_from_finding_section(row.section_id)
    if from_section:
        # Validate the key is in the canonical taxonomy before accepting it.
        # Non-canonical systemic keys cannot be labeled and must not be published.
        return from_section if from_section in CANONICAL_ISSUE_TAXONOMY else None
    # legal_requirement sometimes encodes the issue key directly ("for issue <key>").
    lr = (row.legal_requirement or "").strip()
    m = re.search(r"\bfor issue\s+([a-z_]+)\b", lr, re.IGNORECASE)
    if m:
        candidate = m.group(1).lower()
        if candidate in CANONICAL_ISSUE_TAXONOMY:
            return candidate
    from_text = _infer_issue_from_text(None, row.gap_note, row.remediation_note)
    if from_text:
        return from_text
    # Comprehensive anchor-based fallback — matches the same article set as
    # _derive_issue_key_for_row in reports.py so that count equality holds.
    anchors = " ".join(
        (_deserialize_json_list(row.primary_legal_anchor) or [])
        + (_deserialize_json_list(row.secondary_legal_anchors) or [])
    ).lower()
    if "13(1)(c)" in anchors or "14(1)(c)" in anchors:
        return "missing_legal_basis"
    if "13(1)(f)" in anchors or "14(1)(f)" in anchors or "article 44" in anchors:
        return "missing_transfer_notice"
    if "13(1)(a)" in anchors or "14(1)(a)" in anchors:
        return "missing_controller_contact"
    if "13(1)(e)" in anchors or "14(1)(e)" in anchors:
        return "recipients_disclosure_gap"
    if "13(2)(f)" in anchors or "14(2)(g)" in anchors:
        return "profiling_disclosure_gap"
    if "13(2)(a)" in anchors or "14(2)(a)" in anchors:
        return "missing_retention_period"
    if "13(2)(b)" in anchors or "14(2)(c)" in anchors:
        return "missing_rights_notice"
    if "13(2)(d)" in anchors or "14(2)(e)" in anchors:
        return "missing_complaint_right"
    return None


_PUBLISHED_TEXT_BANNED_PHRASES: tuple[str, ...] = (
    "local finding suppressed:",
    "local finding:",
    "local finding",
    "anchor is absent",
    "required gdpr article anchor",
    "finding classified as internal diagnostic",
    "internal diagnostic",
    "diagnostic only",
    "conditional issue",
    "duty_key=",
    "duty_status=",
)


def _sanitize_published_text(text: str | None) -> str | None:
    if not text:
        return text
    cleaned = INTERNAL_MARKER_RE.sub(" ", text)
    cleaned = re.sub(r"coverage_check:[^\s,;]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"not_visible_in_reviewed_sections", " ", cleaned, flags=re.IGNORECASE)
    for phrase in _PUBLISHED_TEXT_BANNED_PHRASES:
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip() or None


_CITATION_EVIDENCE_CONCLUSION_PREFIXES = (
    "the notice does not",
    "the privacy notice does not",
    "the policy does not",
    "this notice does not",
    "this notice fails",
    "the data controller does not",
    "the document does not",
    "this section does not",
    "the controller has not",
    "no disclosure",
    "there is no",
    "it does not",
)


def _is_rendered_citation_conclusion(text: str) -> bool:
    norm = text.strip().lower()
    return any(norm.startswith(p) for p in _CITATION_EVIDENCE_CONCLUSION_PREFIXES)


def _render_published_evidence_excerpt(
    citation_excerpt: str | None,
    evidence_excerpt: str | None,
    *,
    issue_hint: str | None = None,
) -> str:
    candidates = [_sanitize_published_text(citation_excerpt), _sanitize_published_text(evidence_excerpt)]
    for candidate in candidates:
        if not candidate:
            continue
        if INTERNAL_EVIDENCE_RE.search(candidate):
            continue
        if len(candidate.strip()) < 12 or candidate.strip().lower() in {".", ":", "section"}:
            continue
        if _is_rendered_citation_conclusion(candidate):
            continue
        return candidate
    hint = (issue_hint or "this finding").replace("_", " ")
    return "No explicit disclosure found in this section." if hint else "No explicit disclosure found in this document."


def _sanitize_external_reasoning(text: str | None) -> str | None:
    cleaned = _sanitize_published_text(text)
    if not cleaned:
        return cleaned
    cleaned = INTERNAL_REASONING_RE.sub("section-linked evidence review", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _clean_absence_statement(issue: str | None) -> str:
    mapping = {
        "missing_legal_basis": "No explicit legal basis is described for the listed processing activities.",
        "missing_retention_period": "No explicit retention period or objective retention criteria is described for the listed processing activities.",
        "missing_transfer_notice": "No explicit international transfer mechanism or safeguard is described for the listed processing activities.",
        "profiling_disclosure_gap": "No explicit profiling logic, significance, or consequences are described for the listed processing activities.",
        "recipients_disclosure_gap": "No explicit recipient categories are described for the listed processing activities.",
        "purpose_specificity_gap": "Purpose descriptions are present but not clearly linked to specific data categories.",
        "missing_controller_contact": "No explicit controller contact route is described for the listed processing activities.",
        "missing_controller_identity": "No explicit controller legal identity is described for the listed processing activities.",
    }
    return mapping.get(
        issue or "", "No explicit required disclosure is described for the listed processing activities."
    )


def _is_clean_absence_statement(text: str | None) -> bool:
    cleaned = (text or "").strip()
    lowered = cleaned.lower()
    return (
        (
            lowered.startswith("no explicit ")
            or lowered.startswith("legal basis wording is present but invalid or unclear")
            or lowered.startswith("purpose descriptions are present but not clearly linked")
        )
        and cleaned.endswith(".")
        and not _has_banned_output_tokens(cleaned)
    )


def _has_banned_output_tokens(text: str | None) -> bool:
    norm = (text or "").lower()
    return any(token in norm for token in BANNED_OUTPUT_TOKENS)


def _has_valid_legal_rule(row: FindingOut) -> bool:
    rule = (row.legal_rule or row.legal_requirement or "").strip()
    return bool(rule) and not _has_banned_output_tokens(rule)


def _has_valid_legal_analysis(row: FindingOut) -> bool:
    analysis = (row.legal_analysis or row.gap_reasoning or "").strip()
    return bool(analysis) and not _has_banned_output_tokens(analysis)


def _has_valid_evidence_bundle(row: FindingOut) -> bool:
    positive_mode = bool(row.citations) and all(
        c.evidence_id and c.source_type and c.source_ref and not _has_banned_output_tokens(c.excerpt)
        for c in row.citations
    )
    scoped_absence_mode = (not row.citations) and _is_clean_absence_statement(row.policy_evidence_excerpt)
    return positive_mode or scoped_absence_mode


def _can_publish_row(row: FindingOut) -> bool:
    return (
        row.final_legal_outcome in {"non_compliant", "partially_compliant", "compliant"}
        and _has_valid_legal_rule(row)
        and _has_valid_legal_analysis(row)
        and _has_valid_evidence_bundle(row)
    )


def _infer_issue_from_text(issue: str | None, gap_note: str | None, remediation_note: str | None) -> str | None:
    if issue:
        return issue
    text = ((gap_note or "") + " " + (remediation_note or "")).lower()
    if "controller" in text and "contact" in text:
        return "missing_controller_contact"
    if any(t in text for t in {"transfer", "third country", "safeguard", "adequacy", "scc"}):
        return "missing_transfer_notice"
    if "profil" in text:
        return "profiling_disclosure_gap"
    if "recipient" in text or "third party" in text:
        return "recipients_disclosure_gap"
    if "purpose" in text and "category" in text:
        return "purpose_specificity_gap"
    return issue


def _anchors_for_issue(issue: str | None, anchors: list[str] | None) -> list[str]:
    preferred = FAMILY_ANCHOR_TEMPLATES.get(issue or "", [])
    if not preferred:
        return anchors or ["GDPR Article 13(1)(a)"]
    if not anchors:
        return preferred
    norm = " ".join(a.lower() for a in anchors)
    matching = [a for a in preferred if a.lower().replace("gdpr ", "") in norm or a.lower() in norm]
    return matching or preferred


ISSUE_ARTICLE_RULES: dict[str, dict[str, set[int]]] = {
    "missing_controller_identity": {"primary": {13, 14}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_controller_contact": {"primary": {13, 14}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_legal_basis": {"primary": {6, 13, 14}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_retention_period": {"primary": {5, 13, 14}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_rights_notice": {"primary": {12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}, "disallowed": set()},
    "missing_complaint_right": {"primary": {13, 14, 77}, "disallowed": {21, 22}},
    "missing_transfer_notice": {"primary": {13, 14, 44, 45, 46}, "disallowed": {15, 21}},
    "profiling_disclosure_gap": {"primary": {13, 14, 22}, "disallowed": {15}},
    "controller_processor_role_ambiguity": {"primary": {13, 14}, "disallowed": {21, 22}},
    "recipients_disclosure_gap": {"primary": {13, 14}, "disallowed": {21, 22}},
    "purpose_specificity_gap": {"primary": {5, 6, 13, 14}, "disallowed": {21, 22}},
}


def _article_int(value: str | None) -> int | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _citation_article_findings(issue: str | None, citations: list[CitationOut]) -> tuple[bool, bool]:
    rules = ISSUE_ARTICLE_RULES.get(issue or "")
    if not rules:
        return True, False
    article_numbers = {_article_int(c.article_number) for c in citations}
    article_numbers.discard(None)
    if not article_numbers:
        return False, False
    has_primary = bool(article_numbers & rules.get("primary", set()))
    has_disallowed = bool(article_numbers & rules.get("disallowed", set()))
    return has_primary, has_disallowed


def _ensure_flbc_reasoning(row: FindingOut, issue: str | None) -> None:
    if row.status not in {"gap", "partial"}:
        return
    current = _sanitize_external_reasoning(row.gap_reasoning) or _sanitize_external_reasoning(row.gap_note) or ""
    if all(token in current for token in ("Fact:", "Law:", "Breach:", "Conclusion:")):
        row.gap_reasoning = current
        return
    evidence_text = _sanitize_published_text(row.policy_evidence_excerpt) or "Notice evidence reviewed."
    rule_text = _sanitize_external_reasoning(row.legal_requirement) or ", ".join(
        row.primary_legal_anchor or ["GDPR Articles 12-14"]
    )
    breach_text = (
        _sanitize_published_text(row.gap_note)
        or f"Required disclosure for {issue or 'the issue'} is missing or unclear."
    )
    row.gap_reasoning = (
        f"Fact: {evidence_text} "
        f"Law: {rule_text}. "
        f"Breach: {breach_text}. "
        "Conclusion: the privacy notice does not satisfy the cited GDPR transparency requirement."
    )


def _sanitize_review_text(text: str | None, *, debug: bool) -> str | None:
    if debug or not text:
        return text
    cleaned = _sanitize_published_text(text)
    if not cleaned:
        return cleaned
    cleaned = cleaned.replace(
        "Systemic finding withheld from publication pending complete legal/document support package",
        "This issue was identified internally but is not yet finalized for publication because the current evidence package is incomplete.",
    )
    return cleaned


def _normalize_internal_state(
    classification: str | None,
    status: str | None,
    artifact_role: str | None,
    finding_level: str | None,
    publication_state: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if classification != "diagnostic_internal_only":
        return status, artifact_role, finding_level, publication_state
    return "not_applicable", "support_only", "none", "internal_only"


def _load_final_decision_map(db: Session, audit_id: str) -> dict[str, dict[str, str | bool | list[str] | float]] | None:
    disposition_ledger = (
        db.query(Finding)
        .filter(Finding.audit_id == audit_id)
        .filter(Finding.legal_requirement == "suppression_validator=final_disposition_map")
        .order_by(Finding.id.desc())
        .first()
    )
    if not disposition_ledger or not disposition_ledger.gap_reasoning:
        return None
    try:
        parsed = json.loads(disposition_ledger.gap_reasoning)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _publication_allowed_from_map(decision_map: dict[str, dict[str, str | bool | list[str] | float]]) -> bool:
    controls = decision_map.get("_controls", {})
    publication_allowed = controls.get("publication_allowed")
    if isinstance(publication_allowed, bool):
        return publication_allowed
    core_families = ("controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right")
    for family in core_families:
        status = str((decision_map.get(family, {}) or {}).get("status") or "")
        if status in {"unresolved_internal_error", "blocked"}:
            return False
    return True


def _project_published_findings_from_map(
    audit_id: str,
    decision_map: dict[str, dict[str, str | bool | list[str] | float]],
    backing_rows: list[Finding] | None = None,
    known_evidence_ids: set[str] | None = None,
    evidence_by_chunk: dict[str, EvidenceRecord] | None = None,
    evidence_by_id: dict[str, EvidenceRecord] | None = None,
) -> list[FindingOut]:
    family_to_issue = _family_issue_map()
    severity_defaults = {
        "controller_identity_contact": "high",
        "legal_basis": "high",
        "transfer": "high",
        "profiling": "high",
        "retention": "medium",
        "rights_notice": "medium",
        "complaint_right": "medium",
        "role_ambiguity": "high",
        "article14_source": "medium",
        "recipients": "medium",
        "special_category": "high",
        "dpo_contact": "medium",
        "purpose_mapping": "medium",
    }
    out: list[FindingOut] = []
    remediation_defaults = {
        "missing_transfer_notice": "State whether personal data are transferred internationally and identify the safeguard or transfer mechanism relied upon, such as adequacy decisions or appropriate safeguards, and how data subjects can obtain further information.",
        "profiling_disclosure_gap": "If profiling or comparable evaluation occurs, explain the logic involved and, where required, the significance and envisaged consequences for individuals.",
        "controller_processor_role_ambiguity": "Clarify when the organization acts as controller, processor, or similar role across the different processing contexts described in the notice.",
        "recipients_disclosure_gap": "Disclose categories of recipients and the main disclosure contexts (e.g., processors, vendors, partners, payment/cloud providers).",
        "purpose_specificity_gap": "Map each key personal-data category to specific processing purposes (and lawful-basis context where relevant).",
    }
    row_by_issue: dict[str, Finding] = {}
    for row in backing_rows or []:
        issue = _issue_from_finding_section(row.section_id)
        if issue and issue not in row_by_issue:
            row_by_issue[issue] = row
    for family, issue in family_to_issue.items():
        item = decision_map.get(family, {}) or {}
        status = str(item.get("status") or "")
        publish_rec = str(item.get("publication_recommendation") or "internal_only")
        if status not in {"gap", "referenced_but_unseen"} or publish_rec != "publish":
            continue
        reason = _sanitize_external_reasoning(str(item.get("reasoning") or "")) or ""
        searched_sections = [
            str(v) for v in (item.get("searched_sections") or item.get("section_ids") or []) if isinstance(v, str)
        ]
        projected_evidence_ids = [
            str(v)
            for v in (item.get("positive_evidence_ids") or [])
            if isinstance(v, str) and str(v).startswith("evi:")
        ]
        backing = row_by_issue.get(issue)
        if backing is not None:
            projected_evidence_ids.extend(_deserialize_json_list(backing.document_evidence_refs) or [])
            projected_evidence_ids.append(f"evi:policy:{backing.section_id}")
        projected_evidence_ids = list(
            dict.fromkeys(e for e in projected_evidence_ids if isinstance(e, str) and e.startswith("evi:"))
        )
        inferred_issue = _infer_issue_from_text(
            issue, backing.gap_note if backing else reason, backing.remediation_note if backing else None
        )
        if inferred_issue in {
            "missing_controller_identity",
            "missing_controller_contact",
        } and _controller_identity_disclosed_in_document(
            backing_rows,
            evidence_by_id,
        ):
            item["blocker_reason"] = "document-wide reconciliation found controller identity/contact disclosure"
            item["missing_requirements"] = ["document_wide_reconciliation.override"]
            continue
        if _document_wide_duty_satisfied_elsewhere(inferred_issue, backing_rows):
            item["blocker_reason"] = "document-wide reconciliation satisfied duty elsewhere"
            item["missing_requirements"] = ["document_wide_reconciliation.override"]
            continue
        primary_anchor = _anchors_for_issue(
            inferred_issue,
            _deserialize_json_list(backing.primary_legal_anchor) if backing and backing.primary_legal_anchor else None,
        )
        fallback_summary = f"Evidence-linked projection for {issue}: " + (
            ", ".join(projected_evidence_ids[:4])
            if projected_evidence_ids
            else "no explicit evidence refs from final map"
        )
        projected_chunk_citations = [
            _citation_out(
                c,
                (evidence_by_chunk or {}).get(c.chunk_id)
                or EvidenceRecord(
                    evidence_id=f"evi:chunk:{c.chunk_id}",
                    audit_id=audit_id,
                    evidence_type="retrieval_chunk",
                    source_ref=c.chunk_id,
                    text_excerpt=c.excerpt,
                    derived_from_evidence_ids=None,
                    article_number=c.article_number,
                    paragraph_ref=c.paragraph_ref,
                ),
            )
            for c in (backing.citations if backing else [])
            if _is_real_evidence_ref(c.chunk_id)
        ]
        projected_fallback_citations = [
            CitationOut(
                chunk_id=(ev.source_ref or ev.evidence_id or "policy-evidence"),
                evidence_id=ev.evidence_id,
                source_type=ev.evidence_type,
                source_ref=ev.source_ref,
                article_number=ev.article_number or "13",
                paragraph_ref=ev.paragraph_ref,
                article_title="Evidence record",
                excerpt=_render_published_evidence_excerpt(None, ev.text_excerpt, issue_hint=issue),
            )
            for ref in projected_evidence_ids
            for ev in [((evidence_by_id or {}).get(ref))]
            if _is_allowed_real_quote_evidence(ev)
        ]
        derived_citation_refs = [
            c.evidence_id for c in (projected_chunk_citations or projected_fallback_citations) if c.evidence_id
        ]
        projected_evidence_ids = list(
            dict.fromkeys(projected_evidence_ids + [ref for ref in derived_citation_refs if isinstance(ref, str)])
        )
        rem_note = (
            _sanitize_published_text(backing.remediation_note)
            if backing and backing.remediation_note
            else remediation_defaults.get(
                issue, "Address the identified gap with explicit GDPR-compliant notice language."
            )
        )
        legal_requirement_text = (
            _sanitize_published_text(backing.legal_requirement) if backing and backing.legal_requirement else None
        )
        resolved_severity, resolved_rationale = _severity_rule(inferred_issue, "gap", f"systemic:{issue}", reason)
        policy_excerpt = (
            _sanitize_published_text(backing.policy_evidence_excerpt)
            if backing and backing.policy_evidence_excerpt
            else None
        )
        if not policy_excerpt:
            policy_excerpt = _clean_absence_statement(inferred_issue)
        projected = FindingOut(
            id=f"projected:{audit_id}:{family}",
            section_id=f"systemic:{issue}",
            status="gap",
            severity=resolved_severity or severity_defaults.get(family, "medium"),
            classification=_published_legal_conclusion("gap", inferred_issue, "probable_gap"),
            finding_type="systemic",
            publish_flag="yes",
            artifact_role="publishable_finding",
            finding_level="systemic",
            publication_state="publishable",
            confidence=backing.confidence if backing and backing.confidence is not None else 0.66,
            confidence_evidence=backing.confidence_evidence
            if backing and backing.confidence_evidence is not None
            else 0.72,
            confidence_applicability=backing.confidence_applicability
            if backing and backing.confidence_applicability is not None
            else 0.74,
            confidence_article_fit=backing.confidence_article_fit
            if backing and backing.confidence_article_fit is not None
            else 0.72,
            confidence_synthesis=backing.confidence_synthesis
            if backing and backing.confidence_synthesis is not None
            else 0.7,
            confidence_overall=backing.confidence_overall
            if backing and backing.confidence_overall is not None
            else 0.66,
            source_scope=backing.source_scope if backing and backing.source_scope is not None else "full_notice",
            source_scope_confidence=backing.source_scope_confidence
            if backing and backing.source_scope_confidence is not None
            else 0.75,
            assertion_level=backing.assertion_level
            if backing and backing.assertion_level is not None
            else "probable_document_gap",
            primary_legal_anchor=primary_anchor,
            secondary_legal_anchors=_deserialize_json_list(backing.secondary_legal_anchors) if backing else None,
            citation_summary_text=_sanitize_published_text(backing.citation_summary_text)
            if backing and backing.citation_summary_text
            else fallback_summary,
            support_complete=_deserialize_bool_flag(backing.support_complete) if backing else None,
            omission_basis=_deserialize_bool_flag(backing.omission_basis) if backing else None,
            policy_evidence_excerpt=policy_excerpt,
            legal_requirement=legal_requirement_text or f"Rule: {', '.join(primary_anchor)}.",
            gap_note=_sanitize_published_text(reason) or "Required disclosure gap identified in final decision map.",
            remediation_note=rem_note,
            gap_reasoning=_build_richer_gap_reasoning(
                section_id=f"systemic:{issue}",
                issue=inferred_issue,
                fact=(backing.policy_evidence_excerpt if backing else None) or reason,
                rule=legal_requirement_text or ", ".join(primary_anchor),
                remediation=rem_note,
                conclusion=_sanitize_external_reasoning(reason),
            ),
            severity_rationale=_sanitize_published_text(backing.severity_rationale)
            if backing and backing.severity_rationale
            else resolved_rationale,
            document_evidence_refs=[
                ref for ref in projected_evidence_ids if (known_evidence_ids is None or ref in known_evidence_ids)
            ]
            or None,
            affected_sections=searched_sections
            or ([backing.section_id] if backing and backing.section_id else [f"systemic:{issue}"]),
            where_evidence_found=searched_sections
            or ([backing.section_id] if backing and backing.section_id else [f"systemic:{issue}"]),
            where_disclosure_missing=searched_sections
            or ([backing.section_id] if backing and backing.section_id else [f"systemic:{issue}"]),
            citations=(projected_chunk_citations or projected_fallback_citations),
        )
        projected = _fill_required_published_fields(projected)
        if family in {
            "controller_identity_contact",
            "transfer",
            "profiling",
            "role_ambiguity",
            "recipients",
            "purpose_mapping",
        }:
            if projected.citations and any(
                c.evidence_id is None or c.source_type is None or c.source_ref is None for c in projected.citations
            ):
                item["blocker_reason"] = "specialist finding citation linkage is malformed"
                continue
        missing_requirements = _missing_hydration_requirements(projected)
        if missing_requirements:
            substantive_missing = {
                "primary_legal_anchor",
                "citations.article_primary_fit",
                "citations.article_disallowed",
            } & set(missing_requirements)
            if substantive_missing:
                projected.primary_legal_anchor = projected.primary_legal_anchor or _anchors_for_issue(
                    inferred_issue, None
                )
                if not projected.citations:
                    projected.policy_evidence_excerpt = projected.policy_evidence_excerpt or _clean_absence_statement(
                        inferred_issue
                    )
                    projected.citations = [
                        CitationOut(
                            chunk_id=f"synthetic:{family}",
                            evidence_id=None,
                            source_type="synthetic_absence_statement",
                            source_ref=f"systemic:{issue}",
                            article_number="13",
                            paragraph_ref=None,
                            article_title="GDPR transparency obligation",
                            excerpt=projected.policy_evidence_excerpt,
                        )
                    ]
            projected.confidence_overall = min(projected.confidence_overall or 0.62, 0.62)
            projected.support_complete = False
        out.append(projected)
    return out


def _document_wide_duty_satisfied_elsewhere(issue: str, rows: list[Finding] | None) -> bool:
    if not rows:
        return False
    target_family = _issue_family(issue)
    if not target_family:
        return False
    for row in rows:
        if row.section_id.startswith("ledger:") or row.section_id.startswith("systemic:"):
            continue
        row_issue = _issue_from_finding_section(row.section_id) or _infer_issue_from_text(
            _issue_from_finding_section(row.section_id), row.gap_note, row.remediation_note
        )
        if _issue_family(row_issue) != target_family:
            continue
        if row.status == "compliant" and row.publish_flag == "yes":
            return True
    return False


def _controller_identity_disclosed_in_document(
    rows: list[Finding] | None,
    evidence_by_id: dict[str, EvidenceRecord] | None = None,
) -> bool:
    if not rows and not evidence_by_id:
        return False
    corpus_parts: list[str] = []
    for row in rows or []:
        corpus_parts.append(
            _sanitize_external_reasoning(
                f"{row.policy_evidence_excerpt or ''} {row.gap_note or ''} {row.remediation_note or ''}"
            )
            or ""
        )
    for ev in (evidence_by_id or {}).values():
        corpus_parts.append(_sanitize_external_reasoning(f"{ev.text_excerpt or ''} {ev.source_ref or ''}") or "")
    text = " ".join(corpus_parts).lower()
    has_identity = any(
        t in text for t in {"registered office", "registered address", "inc.", "limited", "llc", "corp", "corporation"}
    ) or bool(
        re.search(r"\b[A-Z][A-Za-z0-9&,\.\s]{2,}\b(?:inc\.|llc|ltd|limited|corporation|corp)\b", " ".join(corpus_parts))
    )
    has_contact = any(t in text for t in {"privacy@", "dpo@", "contact us at", "@", "webform", "privacy email"})
    return has_identity and has_contact


def _issue_family(issue: str | None) -> str | None:
    mapping = {
        "missing_controller_contact": "controller_identity_contact",
        "missing_controller_identity": "controller_identity_contact",
        "missing_transfer_notice": "transfer",
        "profiling_disclosure_gap": "profiling",
        "controller_processor_role_ambiguity": "role_ambiguity",
        "special_category_basis_unclear": "special_category",
        "recipients_disclosure_gap": "recipients",
        "purpose_specificity_gap": "purpose_mapping",
    }
    return mapping.get(issue or "")


def _section_level_reasoning(row: Finding) -> str:
    section = row.section_id
    obligation = row.obligation_under_review or "transparency disclosure duty"
    fact = (
        _sanitize_external_reasoning(row.policy_evidence_excerpt)
        or _sanitize_external_reasoning(row.gap_note)
        or "Section-local evidence indicates a visibility gap."
    )
    rule = (
        _sanitize_external_reasoning(row.legal_requirement)
        or "Apply GDPR transparency duties (Articles 12-14 and family-specific anchors)."
    )
    legal_application = "Section-specific language is evaluated against the cited rule to determine whether disclosure is complete and explicit."
    conclusion = _sanitize_external_reasoning(row.gap_note) or "Section-level disclosure is insufficient."
    remediation = (
        _sanitize_published_text(row.remediation_note) or "Add section-specific compliant wording and cross-references."
    )
    return (
        f"In section {section}, the notice states: {fact}. "
        f"Applicable GDPR duty: {rule}. "
        f"Assessment: {legal_application} "
        f"Breach finding: {conclusion}. "
        f"Required remediation: {remediation}. "
        f"Obligation under review: {obligation}."
    )


def _published_legal_conclusion(status: str | None, issue: str | None, existing: str | None) -> str:
    if status in {"not_assessable", "needs review"}:
        return "not_assessable"
    if status == "partial":
        return "partially_compliant"
    strong_non_compliant = {
        "missing_legal_basis",
        "missing_retention_period",
        "missing_rights_notice",
        "missing_complaint_right",
        "missing_transfer_notice",
        "profiling_disclosure_gap",
        "recipients_disclosure_gap",
        "purpose_specificity_gap",
    }
    if status == "gap" and issue in strong_non_compliant:
        return "non_compliant"
    if status == "gap":
        return "partially_compliant"
    return existing or "not_assessable"


def _final_legal_outcome_for_row(row: FindingOut) -> str:
    status = (row.status or "").lower()
    cls = (row.classification or "").lower()
    if "publication_blocked" in cls:
        if status in {"gap", "partial"} and row.issue_key in {
            "missing_legal_basis",
            "missing_retention_period",
            "missing_transfer_notice",
            "profiling_disclosure_gap",
            "recipients_disclosure_gap",
            "purpose_specificity_gap",
        }:
            return "non_compliant" if status == "gap" else "partially_compliant"
        return "not_assessable_from_provided_text"
    if status == "compliant":
        return "compliant"
    if status in {"partial"} or cls in {"partially_compliant", "referenced_but_unseen"}:
        return "partially_compliant"
    if status == "gap" or cls in {"non_compliant", "clear_non_compliance", "systemic_violation"}:
        return "non_compliant"
    return "not_assessable_from_provided_text"


def _severity_rule(issue: str | None, status: str | None, section_id: str, reasoning: str | None) -> tuple[str, str]:
    high_default = {
        "missing_legal_basis",
        "missing_controller_contact",
        "missing_controller_identity",
        "missing_rights_notice",
        "missing_complaint_right",
    }
    medium_default = {
        "missing_retention_period",
        "recipients_disclosure_gap",
        "purpose_specificity_gap",
        "controller_processor_role_ambiguity",
    }
    text = (reasoning or "").lower()
    transfer_or_profiling_signal = any(
        t in text for t in {"transfer", "scc", "adequacy", "profil", "automated decision"}
    )
    total_failure = any(
        t in text
        for t in {
            "across sections",
            "across the notice",
            "not stated for any",
            "no clear contact route",
            "no safeguard",
            "not disclosed",
        }
    )
    rights_or_accountability = any(
        t in text for t in {"rights", "accountability", "exercise of rights", "controller accountability"}
    )
    if issue in high_default:
        sev = "high"
    elif issue in {"missing_transfer_notice", "profiling_disclosure_gap"}:
        sev = "high" if transfer_or_profiling_signal else "medium"
    elif issue in medium_default:
        sev = "medium"
    else:
        sev = "medium" if status in {"gap", "partial"} else "low"
    if sev == "medium" and (total_failure or rights_or_accountability):
        sev = "high"
    rationale = (
        f"severity_rule={sev}; issue={issue or 'unknown'}; "
        f"basis={'total_failure' if total_failure else 'family_default'}; "
        f"accountability_impact={'yes' if rights_or_accountability else 'no'}; section={section_id}"
    )
    return sev, rationale


def _build_richer_gap_reasoning(
    *,
    section_id: str,
    issue: str | None,
    fact: str | None,
    rule: str | None,
    remediation: str | None,
    conclusion: str | None,
) -> str:
    if issue == "missing_controller_contact":
        return (
            f"The notice content linked to {section_id} identifies the organization but does not provide an actionable privacy contact route. "
            "Under GDPR Articles 13(1)(a) and 14(1)(a), controller identity and contact details must be disclosed. "
            "Because a contact channel is missing, the disclosure remains non-compliant for controller-contact transparency. "
            f"Conclusion: {_sanitize_external_reasoning(conclusion) or 'non-compliant controller-contact disclosure gap'}. "
            "Remediation: add direct privacy contact details (email, webform, or postal route)."
        )
    safe_fact = _sanitize_published_text(fact) or "Relevant policy evidence indicates missing or unclear disclosure."
    safe_rule = _sanitize_published_text(rule) or "GDPR transparency and notice obligations."
    safe_conclusion = (
        _sanitize_published_text(conclusion) or "The required disclosure element is not sufficiently addressed."
    )
    safe_remediation = _sanitize_published_text(remediation) or "Provide explicit compliant notice wording."
    return (
        f"Fact: {safe_fact}. "
        f"Law: {safe_rule}. "
        f"Breach: {safe_conclusion}. "
        f"Conclusion for {issue or 'unspecified issue'} in {section_id}: the notice requires corrective disclosure. "
        f"Remediation: {safe_remediation}."
    )


_DUTY_LABELS: dict[str, str] = {
    "controller_identity_contact": "Controller identity and contact details",
    "legal_basis": "Legal basis for processing",
    "retention": "Data retention period",
    "rights_notice": "Data subject rights",
    "complaint_right": "Right to lodge a supervisory authority complaint",
    "transfer": "International data transfer disclosure",
    "profiling": "Profiling and automated decision-making",
    "role_ambiguity": "Controller/processor role clarity",
    "article14_source": "Article 14 indirect data source",
    "article14": "Article 14 indirect data source",
    "recipients": "Recipients and third-party disclosures",
    "special_category": "Special category data handling",
    "dpo_contact": "Data Protection Officer contact",
    "purpose_mapping": "Purpose-to-data-category mapping",
}

_INTERNAL_SUPPRESSION_PATTERNS: list[tuple[str, str | None]] = [
    (
        "local finding suppressed: required gdpr article anchor is absent",
        "Section-level finding excluded: no GDPR article anchor was determinable for this section.",
    ),
    (
        "duty-level reconciliation marked",
        None,  # handled dynamically below
    ),
    (
        "not assessable from provided excerpt",
        "This section could not be conclusively assessed from the available excerpt.",
    ),
    (
        "section filtered by auditability gate",
        "This section was excluded from GDPR audit scope (meta-section filter).",
    ),
    (
        "systemic finding withheld from publication",
        "This issue was identified internally but the evidence package is incomplete for publication.",
    ),
]


def _clean_suppression_reason(gap_note: str | None) -> str | None:
    if not gap_note:
        return None
    lower = gap_note.lower().strip()
    for prefix, replacement in _INTERNAL_SUPPRESSION_PATTERNS:
        if lower.startswith(prefix):
            if replacement:
                return replacement
            m = re.search(r"marked (\w+) as (\w+)", lower)
            if m:
                duty_raw = m.group(1).replace("_", " ")
                verdict = m.group(2)
                return f"The {duty_raw} obligation was assessed as {verdict} at the document level; this section observation is informational only."
            return None
    return None


def _auditor_review_reason(
    duty_or_family: str | None, disposition: str | None, raw_observation: str | None
) -> str | None:
    if not duty_or_family:
        return None
    label = _DUTY_LABELS.get(duty_or_family, duty_or_family.replace("_", " ").title())
    clean_obs = _sanitize_external_reasoning(raw_observation) if raw_observation else None

    if disposition == "satisfied":
        base = f"{label}: compliant. The required disclosure was identified in the document."
    elif disposition == "gap":
        base = f"{label}: non-compliant. The required disclosure was not identified. A finding has been published."
    elif disposition in ("partial", "partially_compliant"):
        base = f"{label}: partially compliant. The disclosure is incomplete. Review the associated finding."
    elif disposition == "not_assessable":
        base = f"{label}: not assessable. The relevant document sections could not be conclusively evaluated."
    elif not disposition or disposition in ("not_triggered",):
        base = f"{label}: not applicable. This specialist check was not triggered for this document."
    elif disposition in ("unresolved_internal_error", "blocked"):
        base = f"{label}: assessment error. Manual review is required."
    else:
        base = f"{label}: {disposition}."

    if clean_obs and disposition not in ("satisfied", "not_triggered", None):
        return f"{base} Detail: {clean_obs}"
    return base


def _review_reasoning(reason: str | None, family_or_duty: str | None) -> str | None:
    """Legacy wrapper — used only in debug mode to preserve raw pipeline text."""
    base = _sanitize_external_reasoning(reason)
    if not base:
        return base
    return f"[debug] Duty: {family_or_duty or 'unknown'}. Raw observation: {base}."


def _project_section_level_findings(
    backing_rows: list[Finding],
    known_evidence_ids: set[str],
    evidence_by_chunk: dict[str, EvidenceRecord],
) -> list[FindingOut]:
    out: list[FindingOut] = []
    seen_families: set[str] = set()
    for row in backing_rows:
        issue = _issue_from_finding_section(row.section_id)
        if issue is None:
            text = f"{(row.gap_note or '').lower()} {(row.remediation_note or '').lower()}"
            if "transfer" in text:
                issue = "missing_transfer_notice"
            elif "profil" in text or "automated decision" in text:
                issue = "profiling_disclosure_gap"
            elif "controller" in text and "processor" in text:
                issue = "controller_processor_role_ambiguity"
            elif "recipient" in text or "third party" in text:
                issue = "recipients_disclosure_gap"
            elif "purpose" in text and "category" in text:
                issue = "purpose_specificity_gap"
            elif "special category" in text:
                issue = "special_category_basis_unclear"
        family = _issue_family(issue)
        if family not in {
            "controller_identity_contact",
            "transfer",
            "profiling",
            "role_ambiguity",
            "special_category",
            "purpose_mapping",
            "recipients",
        }:
            continue
        if row.section_id.startswith("systemic:") or row.section_id.startswith("ledger:"):
            continue
        if row.publication_state != "publishable" or row.publish_flag != "yes":
            continue
        if row.status not in {"gap", "partial"}:
            continue
        if not row.citations:
            continue
        if family in seen_families:
            continue
        seen_families.add(family)
        citations = [
            _citation_out(c, evidence_by_chunk.get(c.chunk_id))
            for c in row.citations
            if _is_real_evidence_ref(c.chunk_id)
            and (f"evi:chunk:{c.chunk_id}" in known_evidence_ids or c.chunk_id in evidence_by_chunk)
        ]
        if not citations:
            continue
        out.append(
            _fill_required_published_fields(
                FindingOut(
                    id=row.id,
                    section_id=row.section_id,
                    status=row.status,
                    severity=row.severity,
                    classification=_published_legal_conclusion(row.status, issue, row.classification),
                    finding_type=row.finding_type,
                    publish_flag=row.publish_flag,
                    artifact_role=row.artifact_role,
                    finding_level="section",
                    publication_state=row.publication_state,
                    confidence=row.confidence,
                    confidence_evidence=row.confidence_evidence,
                    confidence_applicability=row.confidence_applicability,
                    confidence_article_fit=row.confidence_article_fit,
                    confidence_synthesis=row.confidence_synthesis,
                    confidence_overall=row.confidence_overall if row.confidence_overall is not None else row.confidence,
                    obligation_under_review=row.obligation_under_review,
                    legal_requirement=_sanitize_published_text(row.legal_requirement)
                    or f"Section-level family rule for {issue or family}.",
                    gap_reasoning=_section_level_reasoning(row),
                    severity_rationale=_sanitize_published_text(row.severity_rationale),
                    primary_legal_anchor=_deserialize_json_list(row.primary_legal_anchor)
                    or [f"GDPR Article {citations[0].article_number}"],
                    secondary_legal_anchors=_deserialize_json_list(row.secondary_legal_anchors),
                    source_scope=row.source_scope,
                    source_scope_confidence=row.source_scope_confidence,
                    assertion_level=row.assertion_level,
                    document_evidence_refs=[
                        ref
                        for ref in (_deserialize_json_list(row.document_evidence_refs) or [])
                        if ref in known_evidence_ids
                    ]
                    or None,
                    affected_sections=[row.section_id],
                    where_evidence_found=[row.section_id],
                    where_disclosure_missing=[row.section_id],
                    citation_summary_text=_sanitize_published_text(row.citation_summary_text)
                    or f"Section-local evidence supports {family} publication path.",
                    gap_note=_sanitize_published_text(row.gap_note),
                    remediation_note=_sanitize_published_text(row.remediation_note),
                    citations=citations,
                )
            )
        )
    return [row for row in out if not _hydration_missing(row)]


def _derive_confidence_level(confidence: float | None) -> str:
    if confidence is None:
        return "low"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _is_real_evidence_ref(value: str) -> bool:
    token = (value or "").strip().lower()
    return bool(token) and not token.startswith("systemic-anchor:") and not token.startswith("evi:synthetic")


def _is_allowed_real_quote_evidence(evidence: EvidenceRecord | None) -> bool:
    if evidence is None:
        return False
    source_type = (evidence.evidence_type or "").strip().lower()
    if "synthetic" in source_type:
        return False
    if source_type == "retrieval_chunk":
        return True
    return source_type in {"notice_quote", "section_quote", "policy_quote", "document_quote"}


def _citation_has_allowed_evidence_mode(c: CitationOut) -> bool:
    source_type = (c.source_type or "").strip().lower()
    evidence_id = (c.evidence_id or "").strip().lower()
    if not source_type:
        return False
    if source_type == "absence_trace":
        source_ref = (c.source_ref or "").lower()
        return "sections=" in source_ref and "headings=" in source_ref and "terms=" in source_ref
    if "synthetic" in source_type or evidence_id.startswith("evi:synthetic"):
        return False
    return source_type in {"retrieval_chunk", "notice_quote", "section_quote", "policy_quote", "document_quote"}


def _known_evidence_ids(db: Session, audit_id: str) -> set[str]:
    return {row[0] for row in db.query(EvidenceRecord.evidence_id).filter(EvidenceRecord.audit_id == audit_id).all()}


def _evidence_by_chunk_ref(db: Session, audit_id: str) -> dict[str, EvidenceRecord]:
    rows = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.audit_id == audit_id)
        .filter(EvidenceRecord.evidence_type == "retrieval_chunk")
        .all()
    )
    out: dict[str, EvidenceRecord] = {}
    for row in rows:
        if row.source_ref and row.source_ref not in out:
            out[row.source_ref] = row
    # Always supplement with FindingCitation chunk_ids not already in primary evidence —
    # ensures GDPR-corpus and systemic-finding citations created in audit_runner are resolvable.
    citation_rows = (
        db.query(FindingCitation.chunk_id)
        .join(Finding, Finding.id == FindingCitation.finding_id)
        .filter(Finding.audit_id == audit_id)
        .all()
    )
    for (chunk_id,) in citation_rows:
        if not chunk_id or not _is_real_evidence_ref(chunk_id) or chunk_id in out:
            continue
        out[chunk_id] = EvidenceRecord(
            evidence_id=f"evi:chunk:{chunk_id}",
            audit_id=audit_id,
            evidence_type="retrieval_chunk",
            source_ref=chunk_id,
            text_excerpt=None,
            derived_from_evidence_ids=None,
            article_number=None,
            paragraph_ref=None,
        )
    return out


def _evidence_by_id(db: Session, audit_id: str) -> dict[str, EvidenceRecord]:
    rows = db.query(EvidenceRecord).filter(EvidenceRecord.audit_id == audit_id).all()
    return {row.evidence_id: row for row in rows}


def _citation_out(c: FindingCitation, evidence: EvidenceRecord) -> CitationOut:
    return CitationOut(
        chunk_id=c.chunk_id,
        evidence_id=evidence.evidence_id,
        source_type=evidence.evidence_type,
        source_ref=evidence.source_ref,
        article_number=c.article_number,
        paragraph_ref=c.paragraph_ref,
        article_title=c.article_title,
        excerpt=_render_published_evidence_excerpt(c.excerpt, evidence.text_excerpt, issue_hint=c.article_title),
    )


def _hydration_missing(row: FindingOut) -> bool:
    if not row.primary_legal_anchor:
        return True
    if not (row.citation_summary_text or "").strip():
        return True
    if not row.source_scope or not row.assertion_level:
        return True
    if row.confidence_overall is None:
        return True
    if not row.remediation_note:
        return True
    if len(row.citations) == 0:
        return True
    return False


def _missing_hydration_requirements(row: FindingOut) -> list[str]:
    missing: list[str] = []
    if not row.primary_legal_anchor:
        missing.append("primary_legal_anchor")
    if not (row.citation_summary_text or "").strip():
        missing.append("citation_summary_text")
    if not row.source_scope:
        missing.append("source_scope")
    if not row.assertion_level:
        missing.append("assertion_level")
    if row.confidence_overall is None:
        missing.append("confidence_overall")
    if not row.remediation_note:
        missing.append("remediation_note")
    if len(row.citations) == 0:
        missing.append("citations")
    if not row.policy_evidence_excerpt:
        missing.append("policy_evidence_excerpt")
    if not row.document_evidence_refs:
        missing.append("document_evidence_refs")
    if not row.affected_sections:
        missing.append("affected_sections")
    if not row.where_disclosure_missing:
        missing.append("where_disclosure_missing")
    for c in row.citations:
        if not c.evidence_id:
            missing.append("citations.evidence_id")
        if not c.source_type:
            missing.append("citations.source_type")
        if not c.source_ref:
            missing.append("citations.source_ref")
        if not _citation_has_allowed_evidence_mode(c):
            missing.append("citations.evidence_mode")
    issue = _infer_issue_from_text(_issue_key_from_section(row.section_id), row.gap_note, row.remediation_note)
    if row.citations:
        has_primary_article, has_disallowed_article = _citation_article_findings(issue, row.citations)
        if not has_primary_article:
            missing.append("citations.article_primary_fit")
        if has_disallowed_article:
            missing.append("citations.article_disallowed")
    return missing


def _family_issue_map() -> dict[str, str]:
    return {
        "controller_identity_contact": "missing_controller_contact",
        "controller_identity": "missing_controller_identity",
        "controller_contact": "missing_controller_contact",
        "legal_basis": "missing_legal_basis",
        "retention": "missing_retention_period",
        "rights_notice": "missing_rights_notice",
        "complaint_right": "missing_complaint_right",
        "transfer": "missing_transfer_notice",
        "profiling": "profiling_disclosure_gap",
        "role_ambiguity": "controller_processor_role_ambiguity",
        "article14_source": "article_14_indirect_collection_gap",
        "recipients": "recipients_disclosure_gap",
        "special_category": "special_category_basis_unclear",
        "dpo_contact": "dpo_contact_gap",
        "purpose_mapping": "purpose_specificity_gap",
    }


def _issue_for_family(family: str, item: dict[str, str | bool | list[str] | float]) -> str:
    default = _family_issue_map().get(family, family)
    if family not in {"controller_identity_contact", "controller_identity", "controller_contact"}:
        return default
    if family == "controller_identity":
        return "missing_controller_identity"
    if family == "controller_contact":
        return "missing_controller_contact"
    reasoning = str(item.get("reasoning") or "").strip().lower()
    blocker_reason = str(item.get("blocker_reason") or "").strip().lower()
    searchable = " ".join(
        [
            " ".join([str(v).strip().lower() for v in (item.get("searched_terms") or []) if isinstance(v, str)]),
            " ".join([str(v).strip().lower() for v in (item.get("searched_headings") or []) if isinstance(v, str)]),
        ]
    )
    text = f"{reasoning} {blocker_reason} {searchable}"
    if any(
        t in text
        for t in {"identity missing", "controller identity missing", "controller not named", "legal identity missing"}
    ):
        return "missing_controller_identity"
    if any(t in text for t in {"contact", "privacy@", "email", "webform", "address", "contact route"}):
        return "missing_controller_contact"
    return "missing_controller_contact"


def _is_substantive_publication_blocker(row: FindingOut) -> bool:
    if row.classification != "publication_blocked":
        return False
    if not row.issue_key or not row.blocker_reason or not row.missing_requirements:
        return False
    if not row.affected_sections or not row.where_disclosure_missing:
        return False
    note = str(row.gap_note or "").strip().lower()
    return "searched sections" in note and "searched headings" in note and "searched terms" in note


def _blocker_reason_for_missing_requirements(missing: list[str]) -> str:
    missing_set = set(missing)
    if {"citations.article_primary_fit", "citations.article_disallowed"} & missing_set:
        return "citation article mismatch"
    if {
        "document_evidence_refs",
        "citations",
        "citations.evidence_id",
        "citations.source_type",
        "citations.source_ref",
        "citations.evidence_mode",
    } & missing_set:
        return "missing evidence linkage"
    if {"source_scope", "assertion_level"} & missing_set:
        return "missing section traceability"
    if {"policy_evidence_excerpt"} & missing_set:
        return "missing absence-proof or quote evidence"
    if {"confidence_overall"} & missing_set:
        return "confidence inconsistency"
    return "incomplete hydration"


def _publication_blocker_row(
    *,
    audit_id: str,
    family: str,
    issue: str,
    reason: str,
    missing_requirements: list[str] | None = None,
    searched_sections: list[str] | None = None,
    searched_headings: list[str] | None = None,
    searched_terms: list[str] | None = None,
) -> FindingOut:
    issue_terms = {
        "missing_controller_contact": ["controller contact", "privacy contact", "email", "webform", "address"],
        "missing_transfer_notice": ["transfer", "third country", "safeguard", "SCC", "adequacy"],
        "profiling_disclosure_gap": ["profiling", "automated decision", "logic", "significance", "effects"],
        "article_14_indirect_collection_gap": [
            "data source",
            "indirect collection",
            "partner",
            "aggregator",
            "public records",
        ],
        "controller_processor_role_ambiguity": ["controller", "processor", "on behalf of", "joint controller"],
        "recipients_disclosure_gap": ["recipients", "third parties", "processors", "partners", "vendors"],
        "purpose_specificity_gap": ["purpose", "data category", "lawful basis", "processing purpose"],
    }
    normalized_sections = searched_sections or ["all reviewed privacy-notice sections"]
    normalized_headings = searched_headings or ["privacy notice", "data we collect", "how we use data", "your rights"]
    normalized_terms = searched_terms or issue_terms.get(issue, ["gdpr disclosure duty"])
    details = f"issue={issue}; blocker_reason={reason}"
    if missing_requirements:
        details = f"{details}; missing_requirements={', '.join(sorted(set(missing_requirements)))}"
    search_scope = (
        f"Searched sections: {', '.join(normalized_sections)}. "
        f"Searched headings: {', '.join(normalized_headings)}. "
        f"Searched terms: {', '.join(normalized_terms)}. "
        "Result: required disclosure not evidenced with a fully linked citation package."
    )
    scoped_absence_statement = _clean_absence_statement(issue)
    return FindingOut(
        id=f"publication_blocked:{audit_id}:{family}",
        section_id=f"systemic:{issue}",
        status="needs review",
        severity="medium",
        classification="publication_blocked",
        finding_type="publication_blocker",
        publish_flag="no",
        artifact_role="support_only",
        finding_level="none",
        publication_state="blocked",
        confidence=0.5,
        confidence_evidence=0.4,
        confidence_applicability=0.6,
        confidence_article_fit=0.4,
        confidence_synthesis=0.5,
        confidence_overall=0.5,
        source_scope="uncertain_scope",
        source_scope_confidence=0.6,
        assertion_level="not_assessable",
        publication_blocked=True,
        issue_key=issue,
        blocker_reason=reason,
        missing_requirements=missing_requirements or None,
        affected_sections=normalized_sections,
        where_evidence_found=normalized_sections,
        where_disclosure_missing=normalized_sections,
        severity_rationale=f"publication_blocker={reason}; issue={issue}; requires additional linked evidence packaging",
        legal_requirement="Publication blocker record for required Review→Published parity.",
        legal_rule="Publication blocker parity rule: keep issue visible but hold external publication until required linked evidence fields are complete.",
        legal_analysis=f"Packaging blocker for {issue}: {reason}.",
        gap_reasoning=f"Fact: {scoped_absence_statement} Law: publication parity requires linked evidence package. Breach: {reason}. Conclusion: keep as publication blocker until hydration is complete.",
        gap_note=f"publication_blocked: {details}. {search_scope}",
        remediation_note=(
            "Resolve all missing requirements, attach evidence-linked citations (evidence_id/source_type/source_ref), "
            "and rerun publication projection."
        ),
        document_evidence=scoped_absence_statement,
        policy_evidence_excerpt=scoped_absence_statement,
        citations=[],
    )


def _scoped_absence_publishable_row(
    *,
    audit_id: str,
    family: str,
    issue: str,
    reason: str,
    searched_sections: list[str] | None = None,
    searched_headings: list[str] | None = None,
    searched_terms: list[str] | None = None,
) -> FindingOut:
    sections = searched_sections or ["all reviewed privacy-notice sections"]
    anchors = _anchors_for_issue(issue, None)
    excerpt = _clean_absence_statement(issue)
    return FindingOut(
        id=f"projected_scoped_absence:{audit_id}:{family}",
        section_id=f"systemic:{issue}",
        status="gap",
        severity="high"
        if issue
        in {"missing_legal_basis", "missing_retention_period", "missing_transfer_notice", "profiling_disclosure_gap"}
        else "medium",
        classification="non_compliant",
        finding_type="systemic",
        publish_flag="yes",
        artifact_role="publishable_finding",
        finding_level="systemic",
        publication_state="publishable",
        issue_key=issue,
        primary_legal_anchor=anchors,
        citation_summary_text="Scoped absence statement from reviewed notice sections.",
        support_complete=False,
        omission_basis=True,
        policy_evidence_excerpt=excerpt,
        document_evidence=excerpt,
        legal_requirement=f"Rule: {', '.join(anchors)}.",
        legal_rule=f"Rule: {', '.join(anchors)}.",
        legal_analysis=f"Packaging incomplete ({reason}); substantive gap retained for publication with scoped absence statement.",
        gap_note=excerpt,
        remediation_note="Add explicit compliant disclosure language and attach evidence-linked citations for stronger traceability.",
        gap_reasoning=(
            f"Fact: {excerpt} "
            f"Law: {', '.join(anchors)}. "
            "Breach: required disclosure remains absent in reviewed text. "
            "Conclusion: publish as substantive notice-level gap pending fuller linkage package."
        ),
        severity_rationale=f"substantive_gap={issue}; packaging_gap={reason}; publication_kept_substantive=true",
        affected_sections=sections,
        where_evidence_found=sections,
        where_disclosure_missing=sections,
        source_scope="full_notice",
        source_scope_confidence=0.75,
        assertion_level="probable_document_gap",
        confidence=0.62,
        confidence_evidence=0.55,
        confidence_applicability=0.7,
        confidence_article_fit=0.65,
        confidence_synthesis=0.6,
        confidence_overall=0.6,
        citations=[],
    )


PUBLISHABLE_FALLBACK_ISSUES = {
    "missing_controller_identity",
    "missing_controller_contact",
    "missing_transfer_notice",
    "profiling_disclosure_gap",
    "article_14_indirect_collection_gap",
    "controller_processor_role_ambiguity",
    "recipients_disclosure_gap",
    "purpose_specificity_gap",
}


def _absence_mode_requirement(issue: str) -> list[str]:
    mapping = {
        "missing_controller_identity": ["GDPR Art. 13(1)(a)", "GDPR Art. 14(1)(a)"],
        "missing_controller_contact": ["GDPR Art. 13(1)(a)", "GDPR Art. 14(1)(a)"],
        "missing_transfer_notice": ["GDPR Art. 13(1)(f)", "GDPR Art. 14(1)(f)", "GDPR Arts. 44-46"],
        "profiling_disclosure_gap": ["GDPR Art. 13(2)(f)", "GDPR Art. 14(2)(g)", "GDPR Art. 22"],
        "article_14_indirect_collection_gap": [
            "GDPR Art. 14(1)",
            "GDPR Art. 14(2)",
            "GDPR Art. 14(3)",
            "GDPR Art. 14(5)",
        ],
        "controller_processor_role_ambiguity": ["GDPR Art. 13(1)(a)", "GDPR Art. 14(1)(a)"],
        "recipients_disclosure_gap": ["GDPR Art. 13(1)(e)", "GDPR Art. 14(1)(e)"],
        "purpose_specificity_gap": ["GDPR Art. 13(1)(c)", "GDPR Art. 14(1)(c)", "GDPR Art. 5(1)(b)"],
    }
    return mapping.get(issue, ["GDPR Art. 13", "GDPR Art. 14"])


def _absence_proof_is_secondary_eligible(
    issue: str,
    reasoning: str,
    missing_requirements: list[str],
) -> bool:
    invalidity_markers = {
        "inferred consent",
        "continued use",
        "indefinite retention",
        "without human intervention",
        "similarly significant",
        "legal effect",
        "invalid",
        "unlawful",
    }
    if any(marker in reasoning for marker in invalidity_markers):
        return False
    # Absence-proof should only backfill evidentiary-linkage style gaps, not legal-qualification failures.
    non_linkage_fields = {
        "citations.article_primary_fit",
        "citations.article_disallowed",
        "primary_legal_anchor",
        "legal_requirement",
        "gap_reasoning.flbc",
    }
    if set(missing_requirements) & non_linkage_fields:
        return False
    absence_markers = {"missing", "absent", "not disclosed", "not visible", "not clearly disclosed"}
    if not any(marker in reasoning for marker in absence_markers):
        return False
    # Keep Article 14 family first-class but still absence-secondary only.
    return issue in PUBLISHABLE_FALLBACK_ISSUES


def _absence_proof_publishable_row(
    *,
    audit_id: str,
    family: str,
    issue: str,
    searched_sections: list[str] | None = None,
    searched_headings: list[str] | None = None,
    searched_terms: list[str] | None = None,
    review_reasoning: str | None = None,
) -> FindingOut:
    sections = searched_sections or ["provided privacy-notice text"]
    anchor = _absence_mode_requirement(issue)
    legal_requirement = ", ".join(anchor)
    absence_proof = "No explicit required disclosure was found in the provided notice text for this obligation."
    reasoning = (
        f"Fact: {absence_proof} "
        f"Law: {legal_requirement} requires explicit disclosure for {issue}. "
        "Breach: the required disclosure is not present in the reviewed notice text. "
        "Conclusion: this is a traceable absence record supporting obligation validation; legal conclusion is determined by duty-level reconciliation."
    )
    return FindingOut(
        id=f"published_absence:{audit_id}:{family}",
        section_id=f"systemic:{issue}",
        status="gap",
        severity="high"
        if issue in {"missing_controller_contact", "missing_transfer_notice", "profiling_disclosure_gap"}
        else "medium",
        classification="referenced_but_unseen",
        finding_type="supporting_evidence",
        publish_flag="yes",
        artifact_role="support_only",
        finding_level="systemic",
        publication_state="publishable",
        confidence=0.64,
        confidence_evidence=0.58,
        confidence_applicability=0.72,
        confidence_article_fit=0.68,
        confidence_synthesis=0.62,
        confidence_overall=0.64,
        source_scope="full_notice",
        source_scope_confidence=0.8,
        assertion_level="excerpt_limited_gap",
        issue_key=issue,
        legal_requirement=legal_requirement,
        gap_reasoning=reasoning,
        severity_rationale=(
            "High severity due to core transparency obligation impact."
            if issue in {"missing_controller_contact", "missing_transfer_notice", "profiling_disclosure_gap"}
            else "Medium severity due to meaningful transparency gap with bounded scope."
        ),
        primary_legal_anchor=anchor,
        secondary_legal_anchors=None,
        document_evidence_refs=None,
        citation_summary_text=absence_proof,
        support_complete=False,
        omission_basis=True,
        policy_evidence_excerpt=absence_proof,
        document_evidence=absence_proof,
        legal_rule=legal_requirement,
        legal_analysis=reasoning,
        final_legal_outcome="partially_compliant",
        affected_sections=sections,
        where_evidence_found=sections,
        where_disclosure_missing=sections,
        gap_note=_sanitize_published_text(review_reasoning)
        or f"Required disclosure for {issue} is absent from reviewed notice sections.",
        remediation_note="Add explicit disclosure language mapped to the cited GDPR notice obligations.",
        citations=[],
    )


def _issue_key_from_section(section_id: str) -> str | None:
    if section_id.startswith("systemic:"):
        return section_id.split("systemic:", 1)[1]
    return None


def _fill_required_published_fields(row: FindingOut) -> FindingOut:
    issue = _infer_issue_from_text(_issue_key_from_section(row.section_id), row.gap_note, row.remediation_note)
    if not row.issue_key:
        row.issue_key = issue
    family_defaults = {
        "missing_transfer_notice": "State whether personal data are transferred internationally and identify the safeguard or transfer mechanism relied upon.",
        "profiling_disclosure_gap": "If profiling or comparable evaluation occurs, explain the logic involved and significant consequences where required.",
        "controller_processor_role_ambiguity": "Clarify when the organization acts as controller, processor, or similar role across processing contexts.",
    }
    if row.confidence_evidence is None:
        row.confidence_evidence = 0.72
    if row.confidence_applicability is None:
        row.confidence_applicability = 0.74
    if row.confidence_synthesis is None:
        row.confidence_synthesis = 0.7
    sev, sev_rationale = _severity_rule(issue, row.status, row.section_id, row.gap_reasoning or row.gap_note)
    if row.severity is None:
        row.severity = sev
    if row.severity_rationale is None or "family criticality" in (row.severity_rationale or "").lower():
        row.severity_rationale = sev_rationale
    if row.gap_reasoning is None:
        row.gap_reasoning = row.gap_note or "Gap confirmed by final disposition map and evidence-linked projection."
    if row.remediation_note is None and issue:
        row.remediation_note = family_defaults.get(
            issue, "Add explicit GDPR-compliant notice language for the missing disclosure."
        )
    if row.support_complete is None:
        row.support_complete = len(row.citations) > 0
    if row.omission_basis is None:
        row.omission_basis = row.status in {"gap", "partial"}
    if row.source_scope is None:
        row.source_scope = "full_notice"
    if row.assertion_level is None:
        row.assertion_level = "probable_document_gap"
    if row.confidence_overall is None:
        row.confidence_overall = row.confidence if row.confidence is not None else 0.66
    evidence_linkage = bool(row.citations) and all(
        c.evidence_id is not None and c.source_type is not None and c.source_ref is not None for c in row.citations
    )
    evidence_quality = 0.35
    if row.policy_evidence_excerpt:
        evidence_quality += 0.2
    if row.document_evidence_refs:
        evidence_quality += 0.2
    if evidence_linkage:
        evidence_quality += 0.25
    traceability_quality = 0.25
    if row.affected_sections:
        traceability_quality += 0.25
    if row.where_evidence_found and row.where_disclosure_missing:
        traceability_quality += 0.25
    if row.source_scope and row.assertion_level:
        traceability_quality += 0.25
    article_fit_quality = (
        row.confidence_article_fit
        if row.confidence_article_fit is not None
        else (0.8 if row.primary_legal_anchor else 0.5)
    )
    contradiction_quality = 0.0 if "contradict" in ((row.gap_reasoning or "").lower()) else 1.0
    completeness_quality = 0.0 if _hydration_missing(row) else 1.0
    substantive_ok = bool(row.primary_legal_anchor) and (bool(row.citations) or bool(row.policy_evidence_excerpt))
    derived_confidence = (
        0.35 * min(1.0, evidence_quality)
        + 0.2 * min(1.0, traceability_quality)
        + 0.2 * min(1.0, article_fit_quality)
        + 0.1 * contradiction_quality
        + 0.15 * completeness_quality
    )
    row.confidence_overall = round(max(0.2, min(0.95, derived_confidence)), 2)
    if (
        (not row.policy_evidence_excerpt)
        or (not row.citations)
        or any(c.evidence_id is None or c.source_type is None or c.source_ref is None for c in row.citations)
    ):
        row.confidence_overall = min(row.confidence_overall or 0.55, 0.55)
    if substantive_ok and row.confidence_overall < 0.55:
        row.confidence_overall = 0.58
    if evidence_quality >= 0.75 and row.confidence_overall < 0.55:
        row.confidence_overall = 0.6
    if not row.primary_legal_anchor:
        row.primary_legal_anchor = (
            [f"GDPR Article {row.citations[0].article_number}"] if row.citations else ["GDPR Article 13"]
        )
    row.primary_legal_anchor = _anchors_for_issue(issue, row.primary_legal_anchor)
    if not (row.citation_summary_text or "").strip():
        row.citation_summary_text = "Evidence-linked publication record."
    if not (row.legal_requirement or "").strip():
        row.legal_requirement = f"Rule: {', '.join(row.primary_legal_anchor)}."
    excerpt = _sanitize_published_text(row.policy_evidence_excerpt) or ""
    if (
        excerpt
        and "reviewed sections show processing context but do not contain required disclosure language"
        in excerpt.lower()
    ):
        excerpt = ""
    if not excerpt and row.citations:
        first = row.citations[0]
        quote = _sanitize_published_text(first.excerpt) or ""
        if quote:
            excerpt = quote
    if not excerpt:
        excerpt = _clean_absence_statement(issue)
    if not row.citations and not _is_clean_absence_statement(excerpt):
        excerpt = _clean_absence_statement(issue)
    if _has_banned_output_tokens(excerpt):
        excerpt = _clean_absence_statement(issue)
    row.policy_evidence_excerpt = excerpt
    row.document_evidence = _sanitize_published_text(row.policy_evidence_excerpt)
    row.legal_rule = _sanitize_published_text(row.legal_requirement)
    row.legal_analysis = _sanitize_published_text(row.gap_reasoning or row.gap_note)
    _ensure_flbc_reasoning(row, issue)
    has_primary_article, has_disallowed_article = _citation_article_findings(issue, row.citations)
    if has_disallowed_article or not has_primary_article:
        row.confidence_overall = min(row.confidence_overall or 0.55, 0.5)
        if row.severity == "high":
            row.severity = "medium"
    row.classification = _published_legal_conclusion(row.status, issue, row.classification)
    row.final_legal_outcome = _final_legal_outcome_for_row(row)
    explicit_violation_text = f"{row.document_evidence or ''} {row.legal_analysis or ''}".lower()
    explicit_violation_markers = {
        "consent inferred",
        "retained indefinitely",
        "no specific mechanism disclosed",
        "automated profiling",
    }
    if row.final_legal_outcome == "not_assessable_from_provided_text" and any(
        m in explicit_violation_text for m in explicit_violation_markers
    ):
        row.final_legal_outcome = "not_assessable_from_provided_text"
    if row.classification != "publication_blocked" and not _can_publish_row(row):
        row.classification = "publication_blocked"
        row.publication_blocked = True
        row.blocker_reason = row.blocker_reason or "publication contract failed"
        row.missing_requirements = row.missing_requirements or ["legal_rule_or_analysis_or_evidence_bundle"]
    return row


def _to_audit_ready_view(row: FindingOut) -> FindingOut:
    row.publish_flag = None
    row.artifact_role = None
    row.finding_level = None
    row.publication_state = None
    row.confidence = None
    row.confidence_evidence = None
    row.confidence_applicability = None
    row.confidence_synthesis = None
    row.missing_from_section = None
    row.missing_from_document = None
    row.not_visible_in_excerpt = None
    row.obligation_under_review = None
    row.collection_mode = None
    row.applicability_status = None
    row.visibility_status = None
    row.section_vs_document_scope = None
    row.missing_fact_if_unresolved = None
    row.support_complete = None
    row.omission_basis = None
    row.source_scope_confidence = None
    row.referenced_unseen_sections = None
    return row


def _no_banned_debug_tokens(rows: list[FindingOut]) -> bool:
    for row in [r for r in rows if r.classification != "publication_blocked"]:
        fields = [
            row.document_evidence,
            row.policy_evidence_excerpt,
            row.legal_analysis,
            row.legal_rule,
            row.citation_summary_text,
            row.gap_note,
        ]
        if any(_has_banned_output_tokens(v) for v in fields):
            return False
        for c in row.citations:
            if _has_banned_output_tokens(c.excerpt):
                return False
    return True


def _every_published_finding_has_valid_evidence(rows: list[FindingOut]) -> bool:
    published = [r for r in rows if r.classification != "publication_blocked"]
    return all(_has_valid_evidence_bundle(r) for r in published)


def _no_published_controller_identity_false_positive(
    rows: list[FindingOut], backing_rows: list[Finding], evidence_by_id: dict[str, EvidenceRecord]
) -> bool:
    if not _controller_identity_disclosed_in_document(backing_rows, evidence_by_id):
        return True
    return not any(
        r.section_id in {"systemic:missing_controller_identity", "systemic:missing_controller_contact"} for r in rows
    )


def _no_explicit_retention_violation_is_suppressed(rows: list[FindingOut], backing_rows: list[Finding]) -> bool:
    corpus = " ".join((r.gap_note or "") + " " + (r.policy_evidence_excerpt or "") for r in backing_rows).lower()
    has_explicit_retention = any(
        t in corpus
        for t in {
            "retained indefinitely",
            "archived datasets may be retained indefinitely",
            "retained for extended periods",
        }
    )
    if not has_explicit_retention:
        return True
    for r in rows:
        if r.section_id == "systemic:missing_retention_period":
            return r.final_legal_outcome == "non_compliant" and r.classification != "publication_blocked"
    return False


def _no_explicit_legal_basis_invalidity_is_marked_not_assessable(
    rows: list[FindingOut], backing_rows: list[Finding]
) -> bool:
    corpus = " ".join((r.gap_note or "") + " " + (r.policy_evidence_excerpt or "") for r in backing_rows).lower()
    has_explicit_invalid = any(
        t in corpus
        for t in {
            "consent inferred from interactions",
            "consent inferred from continued use",
            "legitimate interests where applicable",
        }
    )
    if not has_explicit_invalid:
        return True
    return all(
        not (
            r.section_id == "systemic:missing_legal_basis"
            and r.final_legal_outcome == "not_assessable_from_provided_text"
        )
        for r in rows
    )


def _no_explicit_profiling_gap_lacks_evidence(rows: list[FindingOut], backing_rows: list[Finding]) -> bool:
    corpus = " ".join((r.gap_note or "") + " " + (r.policy_evidence_excerpt or "") for r in backing_rows).lower()
    has_profiling_signal = any(
        t in corpus for t in {"profil", "risk scores", "content recommendations", "service availability influenced"}
    )
    if not has_profiling_signal:
        return True
    for r in rows:
        if r.section_id == "systemic:profiling_disclosure_gap":
            return _has_valid_evidence_bundle(r)
    return False


def _release_validator(
    rows: list[FindingOut], backing_rows: list[Finding], evidence_by_id: dict[str, EvidenceRecord]
) -> tuple[bool, str | None]:
    if not _no_banned_debug_tokens(rows):
        return False, "banned debug tokens detected in client-visible output"
    if not _every_published_finding_has_valid_evidence(rows):
        return False, "published finding without valid evidence bundle"
    if not _no_published_controller_identity_false_positive(rows, backing_rows, evidence_by_id):
        return False, "controller identity/contact false positive detected"
    if not _no_explicit_retention_violation_is_suppressed(rows, backing_rows):
        return False, "explicit retention violation was suppressed"
    if not _no_explicit_legal_basis_invalidity_is_marked_not_assessable(rows, backing_rows):
        return False, "explicit legal-basis invalidity marked not-assessable"
    if not _no_explicit_profiling_gap_lacks_evidence(rows, backing_rows):
        return False, "explicit profiling gap lacks valid evidence bundle"
    return True, None


def _reconciliation_blockers(
    audit: Audit,
    decision_map: dict[str, dict[str, str | bool | list[str] | float]] | None,
    published_rows: list[Finding],
    projected_rows: list[FindingOut],
    ignored_families: set[str] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if audit.status == "review_required" and (published_rows or projected_rows):
        blockers.append("review_required audit must not expose published findings")
    if not decision_map:
        return blockers
    core_families = ("controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right")
    for family in core_families:
        status = str((decision_map.get(family, {}) or {}).get("status") or "")
        if status in {"unresolved_internal_error", "blocked"} and (published_rows or projected_rows):
            blockers.append(f"core blocker present for {family} while published findings exist")
    for family, item in decision_map.items():
        if family.startswith("_") or not isinstance(item, dict):
            continue
        if str(item.get("publication_recommendation") or "") != "publish":
            continue
        if str(item.get("status") or "") not in {"gap", "referenced_but_unseen"}:
            continue
        if ignored_families and family in ignored_families:
            continue
        expected_issue = _issue_for_family(family, item)
        expected_section_id = f"systemic:{expected_issue}" if expected_issue else None
        has_projection = any(
            (
                expected_section_id is not None
                and p.section_id == expected_section_id
                and p.classification != "publication_blocked"
            )
            or p.id.endswith(f":{family}")
            for p in projected_rows
        )
        has_persisted_family = any(
            (_issue_from_finding_section(r.section_id) == expected_issue)
            or (
                _infer_issue_from_text(_issue_from_finding_section(r.section_id), r.gap_note, r.remediation_note)
                == expected_issue
            )
            or (_infer_issue_from_text(None, r.obligation_under_review, r.gap_note) == expected_issue)
            or (
                expected_issue == "controller_processor_role_ambiguity"
                and "controller" in ((r.obligation_under_review or "").lower() + " " + (r.gap_note or "").lower())
                and "processor" in ((r.obligation_under_review or "").lower() + " " + (r.gap_note or "").lower())
            )
            or (
                expected_issue
                and expected_issue in ((r.gap_note or "").lower() + " " + (r.remediation_note or "").lower())
            )
            for r in (published_rows or [])
        )
        explicit_blocker = any(
            _is_substantive_publication_blocker(p) and p.issue_key == expected_issue for p in projected_rows
        )
        if not has_projection and not has_persisted_family and not explicit_blocker:
            blockers.append(f"publish recommendation for {family} has no materialized finding or explicit blocker")
    return blockers


def _parity_blocker_rows(
    audit_id: str,
    decision_map: dict[str, dict[str, str | bool | list[str] | float]] | None,
    projected_rows: list[FindingOut],
    published_rows: list[Finding] | None,
) -> list[FindingOut]:
    if not decision_map:
        return []
    blockers: list[FindingOut] = []
    for family, default_issue in _family_issue_map().items():
        item = decision_map.get(family, {}) or {}
        issue = _issue_for_family(family, item) if family == "controller_identity_contact" else default_issue
        if str(item.get("status") or "") not in {"gap", "referenced_but_unseen"}:
            continue
        if str(item.get("publication_recommendation") or "") != "publish":
            continue
        has_projection = any(
            p.section_id == f"systemic:{issue}" for p in projected_rows if p.classification != "publication_blocked"
        )
        has_persisted = any(_issue_from_finding_section(r.section_id) == issue for r in (published_rows or []))
        if has_projection or has_persisted:
            continue
        blocker_reason = str(item.get("blocker_reason") or "incomplete hydration")
        missing_requirements = [str(v) for v in (item.get("missing_requirements") or []) if isinstance(v, str)]
        searched_sections = [
            str(v) for v in (item.get("searched_sections") or item.get("section_ids") or []) if isinstance(v, str)
        ]
        searched_headings = [str(v) for v in (item.get("searched_headings") or []) if isinstance(v, str)]
        searched_terms = [str(v) for v in (item.get("searched_terms") or []) if isinstance(v, str)]
        if not missing_requirements:
            missing_requirements = [
                "policy_evidence_excerpt",
                "document_evidence_refs",
                "citations.evidence_id",
                "citations.source_type",
                "citations.source_ref",
            ]
        substantive_publishable = issue in {
            "missing_legal_basis",
            "missing_retention_period",
            "missing_transfer_notice",
            "profiling_disclosure_gap",
            "recipients_disclosure_gap",
            "purpose_specificity_gap",
        }
        if substantive_publishable:
            blockers.append(
                _scoped_absence_publishable_row(
                    audit_id=audit_id,
                    family=family,
                    issue=issue,
                    reason=blocker_reason,
                    searched_sections=searched_sections,
                    searched_headings=searched_headings,
                    searched_terms=searched_terms,
                )
            )
        else:
            blockers.append(
                _publication_blocker_row(
                    audit_id=audit_id,
                    family=family,
                    issue=issue,
                    reason=blocker_reason,
                    missing_requirements=missing_requirements,
                    searched_sections=searched_sections,
                    searched_headings=searched_headings,
                    searched_terms=searched_terms,
                )
            )
    return blockers


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/groups", response_model=GroupOut)
def create_group(
    payload: GroupCreate,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupOut:
    group = DocumentGroup(user_id=user_id, name=payload.name.strip())
    db.add(group)
    db.commit()
    db.refresh(group)
    return GroupOut(
        id=group.id, name=group.name, created_at=group.created_at, versions=[], latest_compliance_score=None
    )


@router.get("/groups", response_model=list[GroupOut])
def list_groups(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[GroupOut]:
    groups = db.scalars(
        select(DocumentGroup).where(DocumentGroup.user_id == user_id).order_by(DocumentGroup.created_at.desc())
    ).all()
    if not groups:
        return []
    group_ids = [g.id for g in groups]
    audits = db.scalars(
        select(Audit)
        .where(Audit.user_id == user_id, Audit.document_group_id.in_(group_ids), Audit.version_number.is_not(None))
        .order_by(Audit.document_group_id.asc(), Audit.version_number.asc())
    ).all()
    versions_by_group: dict[str, list[GroupVersionOut]] = {g.id: [] for g in groups}
    for audit in audits:
        versions_by_group[audit.document_group_id or ""].append(
            GroupVersionOut(
                document_id=audit.document_id,
                audit_id=audit.id,
                version_number=int(audit.version_number or 0),
                compliance_score=audit.compliance_score,
                created_at=audit.started_at,
            )
        )
    out: list[GroupOut] = []
    for group in groups:
        versions = versions_by_group.get(group.id, [])
        latest_score = versions[-1].compliance_score if versions else None
        out.append(
            GroupOut(
                id=group.id,
                name=group.name,
                created_at=group.created_at,
                versions=versions,
                latest_compliance_score=latest_score,
            )
        )
    return out


@router.patch("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: str,
    payload: GroupUpdate,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupOut:
    group = _get_owned_group_or_404(db, group_id, user_id)
    group.name = payload.name.strip()
    db.add(group)
    db.commit()
    db.refresh(group)
    return GroupOut(
        id=group.id, name=group.name, created_at=group.created_at, versions=[], latest_compliance_score=None
    )


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(
    group_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    _get_owned_group_or_404(db, group_id, user_id)
    db.execute(
        update(Audit)
        .where(Audit.document_group_id == group_id, Audit.user_id == user_id)
        .values(document_group_id=None, version_number=None)
    )
    db.execute(
        DocumentGroup.__table__.delete().where(
            DocumentGroup.id == group_id,
            DocumentGroup.user_id == user_id,
        )
    )
    db.commit()
    return None


@router.post("/groups/{group_id}/versions", response_model=GroupVersionOut)
def assign_group_version(
    group_id: str,
    payload: GroupVersionCreate,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GroupVersionOut:
    _get_owned_group_or_404(db, group_id, user_id, for_update=True)
    audit = db.scalar(
        select(Audit)
        .where(Audit.user_id == user_id, Audit.document_id == payload.document_id)
        .order_by(Audit.started_at.desc())
        .with_for_update()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found for document")
    version_number = _assign_next_version_number(db, group_id, user_id)
    audit.document_group_id = group_id
    audit.version_number = version_number
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return GroupVersionOut(
        document_id=audit.document_id,
        audit_id=audit.id,
        version_number=version_number,
        compliance_score=audit.compliance_score,
        created_at=audit.started_at,
    )


def _create_remediation_items(audit_id: str, compliance_score: int, db: Session) -> None:
    """Build RemediationItem rows from published findings. Idempotent — skips if already exist."""
    existing = db.query(RemediationItem).filter(RemediationItem.audit_id == audit_id).first()
    if existing:
        return

    rows = canonical_published_findings(db, audit_id)
    if not rows:
        return

    gap_entries: list[tuple[str, str, str, str, str]] = []  # (issue_key, issue_label, severity, finding_id, section_id)
    seen_keys: set[str] = set()

    for row in rows:
        issue_key = _derive_issue_key_for_published_row(row)
        if not issue_key or issue_key in seen_keys:
            continue
        try:
            issue_label = _require_issue_label(issue_key)
        except ValueError:
            continue
        seen_keys.add(issue_key)
        sev = (row.severity or "low").lower()
        if sev not in {"high", "medium", "low"}:
            sev = "low"
        gap_entries.append((issue_key, issue_label, sev, row.id, row.section_id))

    if not gap_entries:
        return

    _sev_rank = {"high": 1, "medium": 2, "low": 3}
    gap_entries.sort(key=lambda x: (_sev_rank.get(x[2], 3), x[1]))

    total_gaps = len(gap_entries)
    to_distribute = 100 - compliance_score
    per_item = round(to_distribute / total_gaps) if total_gaps > 0 else 0

    for i, (issue_key, issue_label, sev, finding_id, section_id) in enumerate(gap_entries):
        if i == total_gaps - 1:
            impact = max(0, to_distribute - (total_gaps - 1) * per_item)
        else:
            impact = per_item
        db.add(
            RemediationItem(
                audit_id=audit_id,
                finding_id=finding_id,
                issue_key=issue_key,
                issue_label=issue_label,
                severity=sev,
                score_impact_points=impact,
                order_index=i + 1,
                section_id=section_id,
            )
        )

    db.commit()


_REMEDIATION_SYSTEM_PROMPT = (
    "You are a GDPR compliance drafter. Your task is to provide a model GDPR-compliant clause "
    "that an organization can adapt to fix the identified gap. You must use bracketed placeholders "
    "for any organization-specific details that cannot be determined from context "
    "(e.g., [Organization Name], [X years], [specific purpose], [supervisory authority name]). "
    "Never guess or invent specific retention periods, company names, or jurisdictions. "
    "Return only the suggested clause text — no preamble, no explanation, no JSON."
)


@router.post("/audits", response_model=AuditOut)
def create_audit(
    payload: AuditCreate,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditOut:
    if payload.group_id:
        _get_owned_group_or_404(db, payload.group_id, user_id)
    audit = Audit(document_id=payload.document_id, user_id=user_id, status="pending")
    db.add(audit)
    db.commit()
    db.refresh(audit)

    with orchestration_audit_creation_latency_seconds.time():
        try:
            audit = run_audit(db, audit)
        except Exception as exc:
            db.rollback()
            audit.status = "failed"
            db.add(audit)
            db.commit()
            _record_api_request("/audits", "POST", "502")
            raise HTTPException(status_code=502, detail=f"Audit failed: {exc}")

    orchestration_audit_created_total.inc()
    _record_api_request("/audits", "POST", "200")

    if audit.status == "complete" and (audit.compliance_score or 0) < 100:
        try:
            _create_remediation_items(audit.id, audit.compliance_score or 0, db)
        except Exception:
            pass  # remediation items are non-critical; don't fail the audit response
    if payload.group_id and audit.status == "complete" and audit.compliance_score is not None:
        try:
            _assign_audit_to_group_atomic(db, audit, payload.group_id, user_id)
            db.commit()
        except Exception as exc:
            db.rollback()
            _record_api_request("/audits", "POST", "500")
            raise HTTPException(status_code=500, detail=f"Failed to assign version: {exc}")
        db.refresh(audit)

    return AuditOut.model_validate(audit, from_attributes=True)


@router.get("/audits/{audit_id}", response_model=AuditOut)
def get_audit(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AuditOut:
    audit = _get_owned_audit_or_404(db, audit_id, user_id)
    return AuditOut.model_validate(audit, from_attributes=True)


# ---------------------------------------------------------------------------
# Final-consolidation helpers — called inside get_findings() before return
# ---------------------------------------------------------------------------

# Notice-wide obligations: prefer the systemic finding; merge local evidence into it.
_NOTICE_WIDE_ISSUE_KEYS: frozenset[str] = frozenset(
    {
        "missing_legal_basis",
        "missing_retention_period",
        "missing_rights_notice",
        "missing_complaint_right",
        "missing_controller_identity",
        "missing_controller_contact",
        "controller_identity_contact",
    }
)

_SEVERITY_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}


def _pick_best_evidence_excerpt(excerpts: list[str | None]) -> str | None:
    """Prefer non-fallback text, then longer text."""
    specific = [e for e in excerpts if e and not e.lower().startswith("based on the reviewed notice")]
    if specific:
        return max(specific, key=len)
    fallbacks = [e for e in excerpts if e]
    return max(fallbacks, key=len) if fallbacks else None


def _pick_best_note(texts: list[str | None]) -> str | None:
    """Prefer specific (non-generic) text; among equals choose longer."""
    _GENERIC_NOTE_PREFIXES = (
        "based on the reviewed notice",
        "required gdpr",
        "update the notice to include",
    )
    specific = [t for t in texts if t and not any(t.lower().startswith(p) for p in _GENERIC_NOTE_PREFIXES)]
    if specific:
        return max(specific, key=len)
    fallbacks = [t for t in texts if t]
    return max(fallbacks, key=len) if fallbacks else None


def _merge_citation_groups(citation_lists: list[list[CitationOut]]) -> list[CitationOut]:
    """Deduplicate citations across groups by article_number."""
    seen: set[str] = set()
    merged: list[CitationOut] = []
    for group in citation_lists:
        for c in group:
            key = c.article_number or c.chunk_id
            if key not in seen:
                seen.add(key)
                merged.append(c)
    return merged


def _merge_published_group(group: list[PublishedFindingOut], issue_key: str) -> PublishedFindingOut:
    """Merge a group of findings for the same issue_key into one authoritative finding."""
    systemic = [f for f in group if f.section_id.startswith("systemic:")]
    local = [f for f in group if not f.section_id.startswith("systemic:")]

    # Primary selection
    if issue_key in _NOTICE_WIDE_ISSUE_KEYS and systemic:
        primary = max(systemic, key=lambda f: f.confidence_overall or 0)
    else:
        primary = max(
            group,
            key=lambda f: (f.confidence_overall or 0, 1 if f.section_id.startswith("systemic:") else 0),
        )

    # Collect all source section IDs (deduplicated, ordered)
    all_sids: list[str] = list(dict.fromkeys(sid for f in group for sid in (f.affected_sections or [f.section_id])))

    best_sev = max(
        (f.severity for f in group),
        key=lambda s: _SEVERITY_RANK.get(s or "medium", 2),
        default=primary.severity,
    )
    best_conf = max((f.confidence_overall or 0 for f in group), default=0) or None

    return primary.model_copy(
        update={
            "severity": best_sev,
            "confidence_overall": best_conf,
            "confidence_level": _derive_confidence_level(best_conf or 0.7),
            "affected_sections": all_sids,
            "policy_evidence_excerpt": (
                _pick_best_evidence_excerpt([f.policy_evidence_excerpt for f in group])
                or primary.policy_evidence_excerpt
            ),
            "gap_note": _pick_best_note([f.gap_note for f in group]) or primary.gap_note,
            "remediation_note": _pick_best_note([f.remediation_note for f in group]) or primary.remediation_note,
            "citations": _merge_citation_groups([f.citations for f in group]),
        }
    )


def _consolidate_by_issue_key(findings: list[PublishedFindingOut]) -> list[PublishedFindingOut]:
    """Ensure at most one published finding per canonical issue_key.

    - Notice-wide duties: systemic finding wins; local evidence is merged in.
    - Section-specific duties: highest-confidence finding wins; sections are merged.
    - Always: strongest severity, best evidence, deduplicated citations.
    """
    if len(findings) <= 1:
        return findings
    groups: dict[str, list[PublishedFindingOut]] = {}
    order: list[str] = []
    for f in findings:
        if f.issue_key not in groups:
            groups[f.issue_key] = []
            order.append(f.issue_key)
        groups[f.issue_key].append(f)
    return [groups[k][0] if len(groups[k]) == 1 else _merge_published_group(groups[k], k) for k in order]


@router.get("/audits/{audit_id}/findings", response_model=list[PublishedFindingOut])
def get_findings(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PublishedFindingOut]:
    audit = _get_owned_audit_or_404(db, audit_id, user_id)
    if audit.status == "review_required":
        raise HTTPException(status_code=409, detail="Published findings blocked: audit requires review")
    known_evidence_ids = _known_evidence_ids(db, audit_id)
    evidence_by_chunk = _evidence_by_chunk_ref(db, audit_id)
    rows = canonical_published_findings(db, audit_id)
    if not rows:
        return []
    out: list[PublishedFindingOut] = []
    evidence_ids = known_evidence_ids
    seen: set[str] = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        issue_key = _derive_issue_key_for_published_row(row)
        if not issue_key:
            # canonical_published_findings already ran the quality gate; if no
            # issue_key is derivable the row is silently excluded — no DB writes.
            continue
        issue_label = _require_issue_label(issue_key)
        policy_excerpt = _sanitize_published_text(row.policy_evidence_excerpt)
        # Strip conclusion strings and machine-generated text — they are not document
        # evidence and must not appear in the evidence_from_notice field.
        _CONCLUSION_PREFIXES = (
            "no explicit",
            "no right to",
            "no complete",
            "no clear",
            "no actionable",
            "no third-country",
            "no profiling",
            "no categories of",
            "no explicit disclosure was found",
            "processing purposes are described but not",
            "reviewed sections show processing context",
            "gdpr compliance assessment",
            "required gdpr article anchor",
            "for issue ",
            "primary legal anchor",
            "obligation is missing",
            "legal gate",
        )
        _CONCLUSION_SUBSTRINGS = (
            "gdpr compliance assessment",
            "required gdpr article anchor",
            "primary legal anchor",
            "obligation is missing",
            "for issue ",
        )
        if policy_excerpt:
            lower_exc = policy_excerpt.lower()
            if lower_exc.startswith(_CONCLUSION_PREFIXES) or any(s in lower_exc for s in _CONCLUSION_SUBSTRINGS):
                policy_excerpt = None
        if not policy_excerpt:
            citation_excerpt = next(
                (_sanitize_published_text(c.excerpt) for c in row.citations if _sanitize_published_text(c.excerpt)),
                None,
            )
            fallback_excerpt = (
                citation_excerpt
                or _sanitize_published_text(row.citation_summary_text)
                or _sanitize_published_text(row.gap_reasoning)
            )
            policy_excerpt = (
                f"Based on the reviewed notice: {fallback_excerpt}"
                if fallback_excerpt
                else "Based on the reviewed notice: no explicit compliant disclosure excerpt was found."
            )
        eff_confidence_overall = (
            row.confidence_overall if row.confidence_overall is not None else (row.confidence or 0.7)
        )
        domain_rows = getattr(row, "_domain_merged_rows", None)
        citation_rows = domain_rows if domain_rows else [row]
        domain_anchors = getattr(row, "_domain_merged_anchors", None)
        if domain_rows:
            all_domain_sids = list(
                dict.fromkeys(
                    sid for dr in domain_rows for sid in (getattr(dr, "_merged_section_ids", None) or [dr.section_id])
                )
            )
        else:
            all_domain_sids = getattr(row, "_merged_section_ids", None) or [row.section_id]
        out.append(
            PublishedFindingOut(
                id=row.id,
                section_id=row.section_id,
                issue_key=issue_key,
                issue_label=issue_label,
                status=row.status or "gap",
                severity=row.severity or "medium",
                confidence_level=_derive_confidence_level(eff_confidence_overall),
                confidence_overall=eff_confidence_overall,
                affected_sections=all_domain_sids,
                policy_evidence_excerpt=policy_excerpt,
                legal_requirement=_sanitize_published_text(row.legal_requirement),
                primary_legal_anchor=domain_anchors or _deserialize_json_list(row.primary_legal_anchor),
                gap_note=_sanitize_published_text(
                    _apply_family_fallback(issue_key, row.gap_note, row.remediation_note)[0]
                )
                or (
                    FAMILY_FALLBACK_COPY.get(issue_key or "", (None, None))[0]
                    or _OMISSION_SUMMARY_MAP.get(
                        issue_key or "",
                        "The required GDPR transparency disclosure is missing or insufficient for this finding.",
                    )
                ),
                omission_statement=_sanitize_published_text(row.citation_summary_text) or None,
                gap_reasoning=_sanitize_published_text(row.gap_reasoning),
                remediation_note=_sanitize_published_text(
                    _apply_family_fallback(issue_key, row.gap_note, row.remediation_note)[1]
                )
                or (
                    FAMILY_FALLBACK_COPY.get(issue_key or "", (None, None))[1]
                    or "Update the notice to include a clear and specific disclosure addressing this finding."
                ),
                severity_rationale=_sanitize_published_text(row.severity_rationale),
                citation_summary_text=_sanitize_published_text(row.citation_summary_text)
                or _OMISSION_SUMMARY_MAP.get(
                    issue_key,
                    f"The notice does not provide required disclosure for {(issue_key or 'this obligation').replace('_', ' ')}.",
                ),
                citations=[
                    _citation_out(c, evidence_by_chunk.get(c.chunk_id))
                    for dr in citation_rows
                    for c in dr.citations
                    if _is_real_evidence_ref(c.chunk_id)
                    and (f"evi:chunk:{c.chunk_id}" in evidence_ids or c.chunk_id in evidence_by_chunk)
                    and c.chunk_id in evidence_by_chunk
                ],
            )
        )
    # canonical_published_findings already consolidates to one row per issue key via
    # _consolidate_finding_rows.  No second consolidation pass is needed here.
    return out


@router.get("/audits/{audit_id}/analysis", response_model=list[AnalysisItemOut])
def get_analysis(
    audit_id: str,
    status: str | None = Query(default=None, alias="status"),
    issue_type: str | None = Query(default=None),
    artifact_role: str | None = Query(default=None),
    section_id: str | None = Query(default=None),
    analysis_stage: str | None = Query(default=None),
    debug: bool = Query(default=False),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AnalysisItemOut]:
    _get_owned_audit_or_404(db, audit_id, user_id)
    query = (
        select(AuditAnalysisItem)
        .options(selectinload(AuditAnalysisItem.citations))
        .where(AuditAnalysisItem.audit_id == audit_id)
    )
    if status:
        query = query.where(AuditAnalysisItem.status_candidate == status)
    if issue_type:
        query = query.where(AuditAnalysisItem.issue_type == issue_type)
    if artifact_role:
        query = query.where(AuditAnalysisItem.artifact_role == artifact_role)
    if section_id:
        query = query.where(AuditAnalysisItem.section_id == section_id)
    if analysis_stage:
        query = query.where(AuditAnalysisItem.analysis_stage == analysis_stage)
    rows = db.scalars(query.order_by(AuditAnalysisItem.section_id.asc(), AuditAnalysisItem.id.asc())).all()
    if not debug:
        rows = [row for row in rows if not row.section_id.startswith("ledger:")]
    return [
        AnalysisItemOut(
            id=row.id,
            section_id=row.section_id,
            analysis_stage=row.analysis_stage,
            analysis_type=row.analysis_type,
            issue_type=row.issue_type,
            status_candidate=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[0],
            classification_candidate=row.classification_candidate,
            artifact_role=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[1],
            finding_level_candidate=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[2],
            publication_state_candidate=_normalize_internal_state(
                row.classification_candidate,
                row.status_candidate,
                row.artifact_role,
                row.finding_level_candidate,
                row.publication_state_candidate,
            )[3],
            analysis_outcome=row.analysis_outcome,
            candidate_issue=row.candidate_issue,
            policy_evidence_excerpt=row.policy_evidence_excerpt,
            legal_requirement_candidate=row.legal_requirement_candidate,
            article_candidates=_deserialize_json_list(row.article_candidates),
            retrieval_summary=row.retrieval_summary,
            qualification_summary=row.qualification_summary,
            evidence_sufficiency=row.evidence_sufficiency,
            applicability=row.applicability,
            citation_fit_status=row.citation_fit_status,
            applicability_status=row.applicability_status,
            contradiction_status=row.contradiction_status,
            citation_fit=row.citation_fit,
            support_role=row.support_role,
            source_scope=row.source_scope,
            excerpt_scope_facts=row.excerpt_scope_facts,
            referenced_unseen_sections=_deserialize_json_list(row.referenced_unseen_sections),
            suppression_reason=_sanitize_published_text(row.suppression_reason),
            publishability_candidate=row.publishability_candidate,
            confidence=row.confidence,
            confidence_evidence=row.confidence_evidence,
            confidence_applicability=row.confidence_applicability,
            confidence_article_fit=row.confidence_article_fit,
            confidence_overall=row.confidence_overall,
            finding_status=row.finding_status,
            finding_classification=row.finding_classification,
            finding_severity=row.finding_severity,
            gap_note=_sanitize_published_text(
                _apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[0]
            ),
            remediation_note=_sanitize_published_text(
                _apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)[1]
            ),
            citations=[
                AnalysisCitationOut(
                    chunk_id=c.chunk_id,
                    article_number=c.article_number,
                    paragraph_ref=c.paragraph_ref,
                    article_title=c.article_title,
                    excerpt=c.excerpt,
                )
                for c in row.citations
            ],
        )
        for row in rows
    ]


def _build_finding_review_item(row: Finding, *, debug: bool) -> ReviewItemOut:
    norm = _normalize_internal_state(
        row.classification, row.status, row.artifact_role, row.finding_level, row.publication_state
    )
    issue = _issue_from_finding_section(row.section_id)
    gap, rem = _apply_family_fallback(issue, row.gap_note, row.remediation_note)
    raw_supp = row.gap_note if row.publication_state in {"blocked", "internal_only"} else None
    if debug:
        suppression_reason = _sanitize_review_text(raw_supp, debug=True)
    else:
        suppression_reason = _clean_suppression_reason(raw_supp) or _sanitize_review_text(raw_supp, debug=False)
    return ReviewItemOut(
        item_kind="finding",
        id=row.id,
        section_id=row.section_id,
        issue_type=issue,
        status=norm[0],
        classification=row.classification,
        artifact_role=norm[1],
        finding_level=norm[2],
        publication_state=norm[3],
        suppression_reason=suppression_reason,
        completeness_map=row.legal_requirement
        if row.legal_requirement and "completeness" in row.legal_requirement
        else None,
        gap_note=_sanitize_review_text(gap, debug=debug),
        remediation_note=_sanitize_review_text(rem, debug=debug),
        citations=[
            CitationOut(
                chunk_id=c.chunk_id,
                evidence_id=f"evi:chunk:{c.chunk_id}" if c.chunk_id else None,
                source_type="gdpr_chunk",
                source_ref=c.chunk_id,
                article_number=c.article_number,
                paragraph_ref=c.paragraph_ref,
                article_title=c.article_title,
                excerpt=_sanitize_review_text(c.excerpt, debug=debug) or "",
            )
            for c in row.citations
            if c.excerpt
        ]
        or None,
    )


def _build_analysis_review_item(row: AuditAnalysisItem, *, debug: bool) -> ReviewItemOut:
    norm = _normalize_internal_state(
        row.classification_candidate,
        row.status_candidate,
        row.artifact_role,
        row.finding_level_candidate,
        row.publication_state_candidate,
    )
    gap, rem = _apply_family_fallback(row.issue_type, row.gap_note, row.remediation_note)
    return ReviewItemOut(
        item_kind="analysis",
        id=row.id,
        section_id=row.section_id,
        issue_type=row.issue_type,
        status=norm[0],
        classification=row.classification_candidate,
        artifact_role=norm[1],
        finding_level=norm[2],
        publication_state=norm[3],
        suppression_reason=_sanitize_review_text(row.suppression_reason, debug=debug),
        completeness_map=row.retrieval_summary if row.analysis_type == "completeness_outcome" else None,
        gap_note=_sanitize_review_text(gap, debug=debug),
        remediation_note=_sanitize_review_text(rem, debug=debug),
    )


def _build_review_blocks(disposition: dict, *, debug: bool) -> list[ReviewItemOut]:
    out: list[ReviewItemOut] = []
    for duty in ["controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right"]:
        item = disposition.get(duty, {})
        final_status = item.get("status")
        raw_obs = item.get("reasoning")
        reason = _review_reasoning(raw_obs, duty) if debug else _auditor_review_reason(duty, final_status, raw_obs)
        out.append(
            ReviewItemOut(
                item_kind="review_block",
                id=f"core:{duty}",
                section_id="review:core_duties",
                status=None,
                review_group="core_duties",
                duty=duty,
                triggered=bool(item.get("triggered", True)),
                final_disposition=final_status,
                reason=reason,
                source_scope_dependency=str(item.get("source_scope_dependency") or "high"),
                publication_recommendation=str(item.get("publication_recommendation") or "internal_only"),
            )
        )
    specialist_triggers = {
        "transfer": ("transfer", "transfer"),
        "profiling": ("profiling", "profiling"),
        "role_ambiguity": ("role_ambiguity", "role_ambiguity"),
        "article14_source": ("article14_source", "article14"),
        "recipients": ("recipients", "recipients"),
        "special_category": ("special_category", "special_category"),
        "dpo_contact": ("dpo_contact", "dpo_contact"),
        "purpose_mapping": ("purpose_mapping", "purpose_mapping"),
    }
    for family, (lookup_key, label) in specialist_triggers.items():
        item = disposition.get(lookup_key, {})
        final_status = item.get("status")
        raw_obs = item.get("reasoning")
        triggered = bool(item.get("triggered", item.get("status") != "satisfied"))
        reason = (
            _review_reasoning(raw_obs, family)
            if debug
            else _auditor_review_reason(label, final_status if triggered else None, raw_obs)
        )
        out.append(
            ReviewItemOut(
                item_kind="review_block",
                id=f"family:{family}",
                section_id="review:specialist_families",
                review_group="specialist_families",
                family=label,
                triggered=triggered,
                final_disposition=final_status,
                reason=reason,
                source_scope_dependency=str(item.get("source_scope_dependency") or "low"),
                publication_recommendation=str(item.get("publication_recommendation") or "internal_only"),
            )
        )
    return out


@router.get("/audits/{audit_id}/review", response_model=list[ReviewItemOut])
def get_review(
    audit_id: str,
    debug: bool = Query(default=False),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReviewItemOut]:
    _get_owned_audit_or_404(db, audit_id, user_id)
    # Publishable findings are always included
    publishable_findings = db.scalars(
        select(Finding)
        .options(selectinload(Finding.citations))
        .where(Finding.audit_id == audit_id)
        .where(Finding.publication_state == "publishable")
        .where(~Finding.section_id.startswith("ledger:"))
        .order_by(Finding.section_id.asc(), Finding.id.asc())
    ).all()

    # Count internal rows for the diagnostics summary (always needed for the summary item)
    internal_findings_count = (
        db.scalar(
            select(Finding)
            .where(Finding.audit_id == audit_id)
            .where(Finding.publication_state.in_(["blocked", "internal_only"]))
            .where(~Finding.section_id.startswith("ledger:"))
            .with_only_columns(func.count())
        )
        or 0
    )
    analysis_rows_count = (
        db.scalar(
            select(AuditAnalysisItem)
            .where(AuditAnalysisItem.audit_id == audit_id)
            .where(
                AuditAnalysisItem.analysis_type.in_(
                    [
                        "completeness_outcome",
                        "referenced_but_unseen",
                        "not_assessable_core_duty",
                        "support_evidence",
                        "excerpt_scope_fact",
                    ]
                )
            )
            .with_only_columns(func.count())
        )
        or 0
    )
    diagnostics_total = internal_findings_count + analysis_rows_count

    out: list[ReviewItemOut] = []

    # 1. Publishable findings (always shown)
    out.extend(_build_finding_review_item(row, debug=debug) for row in publishable_findings)

    # 2. In debug mode: also include internal findings and analysis rows
    if debug:
        internal_findings = db.scalars(
            select(Finding)
            .options(selectinload(Finding.citations))
            .where(Finding.audit_id == audit_id)
            .where(Finding.publication_state.in_(["blocked", "internal_only"]))
            .where(Finding.legal_requirement.is_not(None))
            .where(~Finding.section_id.startswith("ledger:"))
            .order_by(Finding.section_id.asc(), Finding.id.asc())
        ).all()
        analysis_rows = db.scalars(
            select(AuditAnalysisItem)
            .where(AuditAnalysisItem.audit_id == audit_id)
            .where(
                AuditAnalysisItem.analysis_type.in_(
                    [
                        "completeness_outcome",
                        "referenced_but_unseen",
                        "not_assessable_core_duty",
                        "support_evidence",
                        "excerpt_scope_fact",
                    ]
                )
            )
            .order_by(AuditAnalysisItem.section_id.asc(), AuditAnalysisItem.id.asc())
        ).all()
        out.extend(_build_finding_review_item(row, debug=True) for row in internal_findings)
        out.extend(_build_analysis_review_item(row, debug=True) for row in analysis_rows)

    # 3. Duty-level review blocks from disposition map
    disposition_ledger = (
        db.query(Finding)
        .filter(Finding.audit_id == audit_id)
        .filter(Finding.legal_requirement == "suppression_validator=final_disposition_map")
        .order_by(Finding.id.desc())
        .first()
    )
    if disposition_ledger and disposition_ledger.gap_reasoning:
        try:
            disposition = json.loads(disposition_ledger.gap_reasoning)
        except json.JSONDecodeError:
            disposition = {}
        out.extend(_build_review_blocks(disposition, debug=debug))

    # 4. Diagnostics summary (default: count only; debug: already shown inline above)
    if not debug:
        out.append(
            ReviewItemOut(
                item_kind="diagnostics_summary",
                id="diagnostics:summary",
                section_id="review:diagnostics",
                diagnostics_count=diagnostics_total,
                gap_note=(f"{diagnostics_total} pipeline analysis rows were excluded from this view.")
                if diagnostics_total > 0
                else "All pipeline rows are accounted for in this view.",
            )
        )

    return out


@router.get("/audits/{audit_id}/review/grouped")
def get_review_grouped(
    audit_id: str,
    debug: bool = Query(default=False),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[ReviewItemOut]]:
    items = get_review(audit_id, debug=debug, user_id=user_id, db=db)
    grouped: dict[str, list[ReviewItemOut]] = {
        "publication_blockers": [],
        "core_duty_resolution": [],
        "specialist_family_resolution": [],
        "publishable_findings": [],
        "internal_unresolved_items": [],
        "diagnostics": [],
    }
    for item in items:
        if item.item_kind == "review_block" and item.review_group == "core_duties":
            grouped["core_duty_resolution"].append(item)
            if item.final_disposition not in {"satisfied", None}:
                grouped["publication_blockers"].append(item)
            continue
        if item.item_kind == "review_block" and item.review_group == "specialist_families":
            grouped["specialist_family_resolution"].append(item)
            if item.final_disposition not in {"satisfied", None}:
                grouped["publication_blockers"].append(item)
            continue
        if item.item_kind == "finding" and item.publication_state == "publishable":
            grouped["publishable_findings"].append(item)
            continue
        if item.item_kind == "diagnostics_summary":
            grouped["diagnostics"].append(item)
            continue
        if item.item_kind == "analysis" or (
            item.item_kind == "finding" and item.publication_state in {"blocked", "internal_only"}
        ):
            grouped["diagnostics"].append(item)
            continue
        if item.status in {"not applicable", "needs review"} or item.publication_state in {"blocked", "internal_only"}:
            grouped["internal_unresolved_items"].append(item)
            continue
    return grouped


@router.get("/audits/{audit_id}/final-decision-ledger", response_model=list[FinalDecisionLedgerRowOut])
def get_final_decision_ledger(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FinalDecisionLedgerRowOut]:
    _get_owned_audit_or_404(db, audit_id, user_id)
    rows = db.scalars(
        select(Finding)
        .options(selectinload(Finding.citations))
        .where(Finding.audit_id == audit_id)
        .order_by(Finding.id.asc())
    ).all()
    output: list[FinalDecisionLedgerRowOut] = []
    seen: set[str] = set()
    for row in rows:
        if row.section_id.startswith("ledger:"):
            continue
        issue = (
            _issue_from_finding_section(row.section_id)
            or _infer_issue_from_text(None, row.gap_note, row.remediation_note)
            or "governance_disclosure_gap"
        )
        issue_type = CANONICAL_ISSUE_TAXONOMY.get(issue, "Governance and compliance disclosure")
        scope_type = "document_wide" if row.section_id.startswith("systemic:") else "section"
        canonical_key = f"{scope_type}:{row.section_id}:{_canonical_issue_key(issue)}"
        if canonical_key in seen:
            continue
        seen.add(canonical_key)
        citation_refs = [f"evi:chunk:{c.chunk_id}" for c in row.citations if c.chunk_id]
        document_refs = _deserialize_json_list(row.document_evidence_refs) or []
        evidence_refs = sorted(set([*citation_refs, *document_refs]))
        evidence_mode = "direct_excerpt" if row.citations else "explicit_absence_statement"
        blockers = []
        if row.publication_state in {"blocked", "internal_only"}:
            blockers.append("publication_blocked")
        output.append(
            FinalDecisionLedgerRowOut(
                canonical_issue_key=canonical_key,
                scope_type=scope_type,
                scope_id=row.section_id,
                scope_title=row.section_id,
                issue_type=issue_type,
                issue_subtype=_issue_subtype_for_row(row),
                final_status=row.status,
                final_severity=row.severity,
                legal_anchors=_deserialize_json_list(row.primary_legal_anchor) or [],
                evidence_refs=evidence_refs,
                evidence_mode=evidence_mode,
                review_visible=True,
                published_visible=row.publication_state == "publishable",
                report_visible=row.publication_state in {"publishable", "blocked", "internal_only"},
                export_visible=row.publication_state == "publishable" or row.publication_state == "blocked",
                blocker_reason_codes=blockers,
                normalization_metadata={
                    "classification": row.classification or "",
                    "publication_state": row.publication_state or "",
                },
            )
        )
    return output


@router.get("/audits/{audit_id}/export-contract", response_model=ExportContractOut)
def get_export_contract(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExportContractOut:
    _get_owned_audit_or_404(db, audit_id, user_id)
    contract, _rows, _blocked = build_export_contract(db, audit_id)
    return ExportContractOut.model_validate(contract)


@router.post("/audits/{audit_id}/report", response_model=ReportTriggerOut)
def create_report(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportTriggerOut:
    audit = _get_owned_audit_or_404(db, audit_id, user_id)

    orchestration_report_generation_requests_total.inc()

    if audit.status != "complete":
        if audit.status == "review_required":
            _record_api_request("/audits/{audit_id}/report", "POST", "409")
            raise HTTPException(status_code=409, detail="Report generation blocked: audit requires reviewer resolution")
        _record_api_request("/audits/{audit_id}/report", "POST", "409")
        raise HTTPException(status_code=409, detail="Audit is not complete")

    with orchestration_report_generation_latency_seconds.time():
        try:
            report, _ = generate_report_text(db, audit_id)
        except Exception as exc:
            failed = Report(audit_id=audit_id, status="failed")
            db.add(failed)
            db.commit()
            _record_api_request("/audits/{audit_id}/report", "POST", "500")
            raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")

    _record_api_request("/audits/{audit_id}/report", "POST", "200")
    return ReportTriggerOut(report_id=report.id, status=report.status)


@router.get("/audits/{audit_id}/report", response_model=ReportOut)
def get_report(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportOut:
    _get_owned_audit_or_404(db, audit_id, user_id)
    report = db.scalars(select(Report).where(Report.audit_id == audit_id).order_by(Report.created_at.desc())).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportOut.model_validate(report, from_attributes=True)


@router.get("/audits/{audit_id}/report/download")
def download_report(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    orchestration_report_downloads_total.inc()
    _get_owned_audit_or_404(db, audit_id, user_id)
    report = db.scalars(select(Report).where(Report.audit_id == audit_id).order_by(Report.created_at.desc())).first()
    if not report or not report.pdf_path:
        _record_api_request("/audits/{audit_id}/report/download", "GET", "404")
        raise HTTPException(status_code=404, detail="Report not found")

    path = Path(report.pdf_path)
    if not path.exists():
        _record_api_request("/audits/{audit_id}/report/download", "GET", "404")
        raise HTTPException(status_code=404, detail="Report file missing")

    _record_api_request("/audits/{audit_id}/report/download", "GET", "200")
    return FileResponse(path=str(path), media_type="application/pdf", filename=path.name)


@router.post("/audits/{audit_id}/remediation")
def trigger_remediation(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    orchestration_remediation_requests_total.inc()
    audit = _get_owned_audit_or_404(db, audit_id, user_id)

    if (audit.compliance_score or 0) >= 100:
        _record_api_request("/audits/{audit_id}/remediation", "POST", "200")
        return {"status": "compliant", "message": "Document is 100% compliant. No remediation required."}

    # Ensure items exist (idempotent)
    _create_remediation_items(audit_id, audit.compliance_score or 0, db)

    with orchestration_remediation_generation_latency_seconds.time():
        items = (
            db.query(RemediationItem)
            .filter(RemediationItem.audit_id == audit_id)
            .order_by(RemediationItem.order_index)
            .all()
        )

        for item in items:
            if item.suggestion and item.suggestion.generation_status == "complete":
                continue

            finding = db.get(Finding, item.finding_id) if item.finding_id else None
            gap_note = (finding.gap_note if finding else None) or item.issue_label
            legal_req = (finding.legal_requirement if finding else None) or item.issue_label

            user_prompt = (
                f"Gap: {item.issue_label}\n"
                f"GDPR requirement: {legal_req}\n"
                f"Gap description: {gap_note}\n\n"
                "Provide a short model clause (2-4 sentences) that would fix this gap. "
                "Use bracketed placeholders for any organization-specific values."
            )

            result = run_llm_plain_text(
                system_prompt=_REMEDIATION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model_provider=audit.model_provider or settings.model_provider,
                model_name=audit.model_name or settings.model_name,
                temperature=audit.model_temperature or settings.model_temperature,
                groq_api_key=settings.groq_api_key,
                gemini_api_key=settings.gemini_api_key,
                fallback_provider=settings.fallback_model_provider,
                fallback_model=settings.fallback_model_name,
            )

            if item.suggestion:
                item.suggestion.generation_status = "complete" if result else "failed"
                item.suggestion.suggested_fix_text = result
            else:
                db.add(
                    RemediationSuggestion(
                        remediation_item_id=item.id,
                        suggested_fix_text=result,
                        generation_status="complete" if result else "failed",
                    )
                )

    db.commit()
    return {"status": "complete", "message": "Remediation suggestions generated."}


@router.get("/audits/{audit_id}/remediation", response_model=list[RemediationItemOut])
def get_remediation(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RemediationItemOut]:
    _get_owned_audit_or_404(db, audit_id, user_id)

    items = (
        db.query(RemediationItem)
        .filter(RemediationItem.audit_id == audit_id)
        .order_by(RemediationItem.order_index)
        .all()
    )

    result: list[RemediationItemOut] = []
    for item in items:
        sug = None
        if item.suggestion:
            sug = RemediationSuggestionOut(
                id=item.suggestion.id,
                generation_status=item.suggestion.generation_status,
                suggested_fix_text=item.suggestion.suggested_fix_text,
            )
        result.append(
            RemediationItemOut(
                id=item.id,
                audit_id=item.audit_id,
                finding_id=item.finding_id,
                issue_key=item.issue_key,
                issue_label=item.issue_label,
                severity=item.severity,
                score_impact_points=item.score_impact_points,
                order_index=item.order_index,
                section_id=item.section_id,
                suggestion=sug,
            )
        )
    return result


@router.get("/audits/{audit_id}/remediation/status", response_model=RemediationStatusOut)
def get_remediation_status(
    audit_id: str,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RemediationStatusOut:
    audit = _get_owned_audit_or_404(db, audit_id, user_id)

    is_compliant = (audit.compliance_score or 0) >= 100

    items = db.query(RemediationItem).filter(RemediationItem.audit_id == audit_id).all()
    total = len(items)
    complete = sum(1 for i in items if i.suggestion and i.suggestion.generation_status == "complete")
    failed = sum(1 for i in items if i.suggestion and i.suggestion.generation_status == "failed")
    pending = total - complete - failed

    return RemediationStatusOut(
        total=total,
        pending=pending,
        complete=complete,
        failed=failed,
        is_compliant=is_compliant,
    )
