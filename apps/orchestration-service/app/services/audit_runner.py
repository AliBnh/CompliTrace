from __future__ import annotations

import re
import time
import json
import hashlib
from datetime import datetime
from typing import Iterable, TypedDict

from prometheus_client import Counter, Histogram
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import AnalysisCitation, Audit, AuditAnalysisItem, Finding, FindingCitation
from app.services.clients import IngestionClient, KnowledgeClient, LlmCitation, LlmFinding, RetrievalChunk, SectionData
from app.services.llm import run_llm_classification


retrieval_retry_total = Counter("retrieval_retry_total", "Retries triggered by frozen threshold")
evidence_gate_failure_total = Counter("evidence_gate_failure_total", "Sections failing evidence gate")
citation_validation_failure_total = Counter("citation_validation_failure_total", "Rejected citations")
llm_inference_latency_seconds = Histogram("llm_inference_latency_seconds", "LLM inference latency")
audit_duration_seconds = Histogram("audit_duration_seconds", "End-to-end audit duration")
findings_by_status_total = Counter("findings_by_status_total", "Findings persisted by status", ["status"])
audit_sections_total = Counter("audit_sections_total", "Total sections processed by audit")
audit_sections_auditable_total = Counter("audit_sections_auditable_total", "Auditable sections processed by audit")
audit_sections_filtered_total = Counter("audit_sections_filtered_total", "Sections filtered before substantive audit")
issue_spotting_calls_total = Counter("issue_spotting_calls_total", "Issue spotting agent calls")
applicability_calls_total = Counter("applicability_calls_total", "Applicability agent calls")
legal_qualification_calls_total = Counter("legal_qualification_calls_total", "Legal qualification calls")
profiling_pass_total = Counter("profiling_pass_total", "Profiling pass triggered")
transfer_pass_total = Counter("transfer_pass_total", "Transfer pass triggered")
reviewer_pass_total = Counter("reviewer_pass_total", "Reviewer pass runs")
publishable_findings_total = Counter("publishable_findings_total", "Publishable findings generated")
contradiction_fail_total = Counter("contradiction_fail_total", "Findings rejected by contradiction controls")
local_findings_published_total = Counter("local_findings_published_total", "Published local findings")
systemic_findings_published_total = Counter("systemic_findings_published_total", "Published systemic findings")
not_assessable_findings_published_total = Counter("not_assessable_findings_published_total", "Published not-assessable findings")


ADMIN_PATTERNS = {
    "scope",
    "purpose of this document",
    "definitions",
    "terms",
    "introduction",
    "overview",
    "document control",
    "version history",
    "amendment history",
    "references",
    "contact us",
    "contacts",
}

PROCESSING_SIGNALS = {
    "personal data",
    "data subject",
    "process",
    "collect",
    "store",
    "retain",
    "share",
    "transfer",
    "consent",
    "sensitive data",
    "recipient",
    "controller",
    "processor",
}

OBLIGATION_WORDS = {"shall", "must", "required", "obligation", "necessary", "appropriate"}

DOCUMENT_MODE_HINTS: dict[str, set[str]] = {
    "privacy_notice": {
        "privacy notice",
        "privacy policy",
        "data subject rights",
        "legal basis",
        "recipients",
        "international transfers",
    },
    "internal_policy": {
        "policy purpose",
        "roles and responsibilities",
        "incident response",
        "security controls",
        "retention schedule",
    },
}

MODE_ARTICLE_HINTS: dict[str, str] = {
    "privacy_notice": "prioritize GDPR Articles 12, 13, 14, and Article 5 principles",
    "internal_policy": "prioritize GDPR Articles 5, 24, 25, 30, 32 and accountability obligations",
}

PRIVACY_NOTICE_PREFERRED_ARTICLES = {5, 6, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}
PRIVACY_NOTICE_DISCOURAGED_ARTICLES = {30, 88}
INTERNAL_POLICY_PREFERRED_ARTICLES = {5, 24, 25, 30, 32, 35}

EMPLOYMENT_SIGNALS = {"employee", "employment", "worker", "staff", "hr", "human resources"}
ROPA_SIGNALS = {"record of processing", "ropa", "processing register", "register of processing"}
THIRD_COUNTRY_TRANSFER_SIGNALS = {
    "third country",
    "outside the eea",
    "outside eea",
    "international transfer",
    "cross-border",
    "transfer",
}

NOTICE_REQUIREMENT_SIGNALS: dict[str, set[str]] = {
    "controller_contact": {"controller", "contact", "email", "address"},
    "legal_basis": {"legal basis", "lawful basis", "consent", "contract", "legitimate interest", "legal obligation"},
    "rights": {"right to access", "rectification", "erasure", "restriction", "portability", "object", "data subject rights"},
    "retention": {"retention", "retain", "kept for", "storage period"},
    "complaint": {"complaint", "supervisory authority", "data protection authority"},
}
CORE_NOTICE_CLAIMS = {"controller_contact", "legal_basis", "retention", "rights", "complaint", "transfer"}
CORE_NOTICE_SYSTEMIC_ISSUES = {
    "missing_controller_identity",
    "missing_legal_basis",
    "missing_retention_period",
    "missing_rights_notice",
    "missing_complaint_right",
}

SYSTEMIC_ANCHOR_MAP: dict[str, dict[str, list[str]]] = {
    "missing_controller_identity": {
        "primary": ["GDPR Art. 13(1)(a)", "GDPR Art. 14(1)(a)"],
        "secondary": ["GDPR Art. 12(1)"],
    },
    "missing_legal_basis": {
        "primary": ["GDPR Art. 13(1)(c)", "GDPR Art. 14(1)(c)"],
        "secondary": ["GDPR Art. 12(1)"],
    },
    "missing_retention_period": {
        "primary": ["GDPR Art. 13(2)(a)", "GDPR Art. 14(2)(a)"],
        "secondary": ["GDPR Art. 5(1)(e)"],
    },
    "missing_rights_notice": {
        "primary": ["GDPR Art. 13(2)(b)-(d)", "GDPR Art. 14(2)(c)-(e)"],
        "secondary": ["GDPR Art. 12(1)"],
    },
    "missing_complaint_right": {
        "primary": ["GDPR Art. 13(2)(d)", "GDPR Art. 14(2)(e)"],
        "secondary": ["GDPR Art. 77"],
    },
    "missing_transfer_notice": {
        "primary": ["GDPR Art. 13(1)(f)", "GDPR Art. 14(1)(f)"],
        "secondary": ["GDPR Art. 44"],
    },
    "profiling_disclosure_gap": {
        "primary": ["GDPR Art. 13(2)(f)", "GDPR Art. 14(2)(g)"],
        "secondary": ["GDPR Art. 22"],
    },
}

SYSTEMIC_REQUIRED_OBLIGATION_KEYS: dict[str, str] = {
    "missing_controller_identity": "controller_identity_present",
    "missing_legal_basis": "legal_basis_present",
    "missing_retention_period": "retention_present",
    "missing_rights_notice": "rights_present",
    "missing_complaint_right": "complaint_present",
}

SYSTEMIC_SECTION_SIGNALS: dict[str, set[str]] = {
    "missing_controller_identity": {"controller", "company", "contact", "privacy notice", "personal data"},
    "missing_legal_basis": {"purpose", "process", "collect", "use", "personal data"},
    "missing_retention_period": {"retain", "retention", "storage", "personal data", "process"},
    "missing_rights_notice": {"right", "data subject", "access", "rectification", "erasure", "process"},
    "missing_complaint_right": {"complaint", "supervisory authority", "rights", "personal data", "privacy"},
    "missing_transfer_notice": {"transfer", "third country", "international", "recipient"},
    "profiling_disclosure_gap": {"profil", "automated", "decision", "score", "segmentation"},
}

CORE_DUTY_TO_ISSUE: dict[str, str] = {
    "controller_identity": "missing_controller_identity",
    "controller_contact": "missing_controller_identity",
    "legal_basis": "missing_legal_basis",
    "retention": "missing_retention_period",
    "rights": "missing_rights_notice",
    "complaint_right": "missing_complaint_right",
}

CORE_DUTY_OBLIGATION_KEYS: dict[str, str] = {
    "controller_identity": "controller_identity_present",
    "controller_contact": "controller_contact_present",
    "legal_basis": "legal_basis_present",
    "retention": "retention_present",
    "rights": "rights_present",
    "complaint_right": "complaint_present",
}

SPECIALIST_TRIGGER_RULES: dict[str, tuple[set[str], str]] = {
    "missing_transfer_notice": (THIRD_COUNTRY_TRANSFER_SIGNALS, "triggered_transfer_family"),
    "profiling_disclosure_gap": ({"profil", "automated decision", "scoring", "segmentation"}, "triggered_profiling_family"),
    "article_14_indirect_collection": (
        {"from third parties", "obtained from third parties", "received from third parties", "from external sources"},
        "triggered_article_14_indirect_collection",
    ),
    "controller_processor_role_ambiguity": ({"controller", "processor", "on behalf of"}, "triggered_role_ambiguity_family"),
}

DIRECT_COLLECTION_SIGNALS = {
    "you provide",
    "provided by you",
    "from you",
    "submitted by you",
    "when you",
    "you submit",
    "you share",
    "you choose to provide",
    "you enter",
    "you fill",
    "account registration",
    "signup form",
    "contact form",
    "application form",
}
INDIRECT_COLLECTION_SIGNALS = {
    "from third parties",
    "from partners",
    "from customers",
    "from suppliers",
    "from resellers",
    "from integrated providers",
    "provided by third parties",
    "obtained from third parties",
    "received from third parties",
    "public authorities",
    "publicly available",
    "data brokers",
    "social media platforms",
    "affiliate companies",
    "our clients provide",
    "employer provides",
    "background screening provider",
    "identity verification provider",
}

DIRECT_COLLECTION_HINTS = {
    "we collect directly",
    "we ask you",
    "you give us",
    "information you provide",
    "directly from data subjects",
}

INDIRECT_COLLECTION_HINTS = {
    "we receive",
    "we obtain",
    "received from",
    "obtained from",
    "collected from",
    "sourced from",
    "from external sources",
    "from other sources",
    "from third-party",
    "from third party",
}

NOTICE_REQUIREMENT_LABELS: dict[str, str] = {
    "controller_contact": "controller identity and contact details",
    "legal_basis": "legal basis for processing",
    "rights": "data subject rights information",
    "retention": "retention period or criteria",
    "complaint": "complaint-right and supervisory authority details",
}

CLAIM_PRIMARY_ARTICLES: dict[str, set[int]] = {
    "legal_basis": {6, 13, 14},
    "retention": {5, 13, 14},
    "rights": {12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22},
    "controller_contact": {13, 14},
    "complaint": {13, 14, 77},
    "transfer": {13, 14, 44, 45, 46, 47, 49},
    "sensitive_data": {9, 13, 14},
    "profiling": {13, 14, 22},
    "right_to_object": {21, 13, 14},
}

PRIVACY_NOTICE_SCOPE_PRIMARY = {5, 6, 9, 12, 13, 14, 21, 22, 44, 45, 46, 47, 49, 77}

CLAIM_ARTICLE_RULES: dict[str, dict[str, set[int]]] = {
    "missing_controller_identity": {"primary": {13, 14}, "support": {12}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_dpo_contact": {"primary": {13, 14}, "support": {12}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_legal_basis": {"primary": {6, 13, 14}, "support": {5}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_purposes": {"primary": {13, 14, 5}, "support": {12}, "disallowed": {21, 44, 45, 46, 47, 49}},
    "missing_recipients": {"primary": {13, 14}, "support": {12}, "disallowed": {21, 22}},
    "missing_transfer_disclosure": {"primary": {13, 14}, "support": {44, 45, 46, 47, 49}, "disallowed": {15, 21}},
    "missing_transfer_safeguard_mechanism": {
        "primary": {44, 45, 46, 47, 49},
        "support": {13, 14},
        "disallowed": {15, 21},
    },
    "missing_retention_period": {"primary": {13, 14, 5}, "support": {12}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_rights_notice": {"primary": {13, 14, 12, 15, 16, 17, 18, 19, 20, 21, 22}, "support": {5}, "disallowed": set()},
    "missing_complaint_right": {"primary": {13, 14, 77}, "support": {12}, "disallowed": {21, 22}},
    "missing_profiling_logic": {"primary": {13, 14}, "support": {22, 21}, "disallowed": {15}},
    "missing_special_category_basis": {"primary": {9, 13, 14}, "support": {6}, "disallowed": {21}},
    "controller_processor_role_ambiguity": {"primary": {13, 14}, "support": {12}, "disallowed": {21, 22}},
}

NOTICE_SECTION_TITLE_SIGNALS = {
    "privacy notice",
    "privacy policy",
    "data we collect",
    "information we collect",
    "how we use your data",
    "your rights",
    "retention",
    "contact us",
    "international transfer",
}

NOTICE_SECTION_CONTENT_SIGNALS = {
    "we collect",
    "we process",
    "personal data",
    "data subject",
    "your rights",
    "legal basis",
    "retention period",
    "supervisory authority",
    "complaint",
}


class DocumentPosture(TypedDict):
    document_type: str
    triggered_duties: list[str]
    not_triggered_duties: list[str]
    not_assessable_duties: list[str]


class ApplicabilityMemo(TypedDict):
    obligation: str
    applicability_reasoning: str
    collection_mode: str
    visibility: str
    applicability_confidence: float
    disqualifying_alternatives: list[str]


class ApplicabilityDecision(TypedDict):
    collection_mode: str
    applicability_status: str
    allowed_notice_articles: list[int]
    unresolved_trigger: str | None


class SpecializedReview(TypedDict):
    profiling: str | None
    transfer: str | None
    special_category: str | None
    role_allocation: str | None


class CandidateIssue(TypedDict):
    candidate_issue_type: str
    evidence_text: str
    evidence_strength: float
    local_or_document_level: str
    possible_collection_mode: str
    is_visible_gap: bool


class LegalQualification(TypedDict):
    issue_name: str
    primary_article: str
    secondary_articles: list[str]
    rejected_articles: list[str]
    reason_primary_article_fits: str
    reason_rejected_articles_do_not_fit: str


class CrossReference(TypedDict):
    referenced_topic: str
    referenced_section_label: str
    reference_text: str
    section_present_in_reviewed_source: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _is_not_applicable(section: SectionData) -> bool:
    title = re.sub(r"[^a-z0-9\s]", "", _norm(section.section_title))
    if title not in ADMIN_PATTERNS:
        return False
    content = _norm(section.content)
    return not any(k in content for k in PROCESSING_SIGNALS)


def _section_auditability_type(section: SectionData) -> str:
    title = _norm(section.section_title)
    text = _section_context_signals(section)
    auditable_signals = {
        "process",
        "collect",
        "data categories",
        "source",
        "transfer",
        "profil",
        "retention",
        "rights",
        "recipient",
        "controller",
        "processor",
        "audience",
        "application",
        "territorial",
        "partner",
        "customer-sourced",
        "device",
        "behavioral",
        "special category",
        "sensitive",
        "personal data",
        "personal information",
        "identifier",
        "identity",
        "usage",
        "share",
    }
    if any(signal in text for signal in auditable_signals):
        high_value = {"legal basis", "retention", "right", "complaint", "controller", "recipient", "transfer"}
        if any(sig in text for sig in high_value):
            return "auditable_primary"
        return "auditable_secondary"
    if any(t in title for t in {"definition", "glossary", "terms"}):
        return "definition_section"
    if any(t in title for t in {"effective date", "owner", "version", "introduction"}):
        return "administrative_section"
    if any(t in text for t in {"we process", "we collect", "recipient", "rights", "retention", "transfer", "profil"}):
        return "auditable_primary"
    if any(t in text for t in {"controller", "processor", "third party", "source"}):
        return "auditable_secondary"
    return "meta_section"


def _issue_specific_remediation(issue_name: str, document_type: str, systemic: bool) -> str:
    prefix = "For the notice as a whole" if systemic else "For this section"
    mapping = {
        "missing_controller_identity": f"{prefix}, identify the controller legal entity and provide a direct contact route in the external privacy notice.",
        "missing_controller_contact": f"{prefix}, add a direct contact channel (email/webform/address) for privacy inquiries.",
        "missing_dpo_contact": f"{prefix}, disclose DPO contact details where a DPO is appointed or legally required.",
        "missing_purposes": f"{prefix}, list processing purposes in plain language and map each to relevant processing activities.",
        "missing_legal_basis": f"{prefix}, for each processing purpose described in the notice, state the lawful basis relied upon (e.g., contract, legal obligation, legitimate interests, or consent).",
        "missing_recipients": f"{prefix}, identify recipient categories and third-party disclosure contexts.",
        "missing_retention": f"{prefix}, state either the applicable retention periods or the objective criteria used to determine them for each relevant category of personal data.",
        "missing_rights_information": f"{prefix}, add complete rights information (access, rectification, erasure, restriction, objection, portability).",
        "missing_complaint_right": f"{prefix}, state that data subjects have the right to lodge a complaint with a supervisory authority and identify the relevant supervisory authority route where appropriate.",
        "missing_transfer_notice": f"{prefix}, disclose whether third-country transfers occur and in what contexts.",
        "missing_transfer_safeguards_disclosure": f"{prefix}, specify adequacy/SCC/BCR/derogation mechanism and how safeguard details can be obtained.",
        "profiling_disclosure_gap": (
            f"{prefix}, explain profiling existence, logic, significance, and envisaged consequences under Articles 13(2)(f)/14(2)(g)."
        ),
        "article_22_threshold_unclear": f"{prefix}, clarify whether automated decision-making with legal/similarly significant effects is performed and apply Article 22 safeguards if triggered.",
        "special_category_basis_unclear": f"{prefix}, identify Article 9 category and explicit Article 9(2) condition relied upon.",
        "controller_processor_role_ambiguity": f"{prefix}, clarify when the organization acts as controller vs processor and how role changes are communicated.",
        "missing_retention_period": f"{prefix}, state either the applicable retention periods or the objective criteria used to determine them for each relevant category of personal data.",
        "missing_rights_notice": f"{prefix}, add a dedicated rights section describing access, rectification, erasure, restriction, objection, portability, and any other applicable rights.",
        "missing_transfer_notice": f"{prefix}, disclose whether third-country transfers occur and in what contexts.",
    }
    return mapping.get(issue_name, f"{prefix}, add obligation-specific notice wording aligned to GDPR transparency duties.")


def _consistency_validator(issue_name: str, claim_types: set[str], citations: list[LlmCitation], remediation_note: str | None) -> bool:
    issue_from_claim = _claim_issue_ids(claim_types)
    if issue_name and issue_from_claim and issue_name not in issue_from_claim:
        return False
    if citations and _violates_forbidden_article_matrix(claim_types, citations):
        return False
    if remediation_note:
        rem = _norm(remediation_note)
        if "transfer" in issue_name and "retention" in rem:
            return False
        if "retention" in issue_name and "transfer" in rem:
            return False
    return True


def _assessment_type_for(finding: LlmFinding, classification: str | None) -> str:
    if classification == "clear_non_compliance":
        return "confirmed"
    if classification == "probable_gap":
        return "probable"
    return "not_assessable"


def _confidence_level_for(confidence: float | None) -> str:
    if confidence is None:
        return "low"
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def _severity_rationale(finding: LlmFinding, claim_types: set[str]) -> str:
    if finding.severity == "high":
        return "High severity due to central GDPR transparency obligation impact and broad rights exposure."
    if finding.severity == "medium":
        return "Medium severity due to meaningful transparency gap with partially bounded scope."
    if finding.severity == "low":
        return "Low severity due to localized clarity issue without clear document-wide omission."
    if finding.status == "needs review":
        return "Severity withheld because substantive legal support is not yet assessable."
    if "transfer" in claim_types:
        return "Severity calibrated to transfer disclosure context and safeguard visibility."
    return "Severity calibrated from obligation criticality, scope, and evidence confidence."


def _is_publishable_finding(section_id: str, status: str, classification: str | None, finding_type: str) -> bool:
    if section_id.startswith("__"):
        return False
    if status in {"needs review", "not applicable"}:
        return False
    if finding_type == "supporting_evidence":
        return False
    if classification == "supporting_evidence_internal_only":
        return False
    if classification in {"diagnostic_internal_only", "contradiction_internal_only", "retrieval_failure_internal_only"}:
        return False
    return True


def _pre_persist_consistency_gate(
    issue_name: str,
    claim_types: set[str],
    obligation_under_review: str,
    citations: list[LlmCitation],
    remediation_note: str | None,
    classification: str | None,
) -> tuple[bool, str | None]:
    if not _consistency_validator(issue_name, claim_types, citations, remediation_note):
        return False, "issue/article/citation/remediation mismatch"
    claim_issue_ids = _claim_issue_ids(claim_types)
    if claim_issue_ids and issue_name not in claim_issue_ids:
        return False, "issue type does not match extracted claim type"
    if obligation_under_review:
        obligation_map = {
            "controller_contact": {"missing_controller_identity", "missing_controller_contact"},
            "legal_basis": {"missing_legal_basis"},
            "retention": {"missing_retention", "missing_retention_period"},
            "rights": {"missing_rights_information", "missing_rights_notice"},
            "complaint": {"missing_complaint_right"},
            "transfer": {"missing_transfer_notice", "missing_transfer_safeguards_disclosure", "missing_transfer_disclosure"},
        }
        allowed_issues = obligation_map.get(obligation_under_review, set())
        if allowed_issues and issue_name not in allowed_issues:
            return False, "obligation_under_review mismatches issue type"
    if classification == "not_assessable" and citations:
        return False, "not_assessable finding should not carry substantive citation chain"
    return True, None


def _spot_candidate_issues(section: SectionData, collection_mode: str) -> list[CandidateIssue]:
    text = _section_context_signals(section)
    candidates: list[CandidateIssue] = []
    patterns: list[tuple[str, set[str], str]] = [
        ("missing_controller_identity", {"controller", "identity", "contact"}, "document"),
        ("missing_legal_basis", {"legal basis", "lawful basis"}, "document"),
        ("missing_retention", {"retention", "kept for", "storage period"}, "document"),
        ("missing_rights_information", {"right to access", "rectification", "erasure", "object"}, "document"),
        ("missing_complaint_right", {"supervisory authority", "complaint"}, "document"),
        ("missing_transfer_notice", {"transfer", "third country", "outside the eea"}, "local"),
        ("profiling_disclosure_gap", {"profil", "score", "segmentation", "predictive"}, "local"),
        ("special_category_basis_unclear", {"health", "biometric", "religious", "political", "ethnic", "genetic"}, "local"),
        ("controller_processor_role_ambiguity", {"controller", "processor", "on behalf of"}, "local"),
    ]
    for issue, signals, level in patterns:
        hits = sum(1 for s in signals if s in text)
        if hits == 0:
            if issue.startswith("missing_") and _is_notice_disclosure_section(section):
                candidates.append(
                    CandidateIssue(
                        candidate_issue_type=issue,
                        evidence_text=section.content[:200],
                        evidence_strength=0.45,
                        local_or_document_level=level,
                        possible_collection_mode=collection_mode,
                        is_visible_gap=False,
                    )
                )
            continue
        candidates.append(
            CandidateIssue(
                candidate_issue_type=issue,
                evidence_text=section.content[:260],
                evidence_strength=min(0.95, 0.55 + (hits * 0.12)),
                local_or_document_level=level,
                possible_collection_mode=collection_mode,
                is_visible_gap=hits > 0,
            )
        )
    return candidates[:6]


def _legal_qualification_for_issue(issue: CandidateIssue) -> LegalQualification:
    mapping: dict[str, tuple[str, list[str], list[str], str, str]] = {
        "missing_controller_identity": ("13(1)(a)", ["14(1)(a)"], ["21", "22"], "Controller identity disclosure duty.", "Article 21/22 do not govern identity notice content."),
        "missing_legal_basis": ("13(1)(c)", ["14(1)(c)", "6(1)"], ["13(1)(f)", "14(1)(f)"], "Legal basis must be disclosed with purposes.", "Transfer paragraphs do not satisfy legal-basis disclosure."),
        "missing_retention": ("13(2)(a)", ["14(2)(a)"], ["5(1)(e)"], "Retention period/criteria is explicit notice content duty.", "Article 5 principle alone is not the primary notice anchor."),
        "missing_rights_information": ("13(2)(b)", ["13(2)(c)", "13(2)(d)", "14(2)(c)", "14(2)(d)", "14(2)(e)"], ["5(1)(a)"], "Rights notice obligations are in Articles 13(2)/14(2).", "Article 5 principle is supporting, not primary rights notice basis."),
        "missing_complaint_right": ("13(2)(d)", ["14(2)(e)"], ["21"], "Complaint-right disclosure is explicit in 13(2)(d)/14(2)(e).", "Article 21 is objection right, not complaint-right anchor."),
        "missing_transfer_notice": ("13(1)(f)", ["14(1)(f)", "44", "45", "46"], ["15"], "Transfer disclosure belongs to notice transfer paragraph and Chapter V support.", "Article 15 access right is not transfer notice anchor."),
        "profiling_disclosure_gap": ("13(2)(f)", ["14(2)(g)", "21"], ["22"], "Profiling transparency starts with notice disclosure paragraphs.", "Article 22 is conditional on effects threshold."),
        "special_category_basis_unclear": ("9(1)", ["9(2)", "13(1)(c)", "14(1)(c)"], ["21"], "Special-category processing requires Article 9 condition.", "Article 21 is not lawful condition for special-category processing."),
        "controller_processor_role_ambiguity": ("13(1)(a)", ["14(1)(a)", "12(1)"], ["28"], "Role clarity is transparency duty in notice context.", "Article 28 only applies where processor-contract obligations are in scope."),
    }
    primary, secondary, rejected, reason_fit, reason_reject = mapping.get(
        issue["candidate_issue_type"],
        ("13(1)(a)", ["14(1)(a)"], ["21", "22"], "Closest notice anchor selected.", "Rejected articles are less direct."),
    )
    return LegalQualification(
        issue_name=issue["candidate_issue_type"],
        primary_article=primary,
        secondary_articles=secondary,
        rejected_articles=rejected,
        reason_primary_article_fits=reason_fit,
        reason_rejected_articles_do_not_fit=reason_reject,
    )


def _infer_topic(section: SectionData) -> str:
    title = _norm(section.section_title)
    content = _norm(section.content)[:1200]
    if "retention" in title or "retain" in content:
        return "data retention storage limitation"
    if "rights" in title or "data subject" in content:
        return "data subject rights access rectification erasure"
    if "transfer" in title or "international" in title:
        return "international transfer safeguards"
    if "security" in title or "incident" in title:
        return "security of processing technical organizational measures"
    if "consent" in title or "lawful" in title:
        return "lawful basis consent processing"
    return section.section_title


def _infer_document_mode(sections: list[SectionData]) -> str:
    scores = {mode: 0 for mode in DOCUMENT_MODE_HINTS}
    for section in sections:
        haystack = _norm(f"{section.section_title} {section.content[:500]}")
        for mode, hints in DOCUMENT_MODE_HINTS.items():
            scores[mode] += sum(1 for hint in hints if hint in haystack)
    best_mode = max(scores, key=scores.get)
    if scores[best_mode] == 0:
        return "internal_policy"
    return best_mode


def _document_posture_agent(sections: list[SectionData], document_mode: str) -> DocumentPosture:
    corpus = " ".join(_norm(f"{s.section_title} {s.content[:700]}") for s in sections)
    has_notice_signals = any(token in corpus for token in {"privacy notice", "privacy policy", "data subject rights"})
    has_dpa_signals = any(token in corpus for token in {"data processing agreement", "processor", "sub-processor"})
    has_consent_signals = any(token in corpus for token in {"consent", "withdraw consent"})
    has_internal_signals = any(token in corpus for token in {"roles and responsibilities", "incident response", "security controls"})
    excerpt_like = len(corpus) < 1800 or "..." in corpus

    if has_notice_signals and has_internal_signals:
        document_type = "mixed_document"
    elif has_dpa_signals:
        document_type = "dpa"
    elif has_notice_signals or document_mode == "privacy_notice":
        document_type = "external_privacy_notice"
    elif has_consent_signals:
        document_type = "consent_text"
    else:
        document_type = "internal_policy"
    if excerpt_like:
        document_type = f"{document_type}_excerpt"

    triggered = ["articles_12_14_transparency", "article_5_1_a_fairness_transparency"]
    not_triggered = ["article_22_automated_decision_making"] if "automated" not in corpus else []
    not_assessable = ["article_14_source_disclosure"] if _contains_any(corpus, INDIRECT_COLLECTION_SIGNALS) is False else []
    if _contains_any(corpus, THIRD_COUNTRY_TRANSFER_SIGNALS):
        triggered.append("articles_44_49_transfers")
    if "legal basis" in corpus or "lawful basis" in corpus:
        triggered.append("article_6_legal_basis")
    return DocumentPosture(
        document_type=document_type,
        triggered_duties=triggered,
        not_triggered_duties=not_triggered,
        not_assessable_duties=not_assessable,
    )


def _build_document_obligation_map(sections: list[SectionData]) -> dict[str, bool]:
    corpus = " ".join(_norm(f"{s.section_title} {s.content}") for s in sections)
    return {
        "controller_identity_present": any(t in corpus for t in {"controller", "legal entity", "company name"}),
        "controller_contact_present": any(t in corpus for t in {"contact details", "privacy@", "email", "contact us", "address"}),
        "dpo_present": any(t in corpus for t in {"data protection officer", "dpo"}),
        "rights_present": any(t in corpus for t in {"right of access", "right to object", "rectification", "erasure"}),
        "retention_present": any(t in corpus for t in {"retention", "kept for", "storage period"}),
        "complaint_present": any(t in corpus for t in {"complaint", "supervisory authority", "data protection authority"}),
        "transfer_present": any(t in corpus for t in THIRD_COUNTRY_TRANSFER_SIGNALS),
        "recipients_present": any(t in corpus for t in {"recipient", "third party", "processor"}),
        "legal_basis_present": any(t in corpus for t in {"legal basis", "lawful basis", "article 6"}),
    }


def _applicability_decision(section: SectionData, memo: ApplicabilityMemo, claim_types: set[str] | None = None) -> ApplicabilityDecision:
    claim_types = claim_types or set()
    mode = memo["collection_mode"]
    if mode == "direct":
        return ApplicabilityDecision(
            collection_mode=mode,
            applicability_status="confirmed",
            allowed_notice_articles=[13],
            unresolved_trigger=None,
        )
    if mode == "indirect":
        return ApplicabilityDecision(
            collection_mode=mode,
            applicability_status="confirmed",
            allowed_notice_articles=[14],
            unresolved_trigger=None,
        )
    if mode == "mixed":
        return ApplicabilityDecision(
            collection_mode=mode,
            applicability_status="probable",
            allowed_notice_articles=[13, 14],
            unresolved_trigger="mixed collection signals",
        )
    hint_text = _section_context_signals(section)
    unresolved = "insufficient source wording to resolve direct vs indirect collection"
    if "collect" in hint_text and "from" not in hint_text:
        return ApplicabilityDecision(
            collection_mode="direct",
            applicability_status="probable",
            allowed_notice_articles=[13],
            unresolved_trigger=unresolved,
        )
    if claim_types & CORE_NOTICE_CLAIMS:
        return ApplicabilityDecision(
            collection_mode=mode,
            applicability_status="probable",
            allowed_notice_articles=[13, 14],
            unresolved_trigger=unresolved,
        )
    return ApplicabilityDecision(
        collection_mode=mode,
        applicability_status="unresolved",
        allowed_notice_articles=[],
        unresolved_trigger=unresolved,
    )


def _build_retrieval_query(section: SectionData, topic: str, document_mode: str) -> str:
    article_hint = MODE_ARTICLE_HINTS.get(document_mode, "prioritize directly applicable GDPR obligations")
    snippet = section.content[:700]
    return f"GDPR obligations for {topic}. Context: {article_hint}. Section text: {snippet}"


def _article_int(value: str | None) -> int | None:
    if not value:
        return None
    m = re.search(r"\d+", str(value))
    if not m:
        return None
    return int(m.group(0))


def _contains_any(text: str, signals: Iterable[str]) -> bool:
    return any(signal in text for signal in signals)


def _section_context_signals(section: SectionData) -> str:
    return _norm(f"{section.section_title} {section.content[:1200]}")


def _extract_notice_cross_references(sections: list[SectionData]) -> list[CrossReference]:
    visible_section_numbers: set[str] = set()
    section_num_re = re.compile(r"\bsection\s+(\d+[a-z]?)\b", re.IGNORECASE)
    for section in sections:
        title = _norm(section.section_title)
        visible_section_numbers.update(section_num_re.findall(title))
        if re.match(r"^\d+[a-z]?(?:\.\d+)?", title):
            visible_section_numbers.add(re.match(r"^\d+[a-z]?", title).group(0))  # type: ignore[union-attr]

    references: list[CrossReference] = []
    topic_tokens = {
        "rights": {"rights", "access", "rectification", "erasure", "complaint"},
        "retention": {"retention", "storage", "kept"},
        "legal_basis": {"legal basis", "lawful basis"},
        "controller_contact": {"controller", "contact", "details"},
        "transfer": {"transfer", "third country", "outside eea"},
    }
    for section in sections:
        content = section.content
        for sentence in re.split(r"(?<=[.!?])\s+", content):
            lowered = _norm(sentence)
            if "section" not in lowered:
                continue
            for match in section_num_re.finditer(lowered):
                sec = match.group(1)
                topic = "general"
                for topic_name, tokens in topic_tokens.items():
                    if any(t in lowered for t in tokens):
                        topic = topic_name
                        break
                references.append(
                    CrossReference(
                        referenced_topic=topic,
                        referenced_section_label=f"Section {sec}",
                        reference_text=sentence.strip()[:260],
                        section_present_in_reviewed_source="yes" if sec in visible_section_numbers else "no",
                    )
                )
    return references


def _source_scope_qualification(sections: list[SectionData], references: list[CrossReference]) -> tuple[str, float, list[str]]:
    unseen = [r["referenced_section_label"] for r in references if r["section_present_in_reviewed_source"] == "no"]
    if unseen:
        return "partial_notice_excerpt", 0.9, sorted(list(dict.fromkeys(unseen)))
    corpus = " ".join(_section_context_signals(s) for s in sections)
    if "..." in corpus or any(_section_context_signals(s).endswith(("and", "or", ",")) for s in sections):
        return "partial_notice_excerpt", 0.72, []
    numbered_titles = [s.section_title.strip() for s in sections if re.match(r"^\d+", s.section_title.strip())]
    if numbered_titles and len(numbered_titles) < 3:
        return "uncertain_scope", 0.55, []
    return "full_notice", 0.82, []


def _issue_has_unseen_reference(issue_id: str, refs: list[CrossReference]) -> bool:
    topic_map = {
        "missing_legal_basis": "legal_basis",
        "missing_retention_period": "retention",
        "missing_rights_notice": "rights",
        "missing_complaint_right": "rights",
        "missing_controller_identity": "controller_contact",
        "missing_transfer_notice": "transfer",
    }
    wanted = topic_map.get(issue_id, "general")
    for ref in refs:
        if ref["section_present_in_reviewed_source"] == "no" and (ref["referenced_topic"] in {wanted, "general"}):
            return True
    return False


def _preferred_articles_for_section(section: SectionData, document_mode: str) -> set[int]:
    topic = _norm(_infer_topic(section))
    section_ctx = _section_context_signals(section)
    if document_mode == "privacy_notice":
        preferred = set(PRIVACY_NOTICE_PREFERRED_ARTICLES)
        if "transfer" in topic or "international" in topic:
            preferred |= {13, 14, 44, 45, 49}
            if _contains_any(section_ctx, THIRD_COUNTRY_TRANSFER_SIGNALS):
                preferred |= {46, 47}
        if "rights" in topic or "data subject" in topic:
            preferred |= {12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22}
        if "retention" in topic:
            preferred |= {5, 13, 14}
        return preferred
    return set(INTERNAL_POLICY_PREFERRED_ARTICLES)


def _section_guidance(section: SectionData, document_mode: str) -> str:
    topic = _norm(_infer_topic(section))
    section_ctx = _section_context_signals(section)
    if document_mode != "privacy_notice":
        return (
            "Use accountability-focused analysis. Prefer Articles 5, 24, 25, 30, and 32 for internal controls. "
            "Use Article 88 only for explicit employment-processing context."
        )
    if "transfer" in topic or "international" in topic:
        return (
            "For privacy notices: first test disclosure obligations under Articles 13(1)(f) and 14(1)(f). "
            "Use Chapter V transfer mechanism support (Articles 44-49, especially 46) only when transfer context is explicit. "
            "Do not use Articles 13(3)-(4), 15, or 18 as primary transfer-safeguard basis."
        )
    if "rights" in topic or "data subject" in topic:
        return (
            "For privacy notices: assess rights notice coverage under Articles 13(2)(b)-(d) and 14(2)(c)-(e), "
            "then use Articles 15-21 only as supporting rights context."
        )
    if "lawful basis" in topic or "consent" in topic:
        return (
            "For privacy notices: legal basis and purpose disclosures should map to Articles 13(1)(c) and 14(1)(c). "
            "Do not use Articles 24 or 25 as substitute citations for notice disclosure duties."
        )
    if "profile" in section_ctx or "scor" in section_ctx or "segment" in section_ctx or "churn" in section_ctx:
        return (
            "The section appears to discuss profiling outputs; evaluate transparency under Articles 13(2)(f) and 14(2)(g), "
            "and reference Article 22 only conditionally if legal or similarly significant effects are explicitly indicated."
        )
    if "retention" in topic:
        return "For privacy notices: prioritize retention transparency under Articles 13(2)(a), 14(2)(a), and Article 5(1)(e)."
    return (
        "For privacy notices: check mandatory disclosures (controller identity/contact, DPO where applicable, legal basis, "
        "recipients, transfer disclosures, retention criteria, rights, and complaint rights) with Articles 12-14 priority."
    )


def _rerank_chunks_for_mode(section: SectionData, chunks: list[RetrievalChunk], document_mode: str) -> list[RetrievalChunk]:
    if not chunks:
        return chunks
    section_ctx = _section_context_signals(section)
    preferred = _preferred_articles_for_section(section, document_mode)
    allows_employment = _contains_any(section_ctx, EMPLOYMENT_SIGNALS)
    allows_ropa = _contains_any(section_ctx, ROPA_SIGNALS)

    scored: list[tuple[float, RetrievalChunk]] = []
    for ch in chunks:
        article = _article_int(ch.article_number)
        adjusted = ch.score
        if article in preferred:
            adjusted += 0.12
        if document_mode == "privacy_notice":
            if article == 88 and not allows_employment:
                adjusted -= 0.20
            if article == 30 and not allows_ropa:
                adjusted -= 0.15
            if article in PRIVACY_NOTICE_DISCOURAGED_ARTICLES:
                adjusted -= 0.05
        scored.append((adjusted, ch))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [ch for _score, ch in scored]


def _topic_keywords(topic: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", _norm(topic)) if len(w) > 3}


def _retry_needed(chunks: list[RetrievalChunk], topic: str) -> bool:
    if not chunks:
        return True
    top1 = chunks[0].score
    keys = _topic_keywords(topic)
    overlap_hits = 0
    for ch in chunks[:5]:
        txt = _norm(ch.content)
        if any(k in txt for k in keys):
            overlap_hits += 1
    return top1 < 0.45 or overlap_hits < 2


def _evidence_sufficient(chunks: list[RetrievalChunk]) -> bool:
    strong = [c for c in chunks[:5] if c.score >= 0.50]
    if len(strong) < 2:
        return False
    for c in chunks[:5]:
        txt = _norm(c.content)
        if any(k in txt for k in OBLIGATION_WORDS):
            return True
    return False


def _paragraph_ref_compatible(citation_ref: str | None, chunk_ref: str | None) -> bool:
    if not citation_ref or not chunk_ref:
        return True
    a = _norm(citation_ref)
    b = _norm(chunk_ref)
    return a == b or a in b or b in a


def _claim_types_from_text(text: str) -> set[str]:
    norm = _norm(text)
    claims: set[str] = set()
    if any(token in norm for token in {"legal basis", "lawful basis", "article 6"}):
        claims.add("legal_basis")
    if any(token in norm for token in {"retention", "storage period", "kept for"}):
        claims.add("retention")
    if any(token in norm for token in {"rights", "access", "erasure", "portability", "rectification"}):
        claims.add("rights")
    if any(token in norm for token in {"right to object", "object to processing", "direct marketing"}):
        claims.add("right_to_object")
    if any(token in norm for token in {"controller identity", "contact details", "controller"}):
        claims.add("controller_contact")
    if any(token in norm for token in {"supervisory authority", "complaint"}):
        claims.add("complaint")
    if any(token in norm for token in {"transfer", "third country", "adequacy", "safeguards"}):
        claims.add("transfer")
    if any(token in norm for token in {"special category", "sensitive data", "article 9", "explicit consent"}):
        claims.add("sensitive_data")
    if any(token in norm for token in {"profiling", "automated decision", "article 22", "meaningful information about logic"}):
        claims.add("profiling")
    return claims


def _citation_claim_compatible(citation: LlmCitation, chunk: RetrievalChunk, claim_types: set[str]) -> bool:
    if not claim_types:
        return True
    article = _article_int(citation.article_number)
    para = _norm(chunk.paragraph_ref or citation.paragraph_ref or "")
    para_known = bool(para)
    if article is None:
        return False

    allowed = False
    if "legal_basis" in claim_types:
        allowed = allowed or (article in {6}) or (article in {13, 14} and (not para_known or para.startswith("1")))
    if "retention" in claim_types:
        allowed = allowed or (article == 5) or (article in {13, 14} and (not para_known or para.startswith("2")))
    if "rights" in claim_types:
        allowed = allowed or (article == 12) or (article in {13, 14} and (not para_known or para.startswith("2"))) or (
            article in {15, 16, 17, 18, 19, 20, 22}
        )
        if "right_to_object" in claim_types:
            allowed = allowed or article == 21
    if "controller_contact" in claim_types:
        allowed = allowed or (article in {13, 14} and (not para_known or para.startswith("1")))
    if "complaint" in claim_types:
        allowed = allowed or (article in {13, 14} and (not para_known or para.startswith("2"))) or article == 77
    if "transfer" in claim_types:
        if article in {44, 45, 46, 47, 49}:
            allowed = True
        elif article in {13, 14}:
            transfer_terms = {"third country", "international transfer", "outside the eea", "outside eea", "safeguard"}
            content = _norm(chunk.content)
            has_transfer_content = any(term in content for term in transfer_terms)
            allowed = allowed or ((not para_known or para.startswith("1")) and has_transfer_content)
    if "sensitive_data" in claim_types:
        allowed = allowed or article in {9, 13, 14}
    if "profiling" in claim_types:
        norm_text = _norm(chunk.content)
        has_significant_effect_signal = any(
            t in norm_text for t in {"legal effect", "similarly significant", "automated decision-making", "article 22"}
        )
        if article in {13, 14}:
            allowed = True
        elif article == 22:
            allowed = allowed or has_significant_effect_signal
    return allowed


def _claim_has_primary_anchor(claim_types: set[str], citations: list[LlmCitation]) -> bool:
    if not claim_types:
        return bool(citations)
    article_set = {_article_int(c.article_number) for c in citations}
    for claim in claim_types:
        allowed = CLAIM_PRIMARY_ARTICLES.get(claim)
        if not allowed:
            continue
        if not any(article in allowed for article in article_set):
            return False
    return True


def _claim_type_to_issue_id(claim_type: str) -> str:
    mapping = {
        "controller_contact": "missing_controller_identity",
        "legal_basis": "missing_legal_basis",
        "retention": "missing_retention_period",
        "rights": "missing_rights_notice",
        "complaint": "missing_complaint_right",
        "transfer": "missing_transfer_disclosure",
        "profiling": "missing_profiling_logic",
        "sensitive_data": "missing_special_category_basis",
        "right_to_object": "missing_rights_notice",
    }
    return mapping.get(claim_type, claim_type)


def _claim_issue_ids(claim_types: set[str]) -> set[str]:
    return {_claim_type_to_issue_id(c) for c in claim_types}


def _most_specific_article_for_claim(claim_type: str, available_articles: set[int]) -> int | None:
    preference = {
        "legal_basis": [6, 13, 14, 5],
        "retention": [13, 14, 5],
        "rights": [13, 14, 12, 21, 22, 15, 16, 17, 18, 19, 20],
        "right_to_object": [21, 13, 14, 12],
        "controller_contact": [13, 14, 12],
        "complaint": [13, 14, 77, 12],
        "transfer": [13, 14, 46, 45, 44, 47, 49],
        "sensitive_data": [9, 13, 14, 6],
        "profiling": [13, 14, 22, 21],
    }
    for article in preference.get(claim_type, []):
        if article in available_articles:
            return article
    return None


def _applicability_memo(section: SectionData, claim_types: set[str], posture: DocumentPosture) -> ApplicabilityMemo:
    mode = _collection_mode(section)
    visibility = "visible"
    if len(section.content.strip()) < 140:
        visibility = "not_assessable"
    elif any(token in _norm(section.content) for token in {"may", "might", "where applicable"}):
        visibility = "inferred"
    obligation = ", ".join(sorted(claim_types)) if claim_types else "mandatory transparency disclosures"
    alternatives = ["internal governance articles (24/25/30/32) for external notice gaps"]
    if mode in {"direct", "indirect"}:
        alternatives.append(f"using Article {'14' if mode == 'direct' else '13'} as primary notice article")
    confidence = 0.78 if visibility == "visible" else 0.58 if visibility == "inferred" else 0.35
    if "excerpt" in posture["document_type"]:
        confidence = max(0.25, confidence - 0.2)
    return ApplicabilityMemo(
        obligation=obligation,
        applicability_reasoning=(
            f"Section posture={posture['document_type']}; collection_mode={mode}; "
            f"triggered duties={', '.join(posture['triggered_duties']) or 'none'}."
        ),
        collection_mode=mode,
        visibility=visibility,
        applicability_confidence=round(confidence, 2),
        disqualifying_alternatives=alternatives,
    )


def _reviewer_agent(
    finding: LlmFinding,
    citations: list[LlmCitation],
    claim_types: set[str],
    memo: ApplicabilityMemo,
) -> tuple[LlmFinding, list[LlmCitation]]:
    if finding.status not in {"gap", "partial"}:
        return finding, citations
    if memo["visibility"] == "not_assessable":
        return (
            LlmFinding(
                status="needs review",
                severity=None,
                gap_note="Not assessable from excerpt: legal trigger is conditional or evidence is incomplete.",
                remediation_note="Obtain the complete privacy notice section to complete legal qualification.",
                citations=[],
            ),
            [],
        )
    if not citations:
        return finding, citations

    available_articles = {_article_int(c.article_number) for c in citations if _article_int(c.article_number) is not None}
    selected: list[LlmCitation] = []
    used_articles: set[int] = set()
    for claim in sorted(claim_types):
        best = _most_specific_article_for_claim(claim, available_articles)
        if best is None or best in used_articles:
            continue
        chosen = next((c for c in citations if _article_int(c.article_number) == best), None)
        if chosen:
            selected.append(chosen)
            used_articles.add(best)
    if selected:
        citations = selected[:3]
    return finding, citations


def _has_claim_citation_contradiction(claim_types: set[str], citations: list[LlmCitation]) -> bool:
    issue_ids = _claim_issue_ids(claim_types)
    articles = {_article_int(c.article_number) for c in citations}
    for issue in issue_ids:
        rules = CLAIM_ARTICLE_RULES.get(issue)
        if not rules:
            continue
        disallowed = rules.get("disallowed", set())
        if any(a in disallowed for a in articles if a is not None):
            return True
        allowed = rules.get("primary", set()) | rules.get("support", set())
        if allowed and not any(a in allowed for a in articles if a is not None):
            return True
    return False


def _citation_diagnostic_reason(section: SectionData, claim_types: set[str], source_mode: str) -> str:
    if not claim_types:
        return "No claim type could be inferred from the finding text."
    if source_mode == "unknown":
        return "Collection source mode is ambiguous; Article 13 vs 14 applicability could not be confirmed."
    missing = ", ".join(sorted(claim_types))
    return f"Validated citations did not satisfy primary legal anchors for claims: {missing}."


def _fallback_claim_types_from_section(section: SectionData) -> set[str]:
    topic = _norm(_infer_topic(section))
    inferred: set[str] = set()
    if "retention" in topic:
        inferred.add("retention")
    if "rights" in topic or "data subject" in topic:
        inferred.add("rights")
    if "transfer" in topic or "international" in topic:
        inferred.add("transfer")
    if "consent" in topic or "lawful basis" in topic:
        inferred.add("legal_basis")
    section_ctx = _section_context_signals(section)
    if _contains_any(section_ctx, {"controller", "contact", "dpo"}):
        inferred.add("controller_contact")
    return inferred


def _finding_mentions_internal_control_only(text: str) -> bool:
    norm = _norm(text)
    internal_signals = {
        "personal data breach",
        "breach notification authority",
        "incident response",
        "undue delay",
        "article 33",
        "article 34",
        "article 70",
    }
    return any(s in norm for s in internal_signals)


def _is_legally_relevant_citation(citation: LlmCitation, section: SectionData, document_mode: str) -> bool:
    article = _article_int(citation.article_number)
    if article is None:
        return False
    section_ctx = _section_context_signals(section)
    if document_mode == "privacy_notice":
        if article not in PRIVACY_NOTICE_SCOPE_PRIMARY:
            return False
        if article in {24, 25, 33, 34, 70, 18}:
            return False
        if article == 88 and not _contains_any(section_ctx, EMPLOYMENT_SIGNALS):
            return False
        if article == 30 and not _contains_any(section_ctx, ROPA_SIGNALS):
            return False
        if article in {44, 45, 46, 47, 49} and not _contains_any(section_ctx, THIRD_COUNTRY_TRANSFER_SIGNALS):
            return False
    preferred = _preferred_articles_for_section(section, document_mode)
    if article in preferred:
        return True
    if document_mode == "internal_policy":
        return True
    return article in {1, 2, 3, 4}


def _validate_citations(
    citations: list[LlmCitation],
    retrieved: list[RetrievalChunk],
    section: SectionData,
    document_mode: str,
    claim_text: str = "",
) -> list[LlmCitation]:
    by_chunk = {c.chunk_id: c for c in retrieved}
    claim_types = _claim_types_from_text(claim_text)
    if not claim_types:
        claim_types = _fallback_claim_types_from_section(section)
    valid: list[LlmCitation] = []
    source_mode = _collection_mode(section)
    for cit in citations:
        chunk = by_chunk.get(cit.chunk_id)
        if not chunk:
            citation_validation_failure_total.inc()
            continue
        cit_article = _article_int(cit.article_number)
        chunk_article = _article_int(chunk.article_number)
        if cit_article is not None and chunk_article is not None:
            if cit_article != chunk_article:
                citation_validation_failure_total.inc()
                continue
        elif str(cit.article_number).strip() != str(chunk.article_number).strip():
            citation_validation_failure_total.inc()
            continue
        if not _paragraph_ref_compatible(cit.paragraph_ref, chunk.paragraph_ref):
            citation_validation_failure_total.inc()
            continue
        if not cit.chunk_id:
            citation_validation_failure_total.inc()
            continue
        if not _is_legally_relevant_citation(cit, section, document_mode):
            citation_validation_failure_total.inc()
            continue
        if document_mode == "privacy_notice" and not _citation_claim_compatible(cit, chunk, claim_types):
            citation_validation_failure_total.inc()
            continue
        if document_mode == "privacy_notice":
            article = _article_int(cit.article_number)
            if source_mode == "direct" and article == 14 and claim_types & {
                "controller_contact",
                "legal_basis",
                "retention",
                "rights",
                "complaint",
            }:
                citation_validation_failure_total.inc()
                continue
            if source_mode == "indirect" and article == 13 and claim_types & {
                "controller_contact",
                "legal_basis",
                "retention",
                "rights",
                "complaint",
            }:
                citation_validation_failure_total.inc()
                continue

        if not cit.excerpt:
            cit.excerpt = chunk.content[:180]
        if not cit.article_title:
            cit.article_title = chunk.article_title
        valid.append(cit)

    if valid and document_mode == "privacy_notice" and not _claim_has_primary_anchor(claim_types, valid):
        return []
    if valid and _has_claim_citation_contradiction(claim_types, valid):
        return []
    return valid


def _citation_priority_for_notice(section: SectionData, chunk: RetrievalChunk) -> float:
    article = _article_int(chunk.article_number)
    if article is None:
        return -1.0
    section_ctx = _section_context_signals(section)
    paragraph = _norm(chunk.paragraph_ref or "")
    score = 0.0
    source_mode = _collection_mode(section)
    if article in {13, 14}:
        score += 3.0
        if paragraph in {"1", "2", "1-2", "1(a)-(c)", "2(a)-(e)"}:
            score += 1.8
        if paragraph.startswith("3") or paragraph.startswith("4") or paragraph.startswith("5"):
            score -= 3.0
        if source_mode == "direct" and article == 13:
            score += 1.0
        if source_mode == "indirect" and article == 14:
            score += 1.0
        if source_mode == "direct" and article == 14:
            score -= 0.7
        if source_mode == "indirect" and article == 13:
            score -= 0.7
    if article == 12:
        score += 2.0
    if article == 5:
        score += 1.4
    if article in {44, 45, 46, 49} and _contains_any(section_ctx, THIRD_COUNTRY_TRANSFER_SIGNALS):
        score += 1.2
    if article == 44 and not _contains_any(section_ctx, THIRD_COUNTRY_TRANSFER_SIGNALS):
        score -= 1.2
    return score


def _fallback_notice_citations(section: SectionData, chunks: list[RetrievalChunk]) -> list[LlmCitation]:
    candidates: list[tuple[float, RetrievalChunk]] = []
    for ch in chunks:
        article = _article_int(ch.article_number)
        if article not in {5, 12, 13, 14, 44, 45, 46, 49}:
            continue
        priority = _citation_priority_for_notice(section, ch)
        if priority <= 0:
            continue
        candidates.append((priority, ch))

    candidates.sort(key=lambda x: x[0], reverse=True)
    fallback: list[LlmCitation] = []
    for _priority, ch in candidates:
        fallback.append(
            LlmCitation(
                chunk_id=ch.chunk_id,
                article_number=ch.article_number,
                paragraph_ref=ch.paragraph_ref,
                article_title=ch.article_title,
                excerpt=ch.content[:180],
            )
        )
        if len(fallback) >= 3:
            break
    return fallback


def _missing_notice_requirements(section: SectionData) -> list[str]:
    text = _section_context_signals(section)
    if not _is_notice_disclosure_section(section):
        return []
    missing: list[str] = []
    for req, signals in NOTICE_REQUIREMENT_SIGNALS.items():
        if not _contains_any(text, signals):
            missing.append(req)
    return missing


def _is_notice_disclosure_section(section: SectionData) -> bool:
    title = _norm(section.section_title)
    text = _section_context_signals(section)
    title_hits = sum(1 for signal in NOTICE_SECTION_TITLE_SIGNALS if signal in title)
    content_hits = sum(1 for signal in NOTICE_SECTION_CONTENT_SIGNALS if signal in text)
    if title_hits >= 1:
        return True
    if content_hits >= 2:
        return True
    return "we collect" in text and ("you" in text or "personal data" in text)


def _collection_mode(section: SectionData) -> str:
    ctx = _section_context_signals(section)
    direct_score = sum(1 for signal in DIRECT_COLLECTION_SIGNALS if signal in ctx)
    direct_score += sum(1 for hint in DIRECT_COLLECTION_HINTS if hint in ctx)
    indirect_score = sum(1 for signal in INDIRECT_COLLECTION_SIGNALS if signal in ctx)
    indirect_score += sum(1 for hint in INDIRECT_COLLECTION_HINTS if hint in ctx)

    has_direct = direct_score > 0
    has_indirect = indirect_score > 0
    if has_direct and has_indirect:
        return "mixed"
    if has_indirect:
        return "indirect"
    if has_direct:
        return "direct"
    if "we collect" in ctx and "personal data" in ctx:
        return "direct"
    if "we collect" in ctx and "you" in ctx:
        return "direct"
    if ("we receive" in ctx or "we obtain" in ctx) and "from" in ctx:
        return "indirect"
    return "unknown"


def _targeted_notice_query(section: SectionData) -> str:
    mode = _collection_mode(section)
    if mode == "direct":
        focus = "GDPR Article 13(1)(a)-(f) and 13(2)(a)-(e) mandatory privacy notice disclosures"
    elif mode == "indirect":
        focus = "GDPR Article 14(1)(a)-(f) and 14(2)(a)-(e) mandatory privacy notice disclosures"
    else:
        focus = "GDPR Articles 13 and 14 mandatory privacy notice disclosures for direct or indirect collection"
    return f"{focus}. Section context: {section.section_title}. {section.content[:600]}"


def _claim_template_query(section: SectionData, claim_types: set[str]) -> str:
    if "transfer" in claim_types:
        return (
            f"GDPR privacy notice transfer disclosure requirements: Articles 13(1)(f), 14(1)(f), 44-49; "
            f"include adequacy, SCC/BCR safeguards, and how data subjects can obtain safeguard copies. "
            f"Section: {section.section_title}. {section.content[:650]}"
        )
    if "profiling" in claim_types:
        return (
            f"GDPR profiling notice obligations: Articles 13(2)(f), 14(2)(g), and Article 22 threshold test "
            f"(logic, significance, consequences). Section: {section.section_title}. {section.content[:650]}"
        )
    if "retention" in claim_types:
        return (
            f"GDPR retention notice obligations: Articles 13(2)(a), 14(2)(a), Article 5(1)(e). "
            f"Section: {section.section_title}. {section.content[:650]}"
        )
    if "complaint" in claim_types:
        return (
            f"GDPR complaint-right notice obligations: Articles 13(2)(d), 14(2)(e), and Article 77. "
            f"Section: {section.section_title}. {section.content[:650]}"
        )
    if "legal_basis" in claim_types:
        return (
            f"GDPR legal basis notice obligations: Article 6, Articles 13(1)(c), 14(1)(c), purposes and lawful basis mapping. "
            f"Section: {section.section_title}. {section.content[:650]}"
        )
    return _targeted_notice_query(section)


def _tailored_notice_gap_note(section: SectionData, missing: list[str]) -> str:
    labels = [NOTICE_REQUIREMENT_LABELS.get(item, item) for item in missing]
    missing_text = ", ".join(labels)
    mode = _collection_mode(section)
    if mode == "indirect":
        basis = "Articles 14(1)-(2)"
    elif mode == "direct":
        basis = "Articles 13(1)-(2)"
    else:
        basis = "Articles 13(1)-(2) and 14(1)-(2)"
    return (
        f"The section appears to omit mandatory privacy-notice disclosures: {missing_text}. "
        f"Based on the excerpt, this indicates incomplete transparency duties under {basis}."
    )


def _tailored_notice_remediation(section: SectionData, missing: list[str]) -> str:
    items: list[str] = []
    if "controller_contact" in missing:
        items.append("identify the specific controller entity and add contact details")
    if "legal_basis" in missing:
        items.append("state legal basis per purpose")
    if "rights" in missing:
        items.append("add a full data-subject-rights section")
    if "retention" in missing:
        items.append("provide retention period or criteria")
    if "complaint" in missing:
        items.append("include supervisory-authority complaint-right information")
    text = "; ".join(items) if items else "add missing transparency disclosures"
    return f"Update the notice to {text}, with article-level mapping in Articles 13/14."


def _build_mandatory_notice_gap(section: SectionData, chunks: list[RetrievalChunk]) -> LlmFinding | None:
    missing = _missing_notice_requirements(section)
    if len(missing) < 2:
        return None
    citations = _fallback_notice_citations(section, chunks)
    if not citations:
        return None
    return LlmFinding(
        status="gap",
        severity="high" if len(missing) >= 3 else "medium",
        gap_note=_tailored_notice_gap_note(section, missing),
        remediation_note=_tailored_notice_remediation(section, missing),
        citations=citations,
    )


def _build_transfer_gap(section: SectionData, chunks: list[RetrievalChunk]) -> LlmFinding | None:
    section_ctx = _section_context_signals(section)
    if not _contains_any(section_ctx, THIRD_COUNTRY_TRANSFER_SIGNALS):
        return None

    transfer_chunks = [ch for ch in chunks if _article_int(ch.article_number) in {44, 45, 46, 47, 49, 13, 14}]
    if not transfer_chunks:
        return None

    transfer_chunks.sort(
        key=lambda ch: (0 if _article_int(ch.article_number) in {44, 45, 46, 47, 49} else 1, -ch.score)
    )

    citations: list[LlmCitation] = []
    for ch in transfer_chunks[:3]:
        citations.append(
            LlmCitation(
                chunk_id=ch.chunk_id,
                article_number=ch.article_number,
                paragraph_ref=ch.paragraph_ref,
                article_title=ch.article_title,
                excerpt=ch.content[:180],
            )
        )

    return LlmFinding(
        status="gap",
        severity="medium",
        gap_note=(
            "The section indicates international or third-country transfers but does not clearly disclose "
            "transfer mechanism details (adequacy decision or safeguards), as required for transparent disclosures."
        ),
        remediation_note=(
            "Disclose whether transfers rely on adequacy decisions (Article 45) or safeguards such as SCCs (Article 46), "
            "and specify relevant third-country transfer information in the notice."
        ),
        citations=citations,
    )


def _build_retention_gap(section: SectionData, chunks: list[RetrievalChunk]) -> LlmFinding | None:
    candidates = [ch for ch in chunks if _article_int(ch.article_number) in {5, 13, 14}]
    if not candidates:
        return None
    candidates.sort(key=lambda ch: (0 if _article_int(ch.article_number) in {13, 14} else 1, -ch.score))
    citations = [
        LlmCitation(
            chunk_id=ch.chunk_id,
            article_number=ch.article_number,
            paragraph_ref=ch.paragraph_ref,
            article_title=ch.article_title,
            excerpt=ch.content[:180],
        )
        for ch in candidates[:2]
    ]
    return LlmFinding(
        status="gap",
        severity="medium",
        gap_note=(
            "The section does not clearly disclose the retention period or the criteria used to determine retention duration, "
            "which is required for privacy-notice transparency."
        ),
        remediation_note=(
            "Add retention period or objective retention criteria for each relevant data category, mapped to Articles 13(2)(a) and 14(2)(a), "
            "and align storage-limitation language with Article 5(1)(e)."
        ),
        citations=citations,
    )


def _salvage_citations_from_retrieved(
    chunks: list[RetrievalChunk],
    section: SectionData,
    document_mode: str,
    claim_text: str,
) -> list[LlmCitation]:
    claim_types = _claim_types_from_text(claim_text)
    candidates: list[LlmCitation] = []
    for ch in chunks:
        cit = LlmCitation(
            chunk_id=ch.chunk_id,
            article_number=ch.article_number,
            paragraph_ref=ch.paragraph_ref,
            article_title=ch.article_title,
            excerpt=ch.content[:180],
        )
        if not _is_legally_relevant_citation(cit, section, document_mode):
            continue
        if document_mode == "privacy_notice" and not _citation_claim_compatible(cit, ch, claim_types):
            continue
        candidates.append(cit)
        if len(candidates) >= 3:
            break
    return candidates


def _sanitize_legal_reference_text(text: str | None) -> str | None:
    if not text:
        return text
    fixed = text
    fixed = re.sub(r"Article\s*14\(1\)\(f\)", "Article 14(1)(c)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"Article\s*14\(a\)", "Article 14(1)(a)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"Article\s*14\(c\)", "Article 14(1)(c)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"Article\s*13\(a\)", "Article 13(1)(a)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"Article\s*13\(b\)", "Article 13(1)(b)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"Article\s*13\(c\)", "Article 13(1)(c)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(r"Article\s*14\(b\)", "Article 14(1)(b)", fixed, flags=re.IGNORECASE)
    fixed = re.sub(
        r"Article\s*13\(1\)\(f\)\s+as\s+the\s+legal\s+basis",
        "Article 6(1) as the legal basis (and Article 13(1)(f) only for transfer disclosures)",
        fixed,
        flags=re.IGNORECASE,
    )
    return fixed


def _clean_remediation_legal_mismatches(remediation: str | None, claim_types: set[str]) -> str | None:
    if not remediation:
        return remediation
    cleaned = remediation
    if "legal_basis" in claim_types and re.search(r"article\s*13\(1\)\(f\).{0,30}legal basis", cleaned, flags=re.IGNORECASE):
        cleaned = re.sub(
            r"Article\s*13\(1\)\(f\)",
            "Article 6(1) and Article 13(1)(c)",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _specialized_legal_review(section: SectionData, claim_types: set[str]) -> SpecializedReview:
    text = _section_context_signals(section)
    profiling = None
    if any(t in text for t in {"profil", "score", "ranking", "segmentation", "predictive", "automated decision"}):
        has_effect = any(t in text for t in {"legal effect", "similarly significant", "automated decision"})
        if has_effect:
            profiling = "Profiling appears present; Article 22 threshold may be triggered in addition to Articles 13(2)(f)/14(2)(g)."
        else:
            profiling = "Profiling indicators found; anchor first in Articles 13(2)(f)/14(2)(g), with Article 21 secondary."

    transfer = None
    if "transfer" in claim_types or _contains_any(text, THIRD_COUNTRY_TRANSFER_SIGNALS):
        has_mechanism = any(t in text for t in {"adequacy", "standard contractual clauses", "scc", "binding corporate rules", "article 46", "article 49"})
        transfer = (
            "Transfer context detected; notice disclosure and mechanism disclosure both appear."
            if has_mechanism
            else "Transfer context detected; likely notice gap on safeguards/mechanism disclosure."
        )

    special_category = None
    if any(t in text for t in {"health", "biometric", "religious", "political", "ethnic", "genetic"}):
        has_art9 = any(t in text for t in {"article 9", "explicit consent", "substantial public interest"})
        special_category = (
            "Special-category indicators present with Article 9 condition reference."
            if has_art9
            else "Special-category indicators present without clear Article 9 condition."
        )

    role_allocation = None
    if any(t in text for t in {"controller", "processor", "on behalf of", "customer instructions"}):
        has_both_roles = "controller" in text and "processor" in text
        role_allocation = (
            "Controller/processor role boundary appears mixed; verify role-allocation clarity."
            if has_both_roles
            else "Single role stated; verify if role-switch scenarios are disclosed."
        )

    return SpecializedReview(
        profiling=profiling,
        transfer=transfer,
        special_category=special_category,
        role_allocation=role_allocation,
    )


def _apply_applicability_gate_to_citations(
    citations: list[LlmCitation], decision: ApplicabilityDecision, claim_types: set[str]
) -> list[LlmCitation]:
    if not citations:
        return citations
    if not decision["allowed_notice_articles"]:
        restricted_claims = {"controller_contact", "legal_basis", "retention", "rights", "complaint"}
        if claim_types & restricted_claims:
            return []
        return citations
    allowed_articles = set(decision["allowed_notice_articles"]) | {5, 6, 9, 12, 21, 22, 44, 45, 46, 47, 49, 77}
    gated = [c for c in citations if (_article_int(c.article_number) or -1) in allowed_articles]
    return gated


def _violates_forbidden_article_matrix(claim_types: set[str], citations: list[LlmCitation]) -> bool:
    articles = {_article_int(c.article_number) for c in citations if _article_int(c.article_number) is not None}
    if "complaint" in claim_types and 21 in articles:
        return True
    if "transfer" in claim_types and 15 in articles:
        return True
    if "legal_basis" in claim_types and ({13, 14} & articles) and ("transfer" not in claim_types):
        bad_paragraph = any(
            (_article_int(c.article_number) in {13, 14}) and _norm(c.paragraph_ref or "").startswith("1(f)") for c in citations
        )
        if bad_paragraph:
            return True
    if "profiling" in claim_types and 22 in articles:
        # Article 22 must be support unless significant-effects signal is present elsewhere.
        primary_22_only = len(articles) == 1
        if primary_22_only:
            return True
    return False


def _coerce_finding(f: LlmFinding | None) -> LlmFinding:
    if f is None:
        return LlmFinding(status="needs review", severity=None, gap_note="LLM parse failure", remediation_note=None, citations=[])

    if f.status in {"gap", "partial"}:
        if not f.severity:
            f.severity = "medium"
        if not f.gap_note:
            f.gap_note = "Insufficient policy coverage against retrieved GDPR obligations."
        if not f.remediation_note:
            f.remediation_note = "Add explicit policy language to address the cited GDPR obligations."
    else:
        f.severity = None
        if f.status in {"compliant", "needs review"}:
            if f.status != "needs review":
                f.gap_note = None
                f.remediation_note = None
    return f


def _enforce_substantive_citation_gate(f: LlmFinding, valid_citations: list[LlmCitation]) -> LlmFinding:
    if f.status in {"gap", "partial"} and not valid_citations:
        return LlmFinding(
            status="needs review",
            severity=None,
            gap_note="Substantive finding rejected: no validated GDPR citation evidence.",
            remediation_note=None,
            citations=[],
        )
    return f


def _normalize_severity(status: str, severity: str | None, claim_types: set[str]) -> str | None:
    if status not in {"gap", "partial"}:
        return None
    high_claims = {"legal_basis", "rights", "retention", "complaint", "transfer"}
    if claim_types & high_claims:
        return "high"
    if severity in {"high", "medium", "low"}:
        return severity
    return "medium"


def _finding_signature(f: LlmFinding, citations: list[LlmCitation]) -> str:
    gap = _norm(f.gap_note or "")
    assessment_idx = gap.find("assessment:")
    gap_key = gap[assessment_idx : assessment_idx + 220] if assessment_idx >= 0 else gap[:220]
    article_key = ",".join(sorted({str(_article_int(c.article_number) or c.article_number) for c in citations}))
    return f"{f.status}|{f.severity}|{gap_key}|{article_key}"


def _ensure_reasoning_chain(f: LlmFinding, section: SectionData, citations: list[LlmCitation], claim_types: set[str]) -> LlmFinding:
    if f.status not in {"gap", "partial"}:
        return f
    gap = f.gap_note or ""
    if "Evidence:" in gap and "Requirement:" in gap and "Assessment:" in gap:
        return f
    evidence = _norm(section.content)[:220]
    requirement_articles = ", ".join(sorted({c.article_number for c in citations})) or "validated GDPR disclosure obligations"
    claim_text = ", ".join(sorted(claim_types)) if claim_types else "identified transparency obligations"
    f.gap_note = (
        f"Evidence: {evidence}. Requirement: {requirement_articles} ({claim_text}). "
        f"Assessment: {gap or 'Policy language appears incomplete against cited obligations.'}"
    )
    return f


def _classify_finding_quality(
    f: LlmFinding,
    citations: list[LlmCitation],
    claim_types: set[str],
    source_mode: str,
) -> tuple[str | None, float | None]:
    if f.status == "needs review":
        if claim_types & CORE_NOTICE_CLAIMS:
            return "probable_gap", 0.55
        return "not_assessable", 0.2
    if f.status not in {"gap", "partial"}:
        return None, None
    if not citations:
        if claim_types & CORE_NOTICE_CLAIMS:
            return "probable_gap", 0.58
        return "not_assessable", 0.2
    has_primary = _claim_has_primary_anchor(claim_types, citations)
    if not has_primary:
        return "not_assessable", 0.25
    contradiction_penalty = 0.2 if _has_claim_citation_contradiction(claim_types, citations) else 0.0
    source_bonus = 0.1 if source_mode in {"direct", "indirect"} else 0.0
    evidence_conf = min(0.35, 0.12 * len(citations))
    applicability_conf = 0.30 if source_mode in {"direct", "indirect", "mixed"} else 0.15
    qualification_conf = 0.25 if has_primary else 0.12
    base_confidence = max(
        0.2,
        min(
            0.95,
            evidence_conf + applicability_conf + qualification_conf + source_bonus - contradiction_penalty,
        ),
    )
    if source_mode == "unknown" and any(claim in {"controller_contact", "legal_basis", "retention", "rights", "complaint"} for claim in claim_types):
        return "probable_gap", round(base_confidence - 0.1, 2)
    if f.status == "gap":
        return "clear_non_compliance", round(base_confidence + 0.15, 2)
    return "probable_gap", round(base_confidence, 2)


def _runtime_budget_exceeded(started_monotonic: float, now_monotonic: float, budget_seconds: int) -> bool:
    return (now_monotonic - started_monotonic) > budget_seconds


def _effective_llm_budget(section_count: int, configured_cap: int) -> int:
    if section_count <= 0:
        return configured_cap
    if section_count <= configured_cap:
        return configured_cap
    scaled_budget = max(12, round(section_count * 0.85))
    return min(configured_cap, scaled_budget)


def _add_notice_level_synthesis(db: Session, audit_id: str, obligation_map: dict[str, bool]) -> None:
    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    corpus = " ".join(_norm(f"{r.gap_note or ''} {r.remediation_note or ''}") for r in rows if r.status in {"gap", "partial"})
    existing_obligations = {_norm(r.obligation_under_review or "") for r in rows}
    mandatory = {
        "legal basis": ("missing_legal_basis", "high"),
        "retention": ("missing_retention_period", "medium"),
        "rights": ("missing_rights_notice", "medium"),
        "complaint": ("missing_complaint_right", "medium"),
        "controller": ("missing_controller_identity", "high"),
    }
    systemic_wording = {
        "missing_legal_basis": "The notice does not explain the lawful basis for each processing purpose.",
        "missing_retention_period": "The notice does not provide retention periods or objective retention criteria by data category.",
        "missing_rights_notice": "The notice does not describe data subject rights, including access, erasure, restriction, objection, and portability.",
        "missing_complaint_right": "The notice does not explain the right to lodge a complaint with a supervisory authority.",
        "missing_controller_identity": "The notice does not clearly identify the controller legal entity and contact route.",
    }
    to_add: list[tuple[str, str]] = []
    for token, (issue_id, severity) in mandatory.items():
        if issue_id == "missing_legal_basis":
            has_legal_basis_issue = ("legal basis" in corpus) or ("legal_basis" in existing_obligations) or obligation_map.get("legal_basis_present", False)
            if not has_legal_basis_issue:
                to_add.append((issue_id, severity))
            continue
        if token not in corpus:
            to_add.append((issue_id, severity))
    for issue_id, severity in to_add:
        db.add(
            Finding(
                audit_id=audit_id,
                section_id=f"systemic:{issue_id}",
                status="gap",
                severity=severity,
                classification="systemic_violation",
                confidence=0.85,
                confidence_evidence=0.8,
                confidence_applicability=0.9,
                confidence_article_fit=0.9,
                confidence_synthesis=0.9,
                confidence_overall=0.85,
                finding_type="systemic",
                publish_flag="yes",
                missing_from_section="yes",
                missing_from_document="yes",
                not_visible_in_excerpt="no",
                gap_note=(
                    systemic_wording.get(
                        issue_id,
                        "The notice omits a mandatory transparency element required under Articles 13/14.",
                    )
                ),
                remediation_note=_issue_specific_remediation(issue_id, "privacy_notice", systemic=True),
            )
        )
        findings_by_status_total.labels(status="gap").inc()
        systemic_findings_published_total.inc()
    if to_add:
        db.commit()


def _add_systemic_issue_synthesis(db: Session, audit_id: str) -> None:
    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    by_issue: dict[str, list[Finding]] = {}
    for finding in rows:
        if finding.status not in {"gap", "partial"}:
            continue
        note = _norm(finding.gap_note or "")
        issue_id = "general_transparency_gap"
        for candidate in CLAIM_ARTICLE_RULES:
            if candidate.replace("_", " ") in note:
                issue_id = candidate
                break
        by_issue.setdefault(issue_id, []).append(finding)

    for issue_id, group in by_issue.items():
        if issue_id == "general_transparency_gap":
            continue
        if len(group) < 2:
            continue
        supporting_sections = ", ".join(sorted({g.section_id for g in group})[:6])
        db.add(
            Finding(
                audit_id=audit_id,
                section_id=f"systemic:{issue_id}",
                status="gap",
                severity="medium" if issue_id in {"missing_complaint_right", "missing_retention_period"} else ("high" if len(group) >= 3 else "medium"),
                classification="systemic_violation",
                confidence=0.88 if len(group) >= 3 else 0.8,
                confidence_evidence=0.82,
                confidence_applicability=0.86,
                confidence_article_fit=0.84,
                confidence_synthesis=0.9,
                confidence_overall=0.88 if len(group) >= 3 else 0.8,
                finding_type="systemic",
                publish_flag="yes",
                missing_from_section="yes",
                missing_from_document="yes",
                not_visible_in_excerpt="no",
                gap_note=(
                    f"The notice shows a repeated '{issue_id.replace('_', ' ')}' transparency defect across sections "
                    f"[{supporting_sections}], indicating a document-level compliance gap."
                ),
                remediation_note=_issue_specific_remediation(issue_id, "privacy_notice", systemic=True),
            )
        )
        findings_by_status_total.labels(status="gap").inc()
        systemic_findings_published_total.inc()
    db.commit()


def _finding_issue_id(row: Finding) -> str | None:
    if row.section_id.startswith("systemic:"):
        return row.section_id.split("systemic:", 1)[1]
    text = _norm(f"{row.gap_note or ''} {row.remediation_note or ''} {row.obligation_under_review or ''}")
    for issue in CLAIM_ARTICLE_RULES:
        if issue.replace("_", " ") in text:
            return issue
    return None


def _section_ref(section: SectionData) -> str:
    short_title = section.section_title.strip() if section.section_title.strip() else f"Section {section.section_order}"
    return f"section:{section.id}:{short_title}"


def _serialize_json_list(values: list[str]) -> str:
    unique = list(dict.fromkeys(v for v in values if v))
    return json.dumps(unique, ensure_ascii=False)


def _systemic_evidence_refs(issue_id: str, sections: list[SectionData], obligation_map: dict[str, bool]) -> tuple[list[str], bool]:
    section_signals = SYSTEMIC_SECTION_SIGNALS.get(issue_id, {"process", "collect", "personal data"})
    ranked_sections = sorted(
        sections,
        key=lambda s: (
            0 if _section_auditability_type(s) == "auditable_primary" else 1 if _section_auditability_type(s) == "auditable_secondary" else 2,
            s.section_order,
        ),
    )
    matched_sections: list[str] = []
    for section in ranked_sections:
        haystack = _section_context_signals(section)
        if _section_auditability_type(section) in {"administrative_section", "meta_section", "definition_section"}:
            continue
        if any(signal in haystack for signal in section_signals):
            matched_sections.append(_section_ref(section))
        if len(matched_sections) >= 3:
            break
    obligation_key = SYSTEMIC_REQUIRED_OBLIGATION_KEYS.get(issue_id)
    omission_basis = False
    if obligation_key:
        if obligation_map.get(obligation_key) is False:
            matched_sections.append(f"obligation_map:{obligation_key}=not_visible")
            omission_basis = True
        else:
            matched_sections.append(f"obligation_map:{obligation_key}=visible")
    return list(dict.fromkeys(matched_sections)), omission_basis


def _systemic_summary_text(issue_id: str, refs: list[str], omission_basis: bool) -> str:
    base = {
        "missing_controller_identity": "The notice describes personal-data processing contexts but does not clearly disclose controller identity/contact details across the document.",
        "missing_legal_basis": "The notice describes multiple processing contexts but no lawful basis is disclosed anywhere in the notice.",
        "missing_retention_period": "The notice references processing activities but does not state retention periods or objective retention criteria for relevant data categories.",
        "missing_rights_notice": "The notice indicates personal-data processing yet does not provide a complete rights disclosure set.",
        "missing_complaint_right": "The notice lacks a complaint-right disclosure even though it presents processing activities requiring transparency.",
        "missing_transfer_notice": "The notice indicates transfer contexts but does not provide the required third-country transfer disclosure wording.",
        "profiling_disclosure_gap": "The notice references profiling-like processing but does not provide required profiling transparency details.",
    }.get(issue_id, "The notice-level evidence indicates a missing transparency obligation.")
    if omission_basis:
        return f"{base} Omission basis confirmed via document obligation map and section-level processing references."
    if refs:
        return f"{base} Evidence sections reviewed: {', '.join(refs[:3])}."
    return base


def _coverage_to_support_valid(issue_id: str, refs: list[str], obligation_map: dict[str, bool], anchors: list[str]) -> bool:
    if not anchors or not refs:
        return False
    has_processing_evidence = any(r.startswith("section:") for r in refs)
    if not has_processing_evidence:
        return False
    required_key = SYSTEMIC_REQUIRED_OBLIGATION_KEYS.get(issue_id)
    if issue_id == "missing_controller_identity":
        identity_missing = obligation_map.get("controller_identity_present") is False
        contact_missing = obligation_map.get("controller_contact_present") is False
        if not (identity_missing or contact_missing):
            return False
    elif required_key and obligation_map.get(required_key) is not False:
        return False
    return True


def _copy_supporting_citations(db: Session, audit_id: str, systemic_row: Finding, issue_id: str) -> int:
    supporting_rows = db.query(Finding).filter(Finding.audit_id == audit_id).filter(Finding.section_id.notlike("systemic:%")).all()
    copied = 0
    for row in supporting_rows:
        if row.id == systemic_row.id:
            continue
        if _finding_issue_id(row) != issue_id:
            continue
        citations = db.query(FindingCitation).filter(FindingCitation.finding_id == row.id).limit(3 - copied).all()
        for citation in citations:
            db.add(
                FindingCitation(
                    finding_id=systemic_row.id,
                    chunk_id=citation.chunk_id,
                    article_number=citation.article_number,
                    paragraph_ref=citation.paragraph_ref,
                    article_title=citation.article_title,
                    excerpt=citation.excerpt,
                )
            )
            copied += 1
            if copied >= 3:
                return copied
    return copied


def _add_anchor_citations(db: Session, systemic_row: Finding, anchors: list[str], summary: str) -> None:
    for idx, anchor in enumerate(anchors, start=1):
        db.add(
            FindingCitation(
                finding_id=systemic_row.id,
                chunk_id=f"systemic-anchor:{systemic_row.section_id}:{idx}",
                article_number=anchor,
                paragraph_ref=None,
                article_title="Deterministic systemic legal anchor",
                excerpt=summary,
            )
        )


def _build_systemic_support(
    db: Session,
    audit_id: str,
    sections: list[SectionData],
    obligation_map: dict[str, bool],
    source_scope: str,
    source_scope_confidence: float,
    unseen_sections: list[str],
    cross_references: list[CrossReference],
) -> None:
    systemic_rows = db.query(Finding).filter(Finding.audit_id == audit_id).filter(Finding.finding_type == "systemic").all()
    if not systemic_rows:
        return

    for row in systemic_rows:
        issue_id = _finding_issue_id(row)
        if not issue_id:
            row.publish_flag = "no"
            row.support_complete = "false"
            row.citation_summary_text = "Systemic support could not resolve issue type; downgraded to internal QA."
            continue

        anchors = SYSTEMIC_ANCHOR_MAP.get(issue_id, {})
        primary = anchors.get("primary", [])
        secondary = anchors.get("secondary", [])
        refs, omission_basis = _systemic_evidence_refs(issue_id, sections, obligation_map)
        summary = _systemic_summary_text(issue_id, refs, omission_basis)
        support_valid = _coverage_to_support_valid(issue_id, refs, obligation_map, primary)

        row.primary_legal_anchor = _serialize_json_list(primary)
        row.secondary_legal_anchors = _serialize_json_list(secondary)
        row.document_evidence_refs = _serialize_json_list(refs)
        row.citation_summary_text = summary
        row.omission_basis = "true" if omission_basis else "false"
        row.support_complete = "true" if support_valid else "false"
        row.source_scope = source_scope
        row.source_scope_confidence = source_scope_confidence
        row.referenced_unseen_sections = _serialize_json_list(unseen_sections)

        existing_count = db.query(FindingCitation).filter(FindingCitation.finding_id == row.id).count()
        if existing_count == 0:
            copied = _copy_supporting_citations(db, audit_id, row, issue_id)
            if copied == 0 and primary:
                _add_anchor_citations(db, row, primary, summary)
                existing_count = len(primary)
            else:
                existing_count = copied

        publishable = bool(primary) and bool(refs) and bool(summary.strip()) and support_valid and existing_count > 0
        unseen_reference_for_issue = _issue_has_unseen_reference(issue_id, cross_references)
        excerpt_limited = source_scope in {"partial_notice_excerpt", "uncertain_scope"}
        if excerpt_limited and unseen_reference_for_issue:
            row.classification = "referenced_but_unseen"
            row.assertion_level = "referenced_but_unseen"
            row.status = "partial"
            row.confidence_overall = min(row.confidence_overall or 0.65, 0.65)
            row.confidence_synthesis = min(row.confidence_synthesis or 0.65, 0.65)
            row.confidence_level = "medium"
            row.missing_from_document = "unknown"
            row.not_visible_in_excerpt = "yes"
            row.gap_note = (
                "The reviewed excerpt refers to a later section for this topic, but that section was not included in the material reviewed."
            )
            row.citation_summary_text = (
                "Excerpt-limited assessment: topic is cross-referenced to unseen section(s); full-document compliance cannot be confirmed."
            )
        elif excerpt_limited:
            row.assertion_level = "excerpt_limited_gap"
            row.confidence_overall = min(row.confidence_overall or 0.65, 0.65)
            row.confidence_synthesis = min(row.confidence_synthesis or 0.65, 0.65)
            row.confidence_level = "medium"
            row.missing_from_document = "unknown"
            row.not_visible_in_excerpt = "yes"
            if row.gap_note:
                row.gap_note = f"The reviewed excerpt does not show: {row.gap_note}"
            if row.classification == "systemic_violation":
                row.classification = "probable_gap"
        else:
            row.assertion_level = "confirmed_document_gap"
            row.missing_from_document = "yes"
            row.not_visible_in_excerpt = "no"

        if not publishable:
            row.publish_flag = "no"
            row.finding_type = "supporting_evidence"
            row.classification = "diagnostic_internal_only"
            row.support_complete = "false"
            row.gap_note = "Systemic finding withheld from publication pending complete legal/document support package."
            contradiction_fail_total.inc()
        else:
            row.publish_flag = "yes"
            row.finding_type = "systemic"
            if row.classification not in {"referenced_but_unseen", "probable_gap"}:
                row.classification = "systemic_violation"
            row.support_complete = "true"
    db.commit()


def _record_suppression_ledger(
    db: Session,
    audit_id: str,
    issue_type: str,
    suppression_reason: str,
    suppression_validator: str,
    evidence: str,
) -> None:
    compact = hashlib.sha1(issue_type.encode("utf-8")).hexdigest()[:12]
    db.add(
        Finding(
            audit_id=audit_id,
            section_id=f"ledger:{compact}",
            status="not applicable",
            severity=None,
            classification="diagnostic_internal_only",
            finding_type="supporting_evidence",
            publish_flag="no",
            gap_note=f"Suppressed {issue_type}: {suppression_reason}",
            remediation_note=None,
            legal_requirement=f"suppression_validator={suppression_validator}",
            gap_reasoning=evidence,
        )
    )


def _has_issue_outcome(rows: list[Finding], issue_type: str) -> bool:
    for row in rows:
        issue = _finding_issue_id(row)
        if issue != issue_type:
            continue
        if row.classification in {"systemic_violation", "diagnostic_internal_only", "not_assessable", "referenced_but_unseen", "probable_gap"}:
            return True
    return False


def _enforce_core_and_specialist_completeness(
    db: Session,
    audit_id: str,
    sections: list[SectionData],
    obligation_map: dict[str, bool],
) -> None:
    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    duty_disposition: dict[str, str] = {}

    for duty, issue_type in CORE_DUTY_TO_ISSUE.items():
        obligation_key = CORE_DUTY_OBLIGATION_KEYS[duty]
        present = obligation_map.get(obligation_key)
        published_gap = any(
            r.section_id.startswith("systemic:")
            and _finding_issue_id(r) == issue_type
            and r.publish_flag == "yes"
            and r.classification in {"systemic_violation", "probable_gap", "referenced_but_unseen"}
            for r in rows
        )
        referenced_unseen = any(
            r.section_id.startswith("systemic:")
            and _finding_issue_id(r) == issue_type
            and r.publish_flag == "yes"
            and r.classification == "referenced_but_unseen"
            for r in rows
        )
        if published_gap:
            duty_disposition[duty] = "referenced_but_unseen" if referenced_unseen else "present_and_gap_found"
            continue
        if present is True:
            duty_disposition[duty] = "present_and_satisfied"
            continue
        if present is False:
            reason = f"{obligation_key}=not_visible while no publishable systemic finding survived validators"
            duty_disposition[duty] = f"not_assessable_with_reason:{reason}"
            _record_suppression_ledger(db, audit_id, issue_type, reason, "core_duty_completeness_gate", reason)
            continue
        duty_disposition[duty] = "not_assessable_with_reason:insufficient obligation-map signal"
        _record_suppression_ledger(
            db,
            audit_id,
            issue_type,
            "insufficient obligation-map signal",
            "core_duty_completeness_gate",
            "duty has no boolean presence signal",
        )

    unresolved = [duty for duty, result in duty_disposition.items() if not result]
    if unresolved:
        for row in rows:
            if row.section_id.startswith("systemic:"):
                row.publish_flag = "no"
                row.classification = "diagnostic_internal_only"
        _record_suppression_ledger(
            db,
            audit_id,
            "core_duty_publication_block",
            "one or more core duties had no final disposition",
            "core_duty_completeness_gate",
            ", ".join(unresolved),
        )

    corpus = " ".join(_section_context_signals(s) for s in sections)
    for issue_type, (signals, trigger_label) in SPECIALIST_TRIGGER_RULES.items():
        triggered = any(signal in corpus for signal in signals)
        if not triggered:
            continue
        if _has_issue_outcome(rows, issue_type):
            continue
        reason = f"{trigger_label} triggered but no final issue disposition recorded"
        _record_suppression_ledger(
            db,
            audit_id,
            issue_type,
            reason,
            "specialist_family_completeness_gate",
            f"signals={sorted(list(signals))[:4]}",
        )
    db.commit()


def _partner_review_pass(db: Session, audit_id: str) -> None:
    reviewer_pass_total.inc()
    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    systemic_issue_keys = {row.section_id.split("systemic:", 1)[1] for row in rows if row.section_id.startswith("systemic:")}
    seen_root_keys: dict[str, str] = {}
    seen_supporting_pairs: set[tuple[str, str]] = set()
    for row in rows:
        if row.finding_type is None:
            row.finding_type = "local"
        if row.finding_type == "supporting_evidence":
            row.artifact_role = "support_only"
            row.finding_level = "none"
            row.publication_state = "internal_only"
        if row.publish_flag is None:
            row.publish_flag = "no" if row.status in {"not applicable", "needs review"} else "yes"
        if row.confidence_level is None:
            row.confidence_level = _confidence_level_for(row.confidence)
        if row.assessment_type is None:
            row.assessment_type = "not_assessable" if row.classification == "not_assessable" else "probable"
        if row.severity_rationale is None:
            llm_status = row.status if row.status in {"compliant", "partial", "gap", "needs review"} else "needs review"
            row.severity_rationale = _severity_rationale(
                LlmFinding(status=llm_status, severity=row.severity, gap_note=row.gap_note, remediation_note=row.remediation_note, citations=[]),
                _claim_types_from_text(f"{row.gap_note or ''} {row.remediation_note or ''}"),
            )
        text = _norm(f"{row.gap_note or ''} {row.remediation_note or ''}")
        if row.status == "needs review":
            row.status = "partial"
            row.classification = "not_assessable"
            row.finding_type = "supporting_evidence"
            row.publish_flag = "no"
            row.artifact_role = "support_only"
            row.finding_level = "none"
            row.publication_state = "internal_only"
            if row.gap_note:
                row.gap_note = "Not assessable from provided excerpt; additional documentary context is required."
            row.remediation_note = "Provide complete notice excerpts and rerun legal qualification."
            row.confidence = min(row.confidence or 0.45, 0.45) if row.classification == "not_assessable" else max(row.confidence or 0.6, 0.6)
            continue
        if row.classification == "out_of_scope":
            row.publish_flag = "no"
            row.finding_type = "supporting_evidence"
            row.artifact_role = "support_only"
            row.finding_level = "none"
            row.publication_state = "internal_only"
            continue
        if row.status not in {"gap", "partial"}:
            continue
        key = "general"
        for issue in CLAIM_ARTICLE_RULES:
            if issue.replace("_", " ") in text:
                key = issue
                break
        if key in seen_root_keys and not row.section_id.startswith("systemic:"):
            row.status = "not applicable"
            row.classification = "supporting_evidence"
            row.finding_type = "supporting_evidence"
            row.publish_flag = "no"
            row.artifact_role = "support_only"
            row.finding_level = "none"
            row.publication_state = "internal_only"
            row.severity = None
            row.confidence = 0.7
            row.gap_note = f"Supporting evidence for systemic issue in section {seen_root_keys[key]}."
            row.remediation_note = None
            pair = (row.section_id, key)
            if pair in seen_supporting_pairs:
                db.delete(row)
                continue
            seen_supporting_pairs.add(pair)
        else:
            if row.section_id.startswith("systemic:"):
                row.finding_type = "systemic"
                support_ready = (
                    row.support_complete == "true"
                    and bool(row.primary_legal_anchor)
                    and bool(row.document_evidence_refs)
                    and bool((row.citation_summary_text or "").strip())
                )
                row.publish_flag = "yes" if support_ready else "no"
                if not support_ready:
                    row.classification = "diagnostic_internal_only"
                    row.artifact_role = "support_only"
                    row.finding_level = "none"
                    row.publication_state = "blocked"
                else:
                    row.artifact_role = "publishable_finding"
                    row.finding_level = "systemic"
                    row.publication_state = "publishable"
            else:
                row.finding_type = "local"
                row.publish_flag = "yes"
                row.artifact_role = "publishable_finding"
                row.finding_level = "local"
                row.publication_state = "publishable"
            seen_root_keys[key] = row.section_id
        if key in CORE_NOTICE_SYSTEMIC_ISSUES and key in systemic_issue_keys and not row.section_id.startswith("systemic:"):
            row.status = "not applicable"
            row.classification = "supporting_evidence"
            row.finding_type = "supporting_evidence"
            row.publish_flag = "no"
            row.artifact_role = "support_only"
            row.finding_level = "none"
            row.publication_state = "internal_only"
            row.severity = None
            row.confidence = max(row.confidence or 0.7, 0.7)
            row.gap_note = f"Supporting evidence for systemic notice-level issue '{key}'."
            row.remediation_note = None
            pair = (row.section_id, key)
            if pair in seen_supporting_pairs:
                db.delete(row)
                continue
            seen_supporting_pairs.add(pair)
    db.commit()


def _snapshot_analysis_items(db: Session, audit_id: str) -> None:
    db.query(AnalysisCitation).filter(
        AnalysisCitation.analysis_item_id.in_(
            db.query(AuditAnalysisItem.id).filter(AuditAnalysisItem.audit_id == audit_id)
        )
    ).delete(synchronize_session=False)
    db.query(AuditAnalysisItem).filter(AuditAnalysisItem.audit_id == audit_id).delete(synchronize_session=False)

    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    for row in rows:
        publishable = row.publication_state == "publishable" if row.publication_state else row.publish_flag == "yes"
        analysis = AuditAnalysisItem(
            audit_id=audit_id,
            section_id=row.section_id,
            analysis_stage="post_reviewer_snapshot",
            analysis_type=(
                "support_evidence"
                if row.finding_type == "supporting_evidence"
                else "excerpt_scope_fact"
                if row.classification == "referenced_but_unseen"
                else "provisional_local"
                if row.finding_type == "local"
                else "candidate_issue"
            ),
            issue_type=_finding_issue_id(row),
            status_candidate=(
                "not_applicable"
                if row.status == "not applicable"
                else "needs_review"
                if row.status == "needs review"
                else "candidate_partial"
                if row.status == "partial"
                else "candidate_gap"
                if row.status == "gap"
                else "candidate_compliant"
            ),
            classification_candidate=row.classification,
            artifact_role=(
                "support_only"
                if row.artifact_role == "support_only"
                else "publishable_candidate"
                if publishable
                else "suppressed_local"
            ),
            finding_level_candidate=row.finding_level,
            publication_state_candidate=row.publication_state,
            analysis_outcome=(
                "filtered_out"
                if row.classification == "out_of_scope"
                else "contradiction_failed"
                if row.classification == "diagnostic_internal_only"
                else "excerpt_limited"
                if row.classification == "referenced_but_unseen"
                else "candidate_gap"
                if row.status in {"gap", "partial"}
                else "candidate_compliant"
            ),
            candidate_issue=_finding_issue_id(row),
            policy_evidence_excerpt=row.policy_evidence_excerpt,
            legal_requirement_candidate=row.legal_requirement,
            article_candidates=row.primary_legal_anchor,
            retrieval_summary=row.citation_summary_text,
            qualification_summary=row.legal_requirement,
            evidence_sufficiency="weak" if row.status == "needs review" else "sufficient",
            applicability=row.applicability_status,
            citation_fit_status="pass" if row.confidence_article_fit and row.confidence_article_fit >= 0.5 else "uncertain",
            applicability_status=row.applicability_status,
            contradiction_status="failed" if row.classification == "diagnostic_internal_only" else "passed",
            citation_fit="pass" if row.confidence_article_fit and row.confidence_article_fit >= 0.5 else "uncertain",
            support_role=row.finding_type,
            source_scope=row.source_scope,
            excerpt_scope_facts=row.referenced_unseen_sections,
            referenced_unseen_sections=row.referenced_unseen_sections,
            suppression_reason=row.gap_note if not publishable else None,
            publishability_candidate="yes" if publishable else "no",
            confidence=row.confidence,
            confidence_evidence=row.confidence_evidence,
            confidence_applicability=row.confidence_applicability,
            confidence_article_fit=row.confidence_article_fit,
            confidence_overall=row.confidence_overall,
            finding_status=row.status,
            finding_classification=row.classification,
            finding_severity=row.severity,
            gap_note=row.gap_note,
            remediation_note=row.remediation_note,
        )
        db.add(analysis)
        db.flush()
        citations = db.query(FindingCitation).filter(FindingCitation.finding_id == row.id).all()
        for citation in citations:
            db.add(
                AnalysisCitation(
                    analysis_item_id=analysis.id,
                    chunk_id=citation.chunk_id,
                    article_number=citation.article_number,
                    paragraph_ref=citation.paragraph_ref,
                    article_title=citation.article_title,
                    excerpt=citation.excerpt,
                )
            )
    db.commit()


def run_audit(db: Session, audit: Audit) -> Audit:
    ingestion = IngestionClient(settings.ingestion_service_url)
    knowledge = KnowledgeClient(settings.knowledge_service_url)

    audit.status = "running"
    audit.model_provider = settings.model_provider
    audit.model_name = settings.model_name
    audit.model_temperature = settings.model_temperature
    audit.prompt_template_version = settings.prompt_template_version
    audit.embedding_model = settings.embedding_model
    audit.corpus_version = settings.corpus_version
    db.commit()

    sections = ingestion.get_sections(audit.document_id)
    audit_sections_total.inc(len(sections))
    cross_references = _extract_notice_cross_references(sections)
    source_scope, source_scope_confidence, unseen_sections = _source_scope_qualification(sections, cross_references)
    document_mode = _infer_document_mode(sections)
    posture = _document_posture_agent(sections, document_mode)
    obligation_map = _build_document_obligation_map(sections)
    llm_budget_cap = _effective_llm_budget(len(sections), settings.max_llm_calls_per_audit)
    llm_rate_limited = False
    llm_calls_made = 0
    audit_started = time.monotonic()
    timeout_reached = False
    seen_signatures: dict[str, str] = {}

    for section in sorted(sections, key=lambda s: s.section_order):
        if not timeout_reached and _runtime_budget_exceeded(audit_started, time.monotonic(), settings.max_audit_runtime_seconds):
            timeout_reached = True

        if timeout_reached:
            findings_by_status_total.labels(status="needs review").inc()
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="needs review",
                    severity=None,
                    finding_type="local",
                    publish_flag="no",
                    gap_note=f"Audit runtime budget exceeded ({settings.max_audit_runtime_seconds}s). Manual review required.",
                    remediation_note=None,
                )
            )
            db.commit()
            continue

        if _is_not_applicable(section):
            audit_sections_filtered_total.inc()
            findings_by_status_total.labels(status="not applicable").inc()
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="not applicable",
                    severity=None,
                    classification="out_of_scope",
                    confidence=1.0,
                    confidence_evidence=0.95,
                    confidence_applicability=0.95,
                    confidence_article_fit=0.95,
                    confidence_synthesis=0.7,
                    confidence_overall=1.0,
                    finding_type="supporting_evidence",
                    publish_flag="no",
                    missing_from_section="no",
                    missing_from_document="no",
                    not_visible_in_excerpt="no",
                    gap_note=None,
                    remediation_note=None,
                )
            )
            db.commit()
            continue
        auditability = _section_auditability_type(section)
        if auditability in {"definition_section", "administrative_section", "meta_section"}:
            audit_sections_filtered_total.inc()
            findings_by_status_total.labels(status="not applicable").inc()
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="not applicable",
                    severity=None,
                    classification="out_of_scope",
                    confidence=0.95,
                    confidence_evidence=0.9,
                    confidence_applicability=0.9,
                    confidence_article_fit=0.9,
                    confidence_synthesis=0.7,
                    confidence_overall=0.95,
                    finding_type="supporting_evidence",
                    publish_flag="no",
                    missing_from_section="no",
                    missing_from_document="no",
                    not_visible_in_excerpt="no",
                    gap_note=f"Section filtered by auditability gate ({auditability}).",
                    remediation_note=None,
                )
            )
            db.commit()
            continue

        audit_sections_auditable_total.inc()
        collection_mode = _collection_mode(section)
        issue_spotting_calls_total.inc()
        candidate_issues = _spot_candidate_issues(section, collection_mode)
        primary_issue = candidate_issues[0] if candidate_issues else CandidateIssue(
            candidate_issue_type="missing_controller_identity",
            evidence_text=section.content[:180],
            evidence_strength=0.35,
            local_or_document_level="local",
            possible_collection_mode=collection_mode,
            is_visible_gap=False,
        )
        qualification = _legal_qualification_for_issue(primary_issue)
        legal_qualification_calls_total.inc()
        topic = f"{_infer_topic(section)} qualified_issue:{qualification['issue_name']} primary_article:{qualification['primary_article']}"
        query = _build_retrieval_query(section, topic, document_mode)
        chunks = _rerank_chunks_for_mode(section, knowledge.search(query=query, k=8), document_mode)[:5]

        if _retry_needed(chunks, topic):
            retrieval_retry_total.inc()
            query_retry = _build_retrieval_query(
                section,
                f"{qualification['issue_name']} {qualification['primary_article']} {', '.join(qualification['secondary_articles'])}",
                document_mode,
            )
            chunks_retry = _rerank_chunks_for_mode(section, knowledge.search(query=query_retry, k=8), document_mode)[:5]
            if chunks_retry:
                chunks = chunks_retry

        if not _evidence_sufficient(chunks):
            evidence_gate_failure_total.inc()
            fallback_issue = next((c for c in candidate_issues if c["candidate_issue_type"].startswith("missing_")), None)
            if document_mode == "privacy_notice" and fallback_issue is not None:
                issue_name = fallback_issue["candidate_issue_type"]
                issue_to_obligation = {
                    "missing_controller_identity": "controller_contact",
                    "missing_legal_basis": "legal_basis",
                    "missing_retention": "retention",
                    "missing_rights_information": "rights",
                    "missing_complaint_right": "complaint",
                    "missing_transfer_notice": "transfer",
                }
                obligation = issue_to_obligation.get(issue_name)
                if obligation in CORE_NOTICE_CLAIMS:
                    findings_by_status_total.labels(status="partial").inc()
                    db.add(
                        Finding(
                            audit_id=audit.id,
                            section_id=section.id,
                            status="partial",
                            severity="medium",
                            classification="probable_gap",
                            confidence=0.6,
                            finding_type="local",
                            publish_flag="yes",
                            obligation_under_review=obligation,
                            collection_mode=collection_mode,
                            applicability_status="probable",
                            visibility_status="inferred_from_silence",
                            section_vs_document_scope="missing_from_document",
                            missing_fact_if_unresolved="citation retrieval insufficient; probable silence-based notice omission",
                            confidence_level="medium",
                            assessment_type="probable",
                            severity_rationale="Probable core-notice omission inferred from silence despite weak citation retrieval.",
                            gap_note=(
                                "Probable gap: required privacy-notice element is not visible in the provided excerpt. "
                                "Classification kept substantive (not downgraded to not_assessable) for core notice duty."
                            ),
                            remediation_note=_issue_specific_remediation(issue_name, posture["document_type"], systemic=False),
                        )
                    )
                    db.commit()
                    continue
            findings_by_status_total.labels(status="needs review").inc()
            db.add(
                Finding(
                    audit_id=audit.id,
                    section_id=section.id,
                    status="needs review",
                    severity=None,
                    finding_type="local",
                    publish_flag="no",
                    gap_note="Evidence sufficiency gate failed.",
                    remediation_note=None,
                )
            )
            db.commit()
            continue

        if llm_rate_limited or llm_calls_made >= llm_budget_cap:
            gate_reason = (
                "LLM rate limit reached earlier in this audit. Manual review required."
                if llm_rate_limited
                else f"LLM call budget reached ({llm_budget_cap}). Manual review required."
            )
            llm_finding = LlmFinding(
                status="needs review",
                severity=None,
                gap_note=gate_reason,
                remediation_note=None,
                citations=[],
            )
        else:
            with llm_inference_latency_seconds.time():
                llm_calls_made += 1
                llm_finding, raw = run_llm_classification(
                    section_title=section.section_title,
                    section_content=section.content,
                    chunks=chunks,
                    guidance=_section_guidance(section, document_mode),
                    model_provider=settings.model_provider,
                    model_name=settings.model_name,
                    temperature=settings.model_temperature,
                    groq_api_key=settings.groq_api_key,
                    gemini_api_key=settings.gemini_api_key,
                    fallback_provider=settings.fallback_model_provider,
                    fallback_model=settings.fallback_model_name,
                )
            if raw == "__rate_limited__":
                llm_rate_limited = True

        f = _coerce_finding(llm_finding)
        f.gap_note = _sanitize_legal_reference_text(f.gap_note)
        f.remediation_note = _sanitize_legal_reference_text(f.remediation_note)
        if f.candidate_publishability == "internal_only":
            f = LlmFinding(
                status="needs review",
                severity=None,
                gap_note="Model marked this candidate as internal_only due to weak legal confidence.",
                remediation_note=None,
                citations=[],
                candidate_publishability="internal_only",
            )
        if document_mode == "privacy_notice" and _finding_mentions_internal_control_only(f"{f.gap_note or ''} {f.remediation_note or ''}"):
            f = LlmFinding(
                status="needs review",
                severity=None,
                gap_note=(
                    "The identified issue appears to concern internal controller operations (e.g., breach workflow) "
                    "rather than mandatory external privacy-notice disclosures. Manual legal review required."
                ),
                remediation_note=None,
                citations=[],
            )
        claim_text = f"{f.gap_note or ''} {f.remediation_note or ''}"
        claim_types = _claim_types_from_text(claim_text) or _fallback_claim_types_from_section(section)
        memo = _applicability_memo(section, claim_types, posture)
        applicability_calls_total.inc()
        applicability = _applicability_decision(section, memo, claim_types)
        if any(t in claim_types for t in {"profiling_disclosure_gap", "article_22_threshold_unclear"}):
            profiling_pass_total.inc()
        if any(t in claim_types for t in {"transfer_notice", "transfer_safeguards"}):
            transfer_pass_total.inc()
        specialized_review = _specialized_legal_review(section, claim_types)
        f.remediation_note = _clean_remediation_legal_mismatches(f.remediation_note, claim_types)
        valid_citations = _validate_citations(f.citations, chunks, section, document_mode, claim_text=claim_text)
        valid_citations = _apply_applicability_gate_to_citations(valid_citations, applicability, claim_types)
        if _violates_forbidden_article_matrix(claim_types, valid_citations):
            valid_citations = []
        if f.status in {"gap", "partial"} and not valid_citations and document_mode == "privacy_notice":
            salvaged = _salvage_citations_from_retrieved(chunks, section, document_mode, claim_text=claim_text)
            if salvaged:
                valid_citations = salvaged
            fallback = _build_mandatory_notice_gap(section, chunks)
            if fallback is None and not valid_citations:
                one_rescue_query = _claim_template_query(section, claim_types)
                rescue_chunks = _rerank_chunks_for_mode(section, knowledge.search(query=one_rescue_query, k=8), document_mode)
                merged: list[RetrievalChunk] = []
                seen_chunk_ids: set[str] = set()
                for ch in [*chunks, *rescue_chunks]:
                    if ch.chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(ch.chunk_id)
                    merged.append(ch)
                chunks = merged[:8]
                salvaged = _salvage_citations_from_retrieved(chunks, section, document_mode, claim_text=claim_text)
                if salvaged:
                    valid_citations = salvaged
                valid_citations = _apply_applicability_gate_to_citations(valid_citations, applicability, claim_types)
                if _violates_forbidden_article_matrix(claim_types, valid_citations):
                    valid_citations = []
                fallback = _build_transfer_gap(section, chunks) if "transfer" in claim_types else _build_mandatory_notice_gap(section, chunks)
            if fallback is not None:
                f = fallback
                claim_text = f"{f.gap_note or ''} {f.remediation_note or ''}"
                valid_citations = _validate_citations(f.citations, chunks, section, document_mode, claim_text=claim_text)
                valid_citations = _apply_applicability_gate_to_citations(valid_citations, applicability, claim_types)
                if _violates_forbidden_article_matrix(claim_types, valid_citations):
                    valid_citations = []
        if f.status == "needs review" and document_mode == "privacy_notice":
            review_text = _norm(f"{f.gap_note or ''} {section.section_title} {section.content[:500]}")
            if "retention" in review_text or "storage period" in review_text:
                retention_query = (
                    f"GDPR retention transparency disclosures Articles 13(2)(a), 14(2)(a), and Article 5(1)(e). "
                    f"Section context: {section.section_title}. {section.content[:600]}"
                )
                retention_chunks = _rerank_chunks_for_mode(section, knowledge.search(query=retention_query, k=8), document_mode)
                merged: list[RetrievalChunk] = []
                seen_chunk_ids: set[str] = set()
                for ch in [*chunks, *retention_chunks]:
                    if ch.chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(ch.chunk_id)
                    merged.append(ch)
                chunks = merged[:8]
                retention_gap = _build_retention_gap(section, chunks)
                if retention_gap is not None:
                    f = retention_gap
                    claim_text = f"{f.gap_note or ''} {f.remediation_note or ''}"
                    claim_types = _claim_types_from_text(claim_text) or _fallback_claim_types_from_section(section)
                    valid_citations = _validate_citations(f.citations, chunks, section, document_mode, claim_text=claim_text)
                    valid_citations = _apply_applicability_gate_to_citations(valid_citations, applicability, claim_types)
                    if _violates_forbidden_article_matrix(claim_types, valid_citations):
                        valid_citations = []
        if f.status in {"gap", "partial"} and not valid_citations:
            diagnostic = _citation_diagnostic_reason(section, claim_types, _collection_mode(section))
            f = LlmFinding(
                status="needs review",
                severity=None,
                gap_note=(
                    "Substantive finding withheld due to insufficient legally compatible citation support. "
                    f"Diagnostic: {diagnostic}"
                ),
                remediation_note=(
                    "Provide stronger section-level evidence and aligned GDPR anchors, then rerun classification."
                ),
                citations=[],
            )
        f, valid_citations = _reviewer_agent(f, valid_citations, claim_types, memo)
        if applicability["applicability_status"] == "unresolved" and claim_types & {
            "controller_contact",
            "legal_basis",
            "retention",
            "rights",
            "complaint",
        }:
            if f.status in {"gap", "partial"} and any(i["candidate_issue_type"].startswith("missing_") for i in candidate_issues):
                f.status = "partial"
                f.severity = "medium"
                f.gap_note = (
                    "Probable gap: core notice element appears missing, but direct vs indirect source mode is not fully resolved "
                    f"({applicability['unresolved_trigger']})."
                )
            else:
                f = LlmFinding(
                    status="needs review",
                    severity=None,
                    gap_note=f"Not assessable: {applicability['unresolved_trigger']}.",
                    remediation_note="Provide source-collection wording to resolve Article 13 vs 14 applicability.",
                    citations=[],
                )
                valid_citations = []

        if f.status in {"gap", "partial"}:
            global_missing_conflict = False
            if "legal_basis" in claim_types and obligation_map["legal_basis_present"]:
                global_missing_conflict = True
            if "rights" in claim_types and obligation_map["rights_present"]:
                global_missing_conflict = True
            if "retention" in claim_types and obligation_map["retention_present"]:
                global_missing_conflict = True
            if global_missing_conflict:
                f = LlmFinding(
                    status="partial",
                    severity="low",
                    gap_note=(
                        "Section-local omission detected, but document-wide disclosure appears elsewhere. "
                        "Treat as local clarity gap rather than full notice non-compliance."
                    ),
                    remediation_note="Improve local cross-reference to the global disclosure section.",
                    citations=valid_citations,
                )

        f = _enforce_substantive_citation_gate(f, valid_citations)
        f.severity = _normalize_severity(f.status, f.severity, claim_types)
        if f.status in {"gap", "partial"}:
            f.remediation_note = _issue_specific_remediation(
                qualification["issue_name"],
                posture["document_type"],
                systemic=False,
            )
        f = _ensure_reasoning_chain(f, section, valid_citations, claim_types)
        if f.status in {"gap", "partial"} and f.gap_note:
            f.gap_note = (
                f"{f.gap_note} Applicability memo: obligation={memo['obligation']}; "
                f"collection_mode={memo['collection_mode']}; visibility={memo['visibility']}; "
                f"confidence={memo['applicability_confidence']:.2f}; applicability_status={applicability['applicability_status']}."
            )
            f.gap_note = (
                f"{f.gap_note} Legal qualification: issue={qualification['issue_name']}; "
                f"primary={qualification['primary_article']}; secondary={', '.join(qualification['secondary_articles'])}; "
                f"rejected={', '.join(qualification['rejected_articles'])}. "
                f"Primary fit: {qualification['reason_primary_article_fits']} "
                f"Rejected rationale: {qualification['reason_rejected_articles_do_not_fit']}"
            )
            specialized_bits = [v for v in specialized_review.values() if v]
            if specialized_bits:
                f.gap_note = f"{f.gap_note} Specialized legal review: {' '.join(specialized_bits)}"
        if not _consistency_validator(qualification["issue_name"], claim_types, valid_citations, f.remediation_note):
            f = LlmFinding(
                status="needs review",
                severity=None,
                gap_note="Internal consistency check failed between issue, article mapping, citation fit, and remediation.",
                remediation_note=None,
                citations=[],
            )
            valid_citations = []
        classification, confidence = _classify_finding_quality(f, valid_citations, claim_types, _collection_mode(section))
        consistency_ok, consistency_reason = _pre_persist_consistency_gate(
            qualification["issue_name"],
            claim_types,
            memo["obligation"],
            valid_citations,
            f.remediation_note,
            classification,
        )
        if not consistency_ok:
            contradiction_fail_total.inc()
            classification = "contradiction_internal_only"
            f.status = "needs review"
            f.severity = None
            f.gap_note = (
                "Internal QA consistency gate rejected this draft finding. "
                f"Reason: {consistency_reason or 'mismatch'}."
            )
            f.remediation_note = None
            valid_citations = []
            confidence = min(confidence or 0.35, 0.35)

        if f.status in {"gap", "partial"}:
            signature = _finding_signature(f, valid_citations)
            first_section = seen_signatures.get(signature)
            if first_section:
                f = LlmFinding(
                    status="needs review",
                    severity=None,
                    gap_note=(
                        f"Potential duplicate of section {first_section}; consolidated to reduce repeated findings. "
                        "Review section-level nuances manually if needed."
                    ),
                    remediation_note=None,
                    citations=[],
                )
                valid_citations = []
                classification = "not_assessable"
                confidence = 0.4
            else:
                seen_signatures[signature] = section.id

        finding_row = Finding(
            audit_id=audit.id,
            section_id=section.id,
            status=f.status,
            severity=f.severity,
            classification=classification,
            confidence=confidence,
            confidence_evidence=round(min(0.95, 0.25 + 0.15 * len(valid_citations)), 2),
            confidence_applicability=round(memo["applicability_confidence"], 2),
            confidence_article_fit=round(0.88 if valid_citations and not _violates_forbidden_article_matrix(claim_types, valid_citations) else 0.45, 2),
            confidence_synthesis=0.8 if classification == "systemic_violation" else 0.65,
            confidence_overall=confidence,
            finding_type="local",
            publish_flag="yes" if _is_publishable_finding(section.id, f.status, classification, "local") else "no",
            missing_from_section="yes" if f.status in {"gap", "partial"} else "no",
            missing_from_document="yes" if (f.status in {"gap", "partial"} and not any(obligation_map.values())) else "no",
            not_visible_in_excerpt="yes" if classification == "not_assessable" else "no",
            obligation_under_review=memo["obligation"],
            collection_mode=memo["collection_mode"],
            applicability_status=applicability["applicability_status"],
            visibility_status=memo["visibility"],
            section_vs_document_scope=(
                "missing_from_document"
                if f.status in {"gap", "partial"} and not any(obligation_map.values())
                else "missing_from_section_only"
            ),
            missing_fact_if_unresolved=applicability["unresolved_trigger"],
            policy_evidence_excerpt=(primary_issue["evidence_text"] or section.content[:220]).strip(),
            legal_requirement=(
                f"Primary legal anchor: GDPR Article {qualification['primary_article']} for issue "
                f"{qualification['issue_name']}."
            ),
            gap_reasoning=f.gap_note,
            confidence_level=_confidence_level_for(confidence),
            assessment_type=_assessment_type_for(f, classification),
            severity_rationale=_severity_rationale(f, claim_types),
            gap_note=f.gap_note,
            remediation_note=f.remediation_note,
        )
        db.add(finding_row)
        if finding_row.publish_flag == "yes":
            publishable_findings_total.inc()
            local_findings_published_total.inc()
            if finding_row.classification == "not_assessable":
                not_assessable_findings_published_total.inc()
        findings_by_status_total.labels(status=f.status).inc()
        db.flush()

        for cit in valid_citations:
            db.add(
                FindingCitation(
                    finding_id=finding_row.id,
                    chunk_id=cit.chunk_id,
                    article_number=cit.article_number,
                    paragraph_ref=cit.paragraph_ref,
                    article_title=cit.article_title,
                    excerpt=cit.excerpt,
                )
            )

        db.commit()

        if (
            f.status in {"gap", "partial"}
            and {"controller_contact", "legal_basis"}.issubset(claim_types)
            and qualification["issue_name"] == "missing_controller_identity"
        ):
            split_gap = (
                "Evidence indicates purposes/processing are described, but lawful basis per purpose is not disclosed. "
                "This is evaluated separately from controller identity/contact."
            )
            split_row = Finding(
                audit_id=audit.id,
                section_id=section.id,
                status="partial",
                severity="high",
                classification="probable_gap",
                confidence=0.62,
                confidence_evidence=round(min(0.9, 0.22 + 0.12 * len(valid_citations)), 2),
                confidence_applicability=round(memo["applicability_confidence"], 2),
                confidence_article_fit=0.7 if valid_citations else 0.52,
                confidence_synthesis=0.7,
                confidence_overall=0.62,
                finding_type="local",
                publish_flag="yes",
                missing_from_section="yes",
                missing_from_document="no",
                not_visible_in_excerpt="no",
                obligation_under_review="legal_basis",
                collection_mode=memo["collection_mode"],
                applicability_status=applicability["applicability_status"],
                visibility_status=memo["visibility"],
                section_vs_document_scope="missing_from_section_only",
                missing_fact_if_unresolved=applicability["unresolved_trigger"],
                policy_evidence_excerpt=(primary_issue["evidence_text"] or section.content[:220]).strip(),
                legal_requirement="Primary legal anchor: GDPR Article 13(1)(c) / 14(1)(c) for legal basis disclosure.",
                gap_reasoning=split_gap,
                confidence_level="medium",
                assessment_type="probable",
                severity_rationale="High severity due to missing legal basis transparency for core notice obligations.",
                gap_note=split_gap,
                remediation_note=_issue_specific_remediation("missing_legal_basis", posture["document_type"], systemic=False),
            )
            db.add(split_row)
            findings_by_status_total.labels(status="partial").inc()
            publishable_findings_total.inc()
            db.flush()
            for cit in valid_citations:
                if _article_int(cit.article_number) in {6, 13, 14}:
                    db.add(
                        FindingCitation(
                            finding_id=split_row.id,
                            chunk_id=cit.chunk_id,
                            article_number=cit.article_number,
                            paragraph_ref=cit.paragraph_ref,
                            article_title=cit.article_title,
                            excerpt=cit.excerpt,
                        )
                    )
            db.commit()

    if document_mode == "privacy_notice":
        _add_notice_level_synthesis(db, audit.id, obligation_map)
    _add_systemic_issue_synthesis(db, audit.id)
    _build_systemic_support(
        db,
        audit.id,
        sections,
        obligation_map,
        source_scope,
        source_scope_confidence,
        unseen_sections,
        cross_references,
    )
    _enforce_core_and_specialist_completeness(db, audit.id, sections, obligation_map)
    _partner_review_pass(db, audit.id)
    _snapshot_analysis_items(db, audit.id)

    audit.status = "complete"
    audit.completed_at = datetime.utcnow()
    db.add(audit)
    db.commit()
    db.refresh(audit)
    audit_duration_seconds.observe(time.monotonic() - audit_started)
    return audit
