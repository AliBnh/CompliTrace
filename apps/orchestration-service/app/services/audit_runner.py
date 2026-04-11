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
from app.models.audit import AnalysisCitation, Audit, AuditAnalysisItem, EvidenceRecord, Finding, FindingCitation
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
    "missing_controller_contact": {
        "primary": ["GDPR Art. 13(1)(a)", "GDPR Art. 14(1)(a)"],
        "secondary": ["GDPR Art. 12(1)"],
    },
    "missing_transfer_notice": {
        "primary": ["GDPR Art. 13(1)(f)", "GDPR Art. 14(1)(f)"],
        "secondary": ["GDPR Art. 44", "GDPR Art. 45", "GDPR Art. 46"],
    },
    "profiling_disclosure_gap": {
        "primary": ["GDPR Art. 13(2)(f)", "GDPR Art. 14(2)(g)"],
        "secondary": ["GDPR Art. 22"],
    },
    "recipients_disclosure_gap": {
        "primary": ["GDPR Art. 13(1)(e)", "GDPR Art. 14(1)(e)"],
        "secondary": ["GDPR Art. 12(1)"],
    },
    "purpose_specificity_gap": {
        "primary": ["GDPR Art. 13(1)(c)", "GDPR Art. 14(1)(c)"],
        "secondary": ["GDPR Art. 5(1)(b)"],
    },
    "controller_processor_role_ambiguity": {
        "primary": ["GDPR Art. 13(1)(a)", "GDPR Art. 14(1)(a)"],
        "secondary": ["GDPR Art. 5(1)(a)"],
    },
}

SYSTEMIC_REQUIRED_OBLIGATION_KEYS: dict[str, str] = {
    "missing_controller_identity": "controller_identity_present",
    "missing_controller_contact": "controller_contact_present",
    "missing_legal_basis": "legal_basis_present",
    "missing_retention_period": "retention_present",
    "missing_rights_notice": "rights_present",
    "missing_complaint_right": "complaint_present",
}

SYSTEMIC_SECTION_SIGNALS: dict[str, set[str]] = {
    "missing_controller_identity": {"controller", "company", "contact", "privacy notice", "personal data"},
    "missing_controller_contact": {"contact", "email", "privacy@", "webform", "address", "data subject"},
    "missing_legal_basis": {"purpose", "process", "collect", "use", "personal data"},
    "missing_retention_period": {"retain", "retention", "storage", "personal data", "process"},
    "missing_rights_notice": {"right", "data subject", "access", "rectification", "erasure", "process"},
    "missing_complaint_right": {"complaint", "supervisory authority", "rights", "personal data", "privacy"},
    "missing_transfer_notice": {"transfer", "third country", "international", "recipient"},
    "profiling_disclosure_gap": {"profil", "automated", "decision", "score", "segmentation"},
}

CORE_DUTY_TO_ISSUE: dict[str, str] = {
    "controller_identity": "missing_controller_identity",
    "controller_contact": "missing_controller_contact",
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
    "article_14_indirect_collection_gap": (
        {"from third parties", "obtained from third parties", "received from third parties", "from external sources"},
        "triggered_article_14_indirect_collection",
    ),
    "controller_processor_role_ambiguity": ({"controller", "processor", "on behalf of"}, "triggered_role_ambiguity_family"),
    "recipients_disclosure_gap": (
        {"third party", "third-party", "vendor", "partner", "reseller", "marketplace", "payment provider", "cloud provider"},
        "triggered_recipients_family",
    ),
    "purpose_specificity_gap": (
        {"purpose", "use of data", "we use", "we process", "category of personal data"},
        "triggered_purpose_mapping_family",
    ),
    "special_category_basis_unclear": (
        {"special category", "article 9", "health data", "biometric", "genetic", "sensitive information"},
        "triggered_special_category_family",
    ),
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
    "missing_controller_contact": {"primary": {13, 14}, "support": {12}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_legal_basis": {"primary": {13, 14, 6}, "support": {5}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_retention_period": {"primary": {13, 14, 5}, "support": {12}, "disallowed": {21, 22, 44, 45, 46, 47, 49}},
    "missing_rights_notice": {"primary": {13, 14, 12, 15, 16, 17, 18, 19, 20, 21, 22}, "support": {5}, "disallowed": set()},
    "missing_complaint_right": {"primary": {13, 14, 77}, "support": {12}, "disallowed": {21, 22}},
    "missing_transfer_notice": {"primary": {13, 14, 44, 45, 46}, "support": {47, 49}, "disallowed": {15, 21}},
    "profiling_disclosure_gap": {"primary": {13, 14}, "support": {22}, "disallowed": {15}},
    "recipients_disclosure_gap": {"primary": {13, 14}, "support": {12}, "disallowed": {21, 22}},
    "purpose_specificity_gap": {"primary": {13, 14, 5}, "support": {12, 6}, "disallowed": {21, 22}},
    "special_category_basis_unclear": {"primary": {9, 13, 14}, "support": {6}, "disallowed": {21}},
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
    legal_posture: str
    legal_posture_reason: str


class LegalQualification(TypedDict):
    issue_name: str
    obligation_family: str
    defect_type: str
    priority_bucket: str
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


class LegalFact(TypedDict):
    fact_type: str
    value: str
    evidence: str


class GdprDutySpec(TypedDict):
    duty_id: str
    document_types: list[str]
    primary_articles: list[str]
    secondary_articles: list[str]
    trigger_conditions: list[str]
    satisfaction_requirements: list[str]
    clear_failure_patterns: list[str]
    allowed_outcomes: list[str]


GDPR_DUTY_REGISTRY: dict[str, GdprDutySpec] = {
    "controller_identity_contact": {
        "duty_id": "controller_identity_contact",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(1)(a)", "Art. 14(1)(a)"],
        "secondary_articles": ["Art. 12(1)"],
        "trigger_conditions": ["document presents personal data processing to data subjects"],
        "satisfaction_requirements": ["controller identity", "contact route (email/webform/address)"],
        "clear_failure_patterns": ["controller not named", "no contact route", "contact missing"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "purposes_notice": {
        "duty_id": "purposes_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(1)(c)", "Art. 14(1)(c)"],
        "secondary_articles": ["Art. 5(1)(b)"],
        "trigger_conditions": ["document presents processing purposes"],
        "satisfaction_requirements": ["specific purpose statements"],
        "clear_failure_patterns": ["generic business purposes only", "purpose categories not specific"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "legal_basis_notice": {
        "duty_id": "legal_basis_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(1)(c)", "Art. 14(1)(c)"],
        "secondary_articles": ["Art. 6", "Art. 7"],
        "trigger_conditions": ["document presents personal data processing to data subjects"],
        "satisfaction_requirements": ["lawful basis disclosed", "mapped to purpose where needed"],
        "clear_failure_patterns": ["consent inferred from use", "legal basis not mapped", "implied consent only"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "recipients_notice": {
        "duty_id": "recipients_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(1)(e)", "Art. 14(1)(e)"],
        "secondary_articles": ["Art. 12(1)"],
        "trigger_conditions": ["document mentions sharing/disclosure"],
        "satisfaction_requirements": ["recipient categories or specific recipients"],
        "clear_failure_patterns": ["partners/vendors mentioned without categories"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "transfers_notice": {
        "duty_id": "transfers_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(1)(f)", "Art. 14(1)(f)"],
        "secondary_articles": ["Art. 44", "Art. 45", "Art. 46"],
        "trigger_conditions": ["international transfer signal present"],
        "satisfaction_requirements": ["transfer disclosed", "safeguard/mechanism disclosed"],
        "clear_failure_patterns": ["safeguards where practical", "no specific mechanism disclosed"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "retention_notice": {
        "duty_id": "retention_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(2)(a)", "Art. 14(2)(a)"],
        "secondary_articles": ["Art. 5(1)(e)"],
        "trigger_conditions": ["document presents personal data processing to data subjects"],
        "satisfaction_requirements": ["specific retention period or objective criteria"],
        "clear_failure_patterns": ["retained indefinitely", "retained for business needs", "extended periods"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "rights_notice": {
        "duty_id": "rights_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(2)(b)", "Art. 14(2)(c)"],
        "secondary_articles": ["Art. 12", "Art. 15-22"],
        "trigger_conditions": ["document presents personal data processing to data subjects"],
        "satisfaction_requirements": ["rights listed and actionable"],
        "clear_failure_patterns": ["rights not disclosed"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "complaint_right_notice": {
        "duty_id": "complaint_right_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(2)(d)", "Art. 14(2)(e)"],
        "secondary_articles": ["Art. 77"],
        "trigger_conditions": ["document presents data-subject rights"],
        "satisfaction_requirements": ["supervisory authority complaint right disclosed"],
        "clear_failure_patterns": ["complaint right missing"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
    "profiling_notice": {
        "duty_id": "profiling_notice",
        "document_types": ["privacy_notice", "privacy_policy", "external_privacy_notice", "mixed_document"],
        "primary_articles": ["Art. 13(2)(f)", "Art. 14(2)(g)"],
        "secondary_articles": ["Art. 22"],
        "trigger_conditions": ["profiling or automated decision signal present"],
        "satisfaction_requirements": ["logic involved", "significance", "effects/safeguards where relevant"],
        "clear_failure_patterns": ["automated profiling without logic", "automated decision without explanation"],
        "allowed_outcomes": ["compliant", "partially_compliant", "non_compliant", "not_assessable_from_provided_text"],
    },
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _explicit_violation_library() -> dict[str, dict[str, object]]:
    return {
        "invalid_consent": {
            "patterns": {"consent inferred from use", "consent inferred from continued", "consent via browsing", "implied consent"},
            "articles": ["Art. 6", "Art. 7", "Art. 4(11)"],
            "issue": "missing_legal_basis",
        },
        "unlawful_retention_wording": {
            "patterns": {"retained indefinitely", "retained long-term for business needs", "archived indefinitely", "operational constraints"},
            "articles": ["Art. 13(2)(a)", "Art. 14(2)(a)", "Art. 5(1)(e)"],
            "issue": "missing_retention",
        },
        "weak_transfer_safeguards": {
            "patterns": {"safeguards where practical", "protection may vary", "operational needs", "no specific mechanism disclosed"},
            "articles": ["Art. 13(1)(f)", "Art. 14(1)(f)", "Art. 44", "Art. 45", "Art. 46"],
            "issue": "missing_transfer_notice",
        },
        "profiling_without_required_explanation": {
            "patterns": {"automated profiling", "risk scores", "service availability influenced", "without logic explanation"},
            "articles": ["Art. 13(2)(f)", "Art. 14(2)(g)", "Art. 22"],
            "issue": "profiling_disclosure_gap",
        },
    }


def _explicit_violation_hits(text: str) -> list[tuple[str, dict[str, object]]]:
    norm = _norm(text)
    hits: list[tuple[str, dict[str, object]]] = []
    for key, cfg in _explicit_violation_library().items():
        patterns = cfg.get("patterns", set())
        if any(p in norm for p in patterns if isinstance(p, str)):
            hits.append((key, cfg))
    return hits


def _duty_registry_key_for_issue(issue_name: str) -> str | None:
    mapping = {
        "missing_controller_identity": "controller_identity_contact",
        "missing_controller_contact": "controller_identity_contact",
        "missing_legal_basis": "legal_basis_notice",
        "missing_retention": "retention_notice",
        "missing_rights_information": "rights_notice",
        "missing_complaint_right": "complaint_right_notice",
        "missing_transfer_notice": "transfers_notice",
        "profiling_disclosure_gap": "profiling_notice",
        "recipients_disclosure_gap": "recipients_notice",
        "purpose_specificity_gap": "purposes_notice",
    }
    return mapping.get(issue_name)


def _issue_relevance_score(issue_name: str, section: SectionData) -> int:
    text = _norm(f"{section.section_title} {section.content}")
    signals: dict[str, set[str]] = {
        "missing_controller_contact": {"controller", "contact", "email", "address", "privacy@"},
        "purpose_specificity_gap": {"purpose", "why we process", "processing purpose"},
        "missing_legal_basis": {"legal basis", "lawful basis", "consent", "legitimate interests", "contract"},
        "recipients_disclosure_gap": {"recipient", "third party", "vendor", "partner", "share"},
        "missing_transfer_notice": {"transfer", "third country", "outside eea", "safeguard", "scc", "adequacy"},
        "missing_retention": {"retention", "retain", "storage period", "kept for"},
        "missing_rights_information": {"right to access", "rectification", "erasure", "objection", "portability"},
        "missing_complaint_right": {"complaint", "supervisory authority"},
        "article_14_indirect_collection_gap": {"source", "third-party source", "obtained from"},
        "profiling_disclosure_gap": {"profiling", "automated decision", "logic involved", "significance", "effects"},
    }
    tokens = signals.get(issue_name, set())
    return sum(1 for token in tokens if token in text)


def _validate_duty_outcome(duty: GdprDutySpec, sections: list[SectionData]) -> str:
    corpus = _norm(" ".join(f"{s.section_title} {s.content}" for s in sections))
    if len(corpus) < 80:
        return "not_assessable_from_provided_text"
    failure_patterns = {p for p in duty["clear_failure_patterns"]}
    if any(p in corpus for p in failure_patterns):
        return "non_compliant"
    requirements = {r for r in duty["satisfaction_requirements"]}
    req_hits = sum(1 for r in requirements if any(token in corpus for token in _norm(r).split()[:2]))
    if req_hits == 0:
        return "non_compliant"
    if req_hits < len(requirements):
        return "partially_compliant"
    return "compliant"


def _document_wide_duty_validation(sections: list[SectionData], document_type: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for duty_id, duty in GDPR_DUTY_REGISTRY.items():
        if not any(t in document_type for t in duty["document_types"]):
            continue
        out[duty_id] = _validate_duty_outcome(duty, sections)
    return out


def _not_assessable_allowed(text: str, status: str, classification: str | None) -> bool:
    norm = _norm(text)
    explicit_unlawful = bool(_explicit_violation_hits(text))
    clearly_partial = status == "partial" or any(t in norm for t in {"partially", "incomplete", "not mapped"})
    clearly_missing = status == "gap" or any(t in norm for t in {"missing", "not disclosed", "absent"})
    if explicit_unlawful or clearly_partial or clearly_missing:
        return False
    if classification in {"diagnostic_internal_only", "retrieval_failure_internal_only"}:
        return True
    return len(norm) < 120 or "excerpt" in norm


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
    risk_tier = _risk_tier_for_claims(finding, claim_types)
    high_policy_claims = {"controller_identity", "controller_contact", "controller_identity_contact", "legal_basis", "rights", "complaint"}
    medium_policy_claims = {"retention", "recipients", "purpose_mapping", "role_ambiguity"}
    conditional_high_claims = {"transfer", "profiling"}

    if risk_tier == "critical":
        return "Risk tier: critical. Explicit text indicates potentially unlawful processing model requiring immediate remediation."
    if risk_tier == "major" and (claim_types & {"transfer", "profiling", "retention", "legal_basis"}):
        return "Risk tier: major. Material legal risk with potential rights impact; prompt remediation is required."
    if claim_types & high_policy_claims:
        return "Risk tier: major. High severity under policy for core identity/legal-basis/rights/complaint transparency duties."
    if claim_types & medium_policy_claims:
        return "Medium severity under policy for bounded transparency gaps (retention/recipients/purpose/role clarity)."
    if claim_types & conditional_high_claims:
        text = _norm(finding.gap_note or "")
        explicit_activity = any(t in text for t in {"transfer", "third country", "profiling", "automated decision", "logic involved"})
        if explicit_activity:
            return "High severity under policy because activity is explicit and required disclosure is absent."
        return "Medium severity under policy pending explicit transfer/profiling activity confirmation."

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
    return "Risk tier: minor. Severity calibrated from obligation criticality, scope, and evidence confidence."


def _risk_tier_for_claims(finding: LlmFinding, claim_types: set[str]) -> str:
    text = _norm(f"{finding.gap_note or ''} {finding.remediation_note or ''}")
    critical_markers = {"inferred consent", "continued use", "indefinite", "indefinitely", "without human intervention", "similarly significant"}
    major_markers = {"third country", "outside the eea", "transfer safeguards", "lawful basis", "legal basis", "profiling", "risk scoring"}
    if any(marker in text for marker in critical_markers):
        return "critical"
    if any(marker in text for marker in major_markers) or claim_types & {"transfer", "profiling", "retention", "legal_basis"}:
        return "major"
    return "minor"


def _defect_type_for_issue(issue: CandidateIssue) -> str:
    issue_name = issue["candidate_issue_type"]
    text = _norm(issue.get("evidence_text") or "")
    if issue_name in {"missing_controller_identity", "missing_rights_information", "missing_complaint_right"}:
        return "missing_disclosure"

    invalidity_signals_by_issue: dict[str, set[str]] = {
        "missing_legal_basis": {"inferred consent", "continued use", "implied consent", "consent inferred", "legitimate interests for all"},
        "missing_retention": {"extended period", "as long as necessary"},
        "missing_transfer_notice": {"where practical", "as appropriate", "when needed", "case by case"},
        "profiling_disclosure_gap": {"automated decision", "without human intervention"},
        "recipients_disclosure_gap": {"selected partners", "affiliates and partners"},
    }
    unlawful_practice_signals_by_issue: dict[str, set[str]] = {
        "missing_legal_basis": {"inferred consent", "consent inferred", "continued use"},
        "missing_retention": {"indefinite", "indefinitely", "retain forever"},
        "profiling_disclosure_gap": {"similarly significant", "legal effect"},
    }
    unlawful_signals = unlawful_practice_signals_by_issue.get(issue_name, set())
    if any(signal in text for signal in unlawful_signals):
        return "potential_unlawful_practice"
    issue_signals = invalidity_signals_by_issue.get(issue_name, set())
    if any(signal in text for signal in issue_signals):
        return "present_but_invalid_disclosure"
    if issue_name == "article_14_indirect_collection_gap":
        return "incomplete_disclosure"
    return "missing_disclosure"


def _legal_posture_layer(issue: CandidateIssue, facts: list[LegalFact]) -> tuple[str, str]:
    """
    Mandatory legal qualification layer applied after issue spotting.
    """
    issue_name = issue["candidate_issue_type"]
    text = _norm(issue.get("evidence_text") or "")
    facts_set = {(f["fact_type"], f["value"]) for f in facts}

    if issue_name == "missing_legal_basis" and (
        ("lawful_basis_model", "consent_inferred_from_use") in facts_set
        or any(t in text for t in {"consent inferred", "continued use", "inferred consent"})
    ):
        return (
            "present_but_legally_invalid",
            "Detected inferred/continued-use consent model; treat as present but legally invalid consent basis (Art. 6/7 pathway).",
        )

    if issue_name == "missing_retention" and ("retention_policy", "undefined_duration") in facts_set:
        return ("potential_unlawful_practice", "Retention language indicates indefinite or undefined duration.")

    if issue_name == "missing_transfer_notice" and ("transfer_safeguards", "vague") in facts_set:
        return ("present_but_legally_invalid", "Transfer disclosure is present but safeguards appear vague/conditional.")

    if issue_name == "profiling_disclosure_gap" and ("profiling_transparency", "missing_required_details") in facts_set:
        return ("incomplete_disclosure", "Profiling appears present, but mandatory transparency details are incomplete.")

    if issue_name == "recipients_disclosure_gap" and ("recipient_categories", "missing") in facts_set:
        return ("incomplete_disclosure", "Recipient actors are mentioned without required category-level disclosure.")

    defect_type = _defect_type_for_issue(issue)
    if defect_type == "potential_unlawful_practice":
        return ("potential_unlawful_practice", "Issue signals indicate a potentially unlawful practice pattern.")
    if defect_type == "present_but_invalid_disclosure":
        return ("present_but_legally_invalid", "Disclosure exists but fails legal validity expectations.")
    if defect_type == "incomplete_disclosure":
        return ("incomplete_disclosure", "Disclosure appears partial/incomplete for the obligation.")
    return ("missing_disclosure", "Required disclosure is not visible in the reviewed excerpt.")


def _priority_bucket_for_claims(finding: LlmFinding, claim_types: set[str]) -> str:
    text = _norm(f"{finding.gap_note or ''} {finding.remediation_note or ''}")
    fatal_signals = {
        "inferred consent",
        "continued use",
        "indefinite",
        "indefinitely",
        "without human intervention",
        "similarly significant",
        "legal effect",
    }
    material_claims = {"rights", "complaint", "recipients", "purpose_mapping", "retention", "legal_basis", "transfer", "profiling"}
    if any(signal in text for signal in fatal_signals):
        return "fatal"
    if claim_types & material_claims:
        return "material"
    return "secondary"


def _obligation_family_for_issue(issue_name: str) -> str:
    family_map = {
        "missing_controller_identity": "identity_contact_transparency",
        "missing_controller_contact": "identity_contact_transparency",
        "missing_legal_basis": "lawful_basis_and_validity",
        "missing_retention": "retention_transparency_and_storage_limitation",
        "missing_rights_information": "rights_and_complaints",
        "missing_complaint_right": "rights_and_complaints",
        "missing_transfer_notice": "international_transfers",
        "profiling_disclosure_gap": "profiling_and_article22",
        "special_category_basis_unclear": "special_category_processing",
        "article_14_indirect_collection_gap": "indirect_collection_article14",
        "controller_processor_role_ambiguity": "role_allocation_transparency",
        "recipients_disclosure_gap": "recipients_transparency",
        "purpose_specificity_gap": "purpose_specification",
    }
    return family_map.get(issue_name, "general_transparency")


FAMILY_ARTICLE_MAP: dict[str, tuple[str, list[str], list[str]]] = {
    "identity_contact_transparency": ("13(1)(a)", ["14(1)(a)", "12(1)"], ["21", "22"]),
    "lawful_basis_and_validity": ("13(1)(c)", ["14(1)(c)"], ["13(1)(a)"]),
    "retention_transparency_and_storage_limitation": ("13(2)(a)", ["14(2)(a)"], ["6(1)"]),
    "rights_and_complaints": ("13(2)(b)", ["13(2)(d)", "14(2)(c)", "14(2)(e)", "77"], ["5(1)(a)"]),
    "international_transfers": ("13(1)(f)", ["14(1)(f)", "44", "45", "46"], ["15"]),
    "profiling_and_article22": ("13(2)(f)", ["14(2)(g)"], ["21"]),
    "recipients_transparency": ("13(1)(e)", ["14(1)(e)", "12(1)"], ["21", "22"]),
    "purpose_specification": ("13(1)(c)", ["14(1)(c)", "5(1)(b)"], ["21"]),
    "indirect_collection_article14": ("14(1)", ["14(2)", "14(3)", "14(5)"], ["13(1)"]),
    "role_allocation_transparency": ("13(1)(a)", ["14(1)(a)", "12(1)"], ["28"]),
    "special_category_processing": ("9(1)", ["9(2)", "13(1)(c)", "14(1)(c)"], ["21"]),
}


def _validate_family_obligations(family: str, text: str, facts: list[LegalFact]) -> dict[str, object]:
    norm = _norm(text)
    missing: list[str] = []
    if family == "indirect_collection_article14":
        checks = {
            "source_identity_or_category": any(t in norm for t in {"source categories", "sources of personal data", "obtained from", "from third parties"}),
            "purposes": any(t in norm for t in {"purpose", "we use", "for the purpose"}),
            "legal_basis": any(f["fact_type"] == "lawful_basis" and f["value"] == "present" for f in facts),
            "rights": any(t in norm for t in {"right of access", "rectification", "erasure", "objection", "portability"}),
            "retention": any(t in norm for t in {"retention", "kept for", "storage period"}),
            "complaint_right": any(t in norm for t in {"supervisory authority", "complaint"}),
        }
        missing = [name for name, ok in checks.items() if not ok]
    satisfied = len(missing) == 0
    return {"family": family, "satisfied": satisfied, "missing": missing}


def _extract_legal_facts(text: str) -> list[LegalFact]:
    norm = _norm(text)
    facts: list[LegalFact] = []
    def _add_fact(fact_type: str, value: str, evidence: str) -> None:
        if any(f["fact_type"] == fact_type and f["value"] == value for f in facts):
            return
        facts.append(LegalFact(fact_type=fact_type, value=value, evidence=evidence))

    if any(t in norm for t in {"from partners", "from third parties", "data aggregators", "public records", "external datasets"}):
        _add_fact("data_source", "third_party", "collect/obtain data from partners/third parties/external sources")
    if any(t in norm for t in {"as long as necessary", "indefinite", "indefinitely", "extended period"}):
        _add_fact("retention_policy", "undefined_duration", "retention period wording indicates indefinite or undefined duration")
    if any(t in norm for t in {"inferred consent", "continued use", "consent inferred"}):
        _add_fact("lawful_basis_model", "consent_inferred_from_use", "consent model appears inferred from continued use")
    if any(t in norm for t in {"without human intervention", "legal effect", "similarly significant"}):
        _add_fact("automated_decisioning", "article22_risk_signal", "automated-decisioning effects/safeguard risk wording detected")
    if any(t in norm for t in {"outside the eea", "third country", "international transfer", "outside jurisdiction"}):
        _add_fact("transfer_scope", "outside_jurisdiction", "international/third-country transfer wording is visible")
        if any(t in norm for t in {"where necessary", "where appropriate", "when needed", "as applicable"}):
            _add_fact("transfer_safeguards", "vague", "transfer safeguards wording appears vague/conditional")
    recipient_category_signals = {"categories of recipients", "recipient categories", "types of recipients"}
    recipient_actor_signals = {"third party", "third-party", "partners", "vendors", "processors", "service providers"}
    if any(t in norm for t in recipient_category_signals):
        _add_fact("recipient_categories", "present", "structured recipient-category disclosure is present")
    elif any(t in norm for t in recipient_actor_signals):
        _add_fact("recipient_categories", "missing", "recipient actors are mentioned without structured categories")
    has_lawful_basis = any(t in norm for t in {"legal basis", "lawful basis", "article 6"})
    if has_lawful_basis:
        _add_fact("lawful_basis", "present", "lawful basis disclosure language is present")
        purpose_mapped = any(t in norm for t in {"for the purpose of", "for purposes of", "for each purpose", "by purpose"})
        if not purpose_mapped:
            _add_fact("lawful_basis", "present_but_unmapped", "lawful basis is present but not clearly mapped to purposes")
    profiling_present = any(t in norm for t in {"profiling", "automated decision", "scoring", "segmentation"})
    profiling_detail_present = any(t in norm for t in {"logic involved", "significance", "envisaged consequences", "human intervention"})
    if profiling_present and not profiling_detail_present:
        _add_fact("profiling_transparency", "missing_required_details", "profiling/ADM is present without required transparency detail")
    return facts


def _defect_type_from_facts(issue_name: str, facts: list[LegalFact]) -> str | None:
    facts_set = {(f["fact_type"], f["value"]) for f in facts}
    if issue_name == "missing_legal_basis" and ("lawful_basis", "present_but_unmapped") in facts_set:
        return "present_but_invalid_disclosure"
    if issue_name == "missing_legal_basis" and ("lawful_basis_model", "consent_inferred_from_use") in facts_set:
        return "potential_unlawful_practice"
    if issue_name == "missing_retention" and ("retention_policy", "undefined_duration") in facts_set:
        return "potential_unlawful_practice"
    if issue_name == "missing_transfer_notice" and ("transfer_safeguards", "vague") in facts_set:
        return "present_but_invalid_disclosure"
    if issue_name == "recipients_disclosure_gap" and ("recipient_categories", "missing") in facts_set:
        return "present_but_invalid_disclosure"
    if issue_name == "profiling_disclosure_gap" and ("profiling_transparency", "missing_required_details") in facts_set:
        return "present_but_invalid_disclosure"
    return None


def _legal_reasoning_step(
    section: SectionData,
    issue: CandidateIssue,
    qualification: LegalQualification,
    precomputed_facts: list[LegalFact] | None = None,
) -> tuple[list[LegalFact], str]:
    facts = precomputed_facts if precomputed_facts is not None else _extract_legal_facts(f"{section.section_title}. {section.content}")
    validation = _validate_family_obligations(qualification["obligation_family"], f"{section.section_title}. {section.content}", facts)
    severity_recommendation = "high" if qualification["priority_bucket"] == "fatal" else "medium"
    narrative = (
        f"Legal reasoning pipeline: facts={facts}; "
        f"mandatory_posture={issue.get('legal_posture')}; "
        f"posture_reason={issue.get('legal_posture_reason')}; "
        f"triggered_obligation_family={qualification['obligation_family']}; "
        f"obligation_validation={validation}; "
        f"legal_validation={qualification['defect_type']}; "
        f"severity_recommendation={severity_recommendation}."
    )
    return facts, narrative


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
            continue
        candidates.append(
            CandidateIssue(
                candidate_issue_type=issue,
                evidence_text=section.content[:260],
                evidence_strength=min(0.95, 0.55 + (hits * 0.12)),
                local_or_document_level=level,
                possible_collection_mode=collection_mode,
                is_visible_gap=hits > 0,
                legal_posture="missing_disclosure",
                legal_posture_reason="Initial issue-spotting placeholder; overwritten by mandatory legal posture layer.",
            )
        )
    # Family-first fallback for notice disclosure sections: avoid defaulting to controller identity.
    facts = _extract_legal_facts(f"{section.section_title}. {section.content}")
    if not candidates and (_is_notice_disclosure_section(section) or bool(facts)):
        fact_set = {(f["fact_type"], f["value"]) for f in facts}
        fallback_issue = "missing_legal_basis"
        if ("data_source", "third_party") in fact_set:
            fallback_issue = "article_14_indirect_collection_gap"
        elif ("transfer_scope", "outside_jurisdiction") in fact_set:
            fallback_issue = "missing_transfer_notice"
        elif ("profiling_transparency", "missing_required_details") in fact_set or ("automated_decisioning", "article22_risk_signal") in fact_set:
            fallback_issue = "profiling_disclosure_gap"
        elif ("recipient_categories", "missing") in fact_set:
            fallback_issue = "recipients_disclosure_gap"
        elif ("retention_policy", "undefined_duration") in fact_set:
            fallback_issue = "missing_retention"
        elif ("lawful_basis_model", "consent_inferred_from_use") in fact_set or ("lawful_basis", "present_but_unmapped") in fact_set:
            fallback_issue = "missing_legal_basis"
        if any(t in text for t in {"profil", "automated", "score", "segmentation"}):
            fallback_issue = "profiling_disclosure_gap"
        elif any(t in text for t in {"transfer", "third country", "outside the eea"}):
            fallback_issue = "missing_transfer_notice"
        elif any(t in text for t in {"processor", "on behalf of"}):
            fallback_issue = "controller_processor_role_ambiguity"
        elif any(t in text for t in {"partner", "affiliate", "broker", "source", "indirect"}):
            fallback_issue = "article_14_indirect_collection_gap"
        elif any(t in text for t in {"retention", "storage period", "kept for"}):
            fallback_issue = "missing_retention"
        elif any(t in text for t in {"rights", "access", "erasure", "rectification", "objection"}):
            fallback_issue = "missing_rights_information"
        elif any(t in text for t in {"supervisory authority", "complaint"}):
            fallback_issue = "missing_complaint_right"
        candidates.append(
            CandidateIssue(
                candidate_issue_type=fallback_issue,
                evidence_text=section.content[:220],
                evidence_strength=0.42,
                local_or_document_level="local",
                possible_collection_mode=collection_mode,
                is_visible_gap=False,
                legal_posture="missing_disclosure",
                legal_posture_reason="Initial fallback placeholder; overwritten by mandatory legal posture layer.",
            )
        )
    priority = [
        "profiling_disclosure_gap",
        "missing_transfer_notice",
        "article_14_indirect_collection_gap",
        "controller_processor_role_ambiguity",
        "missing_legal_basis",
        "missing_retention",
        "missing_rights_information",
        "missing_complaint_right",
        "missing_controller_identity",
    ]
    rank = {name: idx for idx, name in enumerate(priority)}
    facts = _extract_legal_facts(f"{section.section_title}. {section.content}")
    for candidate in candidates:
        posture, reason = _legal_posture_layer(candidate, facts)
        candidate["legal_posture"] = posture
        candidate["legal_posture_reason"] = reason
    candidates.sort(key=lambda c: (rank.get(c["candidate_issue_type"], 999), -(c["evidence_strength"] or 0.0)))
    return candidates[:6]


def _legal_qualification_for_issue(issue: CandidateIssue, facts: list[LegalFact] | None = None) -> LegalQualification:
    posture_to_defect = {
        "missing_disclosure": "missing_disclosure",
        "incomplete_disclosure": "incomplete_disclosure",
        "present_but_legally_invalid": "present_but_invalid_disclosure",
        "potential_unlawful_practice": "potential_unlawful_practice",
    }
    posture = issue.get("legal_posture")
    defect_type = posture_to_defect[posture] if posture in posture_to_defect else _defect_type_for_issue(issue)
    issue_name = issue["candidate_issue_type"]
    obligation_family = _obligation_family_for_issue(issue_name)
    if facts:
        defect_from_facts = _defect_type_from_facts(issue_name, facts)
        if defect_from_facts and defect_type not in {"present_but_invalid_disclosure", "potential_unlawful_practice"}:
            defect_type = defect_from_facts
    primary, secondary, rejected = FAMILY_ARTICLE_MAP.get(
        obligation_family,
        ("13(1)(a)", ["14(1)(a)"], ["21", "22"]),
    )
    secondary = list(secondary)
    reason_fit = f"Article set selected from obligation family '{obligation_family}' rather than snippet-level matching."
    reason_reject = "Rejected articles are outside the triggered obligation family for this finding."
    facts_set = {(f["fact_type"], f["value"]) for f in (facts or [])}

    if obligation_family == "lawful_basis_and_validity" and defect_type in {"present_but_invalid_disclosure", "potential_unlawful_practice"}:
        secondary = [*secondary, "6(1)", "7(1)"]
        reason_fit = "Lawful-basis issue kept in Article 13/14 notice family, with Articles 6/7 added because validity is implicated."
    if obligation_family == "retention_transparency_and_storage_limitation" and defect_type == "potential_unlawful_practice":
        secondary = [*secondary, "5(1)(e)"]
        reason_fit = "Retention issue mapped to Articles 13/14, with Article 5(1)(e) added due to excessive/indefinite retention pattern."
    if obligation_family == "profiling_and_article22" and (
        defect_type == "potential_unlawful_practice" or ("automated_decisioning", "article22_risk_signal") in facts_set
    ):
        secondary = [*secondary, "22"]
        reason_fit = "Profiling issue mapped to Articles 13/14 with Article 22 added because legal/similarly-significant effects are indicated."

    if defect_type == "potential_unlawful_practice":
        if issue_name == "missing_legal_basis":
            primary = "6(1)"
            secondary = ["7(1)", "13(1)(c)", "14(1)(c)"]
            rejected = ["13(1)(a)"]
            reason_fit = "Visible wording indicates potentially invalid lawful-basis practice, not only missing notice text."
            reason_reject = "Identity anchors are not primary for lawful-basis validity failures."
        elif issue_name == "missing_retention":
            primary = "5(1)(e)"
            secondary = ["13(2)(a)", "14(2)(a)"]
            rejected = ["6(1)"]
            reason_fit = "Visible indefinite/excessive retention wording may indicate storage-limitation breach."
            reason_reject = "Lawful basis provisions are not primary for storage-limitation defects."
        elif issue_name == "profiling_disclosure_gap":
            primary = "22"
            secondary = ["13(2)(f)", "14(2)(g)"]
            rejected = ["21"]
            reason_fit = "Visible legal/similarly-significant effects indicate potential Article 22 regime relevance."
            reason_reject = "Article 21 objection right is not primary for automated decisioning safeguards."
    priority_bucket = "fatal" if defect_type in {"present_but_invalid_disclosure", "potential_unlawful_practice"} else "material"
    return LegalQualification(
        issue_name=issue_name,
        obligation_family=obligation_family,
        defect_type=defect_type,
        priority_bucket=priority_bucket,
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


def _profiling_tier_from_corpus(corpus: str) -> str | None:
    profiling_signals = {"profile", "profiling", "score", "scoring", "segment", "segmentation", "model", "ranking"}
    automated_decision_signals = {
        "automated decision",
        "automated decision-making",
        "solely automated",
        "without human intervention",
        "algorithmic decision",
    }
    significant_effect_signals = {
        "legal effect",
        "similarly significant",
        "credit denial",
        "loan denial",
        "employment decision",
        "benefit denial",
        "eligibility decision",
    }
    if not _contains_any(corpus, profiling_signals):
        return None
    if _contains_any(corpus, automated_decision_signals) and _contains_any(corpus, significant_effect_signals):
        return "high_impact_automated_decisioning"
    if _contains_any(corpus, automated_decision_signals):
        return "automated_decisioning"
    return "profiling_only"


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
    # Any forward/cross reference introduces uncertainty that this excerpt is self-contained.
    if references:
        return "uncertain_scope", 0.64, []
    corpus = " ".join(_section_context_signals(s) for s in sections)
    if "..." in corpus or any(_section_context_signals(s).endswith(("and", "or", ",")) for s in sections):
        return "partial_notice_excerpt", 0.72, []
    numbered_titles = [s.section_title.strip() for s in sections if re.match(r"^\d+", s.section_title.strip())]
    if numbered_titles and len(numbered_titles) < 3:
        return "uncertain_scope", 0.55, []
    parser_completeness_confidence = min(0.98, 0.45 + (len(sections) * 0.06))
    # Full-notice is only allowed under strict completeness signals.
    if parser_completeness_confidence >= 0.86:
        return "full_notice", round(parser_completeness_confidence, 2), []
    return "uncertain_scope", round(max(0.6, parser_completeness_confidence - 0.1), 2), []


def _source_scope_proof_gate(
    sections: list[SectionData],
    source_scope: str,
    source_scope_confidence: float,
    unseen_sections: list[str],
) -> tuple[str, float]:
    if source_scope != "full_notice":
        return source_scope, source_scope_confidence
    numbered_titles = [s.section_title.strip() for s in sections if re.match(r"^\\d+", s.section_title.strip())]
    has_abrupt_tail = any(_section_context_signals(s).endswith(("and", "or", ",")) for s in sections)
    has_numbering_gaps = bool(numbered_titles) and len(numbered_titles) < 4
    parser_complete = len(sections) >= 5 and not has_abrupt_tail
    if unseen_sections or has_numbering_gaps or not parser_complete:
        downgraded = "partial_notice_excerpt" if unseen_sections else "uncertain_scope"
        return downgraded, min(source_scope_confidence, 0.74)
    return source_scope, source_scope_confidence


def _issue_has_unseen_reference(issue_id: str, refs: list[CrossReference]) -> bool:
    topic_map = {
        "missing_legal_basis": "legal_basis",
        "missing_retention_period": "retention",
        "missing_rights_notice": "rights",
        "missing_complaint_right": "rights",
        "missing_controller_identity": "controller_identity",
        "missing_controller_contact": "controller_contact",
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
        "controller_contact": "missing_controller_contact",
        "legal_basis": "missing_legal_basis",
        "retention": "missing_retention_period",
        "rights": "missing_rights_notice",
        "complaint": "missing_complaint_right",
        "transfer": "missing_transfer_notice",
        "profiling": "profiling_disclosure_gap",
        "sensitive_data": "special_category_basis_unclear",
        "right_to_object": "missing_rights_notice",
    }
    return mapping.get(claim_type, claim_type)


def _claim_issue_ids(claim_types: set[str]) -> set[str]:
    return {_claim_type_to_issue_id(c) for c in claim_types}


def _has_explicit_gdpr_fact(text: str) -> bool:
    norm = _norm(text)
    explicit_fact_signals = {
        "consent",
        "lawful basis",
        "legal basis",
        "retention",
        "storage period",
        "kept for",
        "recipient",
        "share",
        "third party",
        "third-party",
        "outside the eea",
        "third country",
        "international transfer",
        "profiling",
        "automated decision",
        "without human intervention",
        "data source",
        "partner",
        "cookies",
        "tracking",
        "supervisory authority",
        "complaint",
        "right to access",
        "rectification",
        "erasure",
        "objection",
    }
    return any(signal in norm for signal in explicit_fact_signals)


def _most_specific_article_for_claim(claim_type: str, available_articles: set[int]) -> int | None:
    preference = {
        "legal_basis": [13, 14, 6, 7, 5],
        "retention": [13, 14, 5],
        "rights": [13, 14, 12, 21, 22, 15, 16, 17, 18, 19, 20],
        "right_to_object": [21, 13, 14, 12],
        "controller_contact": [13, 14, 12],
        "complaint": [13, 14, 77, 12],
        "transfer": [13, 14, 44, 45, 46, 47, 49],
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
    explicit_fact_visible = _has_explicit_gdpr_fact(f"{section.section_title}. {section.content}")
    if len(section.content.strip()) < 140 and not explicit_fact_visible:
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

    high_claims = {"controller_identity", "controller_contact", "controller_identity_contact", "legal_basis", "rights", "complaint"}
    medium_claims = {"retention", "recipients", "purpose_mapping", "role_ambiguity"}
    conditional_high_claims = {"transfer", "profiling"}

    if claim_types & high_claims:
        return "high"
    if claim_types & medium_claims:
        return "medium"
    if claim_types & conditional_high_claims:
        text = _norm((severity or "") + " " + " ".join(sorted(claim_types)))
        return "high" if "transfer" in text or "profiling" in text else "medium"
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
    if all(token in gap for token in {"Fact:", "Law:", "Breach:", "Conclusion:"}):
        return f
    evidence = _norm(section.content)[:220]
    requirement_articles = ", ".join(sorted({c.article_number for c in citations})) or "validated GDPR disclosure obligations"
    claim_text = ", ".join(sorted(claim_types)) if claim_types else "identified transparency obligations"
    breach = gap or "Policy language appears incomplete against cited obligations."
    f.gap_note = (
        f"Fact: {evidence}. "
        f"Law: {requirement_articles} ({claim_text}). "
        f"Breach: {breach}. "
        "Conclusion: the notice should be remediated to satisfy the applicable GDPR disclosure duty."
    )
    return f


def _classify_finding_quality(
    f: LlmFinding,
    citations: list[LlmCitation],
    claim_types: set[str],
    source_mode: str,
) -> tuple[str | None, float | None]:
    presumptively_assessable_claims = CORE_NOTICE_CLAIMS | {
        "profiling",
        "transfer",
        "recipients",
        "sensitive_data",
        "controller_identity",
        "controller_contact",
        "role_ambiguity",
        "purpose_mapping",
    }
    fragmentary_markers = {"fragmentary", "truncated", "insufficient excerpt", "unseen section", "outside notice"}
    gap_text = _norm(f.gap_note or "")
    is_fragmentary = any(m in gap_text for m in fragmentary_markers)
    visible_violation_markers = {
        "inferred consent",
        "continued use",
        "indefinite retention",
        "retained indefinitely",
        "without human intervention",
        "automated decision-making affecting",
        "data aggregators",
        "external datasets",
        "partner data",
        "ad sharing",
        "risk scoring",
        "third-party enrichment",
        "third country transfer",
        "outside the eea",
        "where practical safeguards",
    }
    has_visible_violation = any(marker in gap_text for marker in visible_violation_markers)

    if f.status == "needs review":
        if has_visible_violation and not is_fragmentary:
            return "probable_gap", 0.6
        if claim_types & presumptively_assessable_claims and not is_fragmentary:
            return "probable_gap", 0.55
        return "not_assessable", 0.2
    if f.status not in {"gap", "partial"}:
        return None, None
    if not citations:
        if has_visible_violation and not is_fragmentary:
            return "probable_gap", 0.62
        if claim_types & presumptively_assessable_claims and not is_fragmentary:
            return "probable_gap", 0.58
        return "not_assessable", 0.2
    has_primary = _claim_has_primary_anchor(claim_types, citations)
    if not has_primary:
        if claim_types:
            return "probable_gap", 0.52
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


def _has_positive_controller_contradiction(text: str) -> bool:
    norm = _norm(text)
    has_entity = any(t in norm for t in {"controller", "legal entity", "company", "we are"})
    has_contact = any(t in norm for t in {"privacy@", "contact us", "email", "postal address", "webform", "dpo@"})
    return has_entity and has_contact


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
    if "recipient" in text or "third party" in text or "vendor" in text:
        return "recipients_disclosure_gap"
    if "transfer" in text or "third country" in text or "outside the eea" in text:
        return "missing_transfer_notice"
    if "profil" in text or "automated decision" in text:
        return "profiling_disclosure_gap"
    if "controller" in text and "processor" in text:
        return "controller_processor_role_ambiguity"
    if "purpose" in text and "category" in text:
        return "purpose_specificity_gap"
    if "special category" in text or "article 9" in text or "sensitive data" in text:
        return "special_category_basis_unclear"
    if "controller" in text and "contact" in text:
        return "missing_controller_contact"
    return None


def _has_flbc_reasoning(text: str | None) -> bool:
    normalized = _norm(text or "")
    return all(token in normalized for token in ("fact:", "law:", "breach:", "conclusion:"))


def _citation_articles_fit_issue(db: Session, finding_id: str, issue_key: str | None) -> bool:
    if not issue_key or issue_key not in CLAIM_ARTICLE_RULES:
        return True
    rows = db.query(FindingCitation.article_number).filter(FindingCitation.finding_id == finding_id).all()
    article_numbers = {_article_int(article) for (article,) in rows if _article_int(article) is not None}
    if not article_numbers:
        return False
    rule = CLAIM_ARTICLE_RULES[issue_key]
    has_primary_or_support = bool(article_numbers & (rule["primary"] | rule["support"]))
    has_disallowed = bool(article_numbers & rule["disallowed"])
    return has_primary_or_support and not has_disallowed


def _has_positive_contradictory_disclosure(db: Session, row: Finding, issue_key: str | None) -> bool:
    contradiction_signals = {"contradict", "conflict", "inconsistent", "already disclosed", "actually disclosed"}
    rationale = _norm(f"{row.gap_reasoning or ''} {row.gap_note or ''}")
    if not any(token in rationale for token in contradiction_signals):
        return False
    issue_terms = {
        "missing_legal_basis": {"legal basis", "article 6", "lawful basis"},
        "missing_transfer_notice": {"transfer", "third country", "safeguard", "adequacy", "scc"},
        "missing_controller_contact": {"contact", "email", "address", "webform"},
        "missing_controller_identity": {"controller", "company", "entity"},
        "missing_retention_period": {"retention", "retain", "storage period"},
        "missing_rights_notice": {"right", "access", "erasure", "rectification", "restriction"},
        "missing_complaint_right": {"complaint", "supervisory authority"},
    }.get(issue_key or "", set())
    citation_rows = db.query(FindingCitation.excerpt).filter(FindingCitation.finding_id == row.id).all()
    positive_disclosure_markers = {"we provide", "we disclose", "you can contact", "you may contact", "we retain", "you have the right"}
    for (excerpt,) in citation_rows:
        text = _norm(excerpt or "")
        if not text:
            continue
        if issue_terms and not any(term in text for term in issue_terms):
            continue
        if any(marker in text for marker in positive_disclosure_markers):
            return True
    return False


def _section_ref(section: SectionData) -> str:
    short_title = section.section_title.strip() if section.section_title.strip() else f"Section {section.section_order}"
    return f"section:{section.id}:{short_title}"


def _serialize_json_list(values: list[str]) -> str:
    unique = list(dict.fromkeys(v for v in values if v))
    return json.dumps(unique, ensure_ascii=False)


def _analysis_anchor_templates(issue: str | None) -> list[str]:
    templates = {
        "missing_controller_contact": ["GDPR Article 13(1)(a)", "GDPR Article 14(1)(a)"],
        "missing_controller_identity": ["GDPR Article 13(1)(a)", "GDPR Article 14(1)(a)"],
        "missing_transfer_notice": ["GDPR Article 13(1)(f)", "GDPR Article 14(1)(f)", "GDPR Article 44", "GDPR Article 46"],
        "profiling_disclosure_gap": ["GDPR Article 13(2)(f)", "GDPR Article 14(2)(g)", "GDPR Article 22"],
        "recipients_disclosure_gap": ["GDPR Article 13(1)(e)", "GDPR Article 14(1)(e)"],
        "purpose_specificity_gap": ["GDPR Article 13(1)(c)", "GDPR Article 14(1)(c)", "GDPR Article 5(1)(b)"],
        "missing_legal_basis": ["GDPR Article 13(1)(c)", "GDPR Article 14(1)(c)"],
        "missing_retention_period": ["GDPR Article 13(2)(a)", "GDPR Article 14(2)(a)"],
        "missing_rights_notice": [
            "GDPR Article 13(2)(b)",
            "GDPR Article 13(2)(c)",
            "GDPR Article 13(2)(d)",
            "GDPR Article 14(2)(c)",
            "GDPR Article 14(2)(d)",
            "GDPR Article 14(2)(e)",
        ],
        "missing_complaint_right": ["GDPR Article 13(2)(d)", "GDPR Article 14(2)(e)", "GDPR Article 77"],
    }
    return templates.get(issue or "", [])


def _normalize_analysis_anchors(issue: str | None, raw_anchors: str | None) -> str | None:
    preferred = _analysis_anchor_templates(issue)
    if not preferred:
        return raw_anchors
    parsed = _decode_json_list(raw_anchors)
    if not parsed:
        return _serialize_json_list(preferred)
    norm = " ".join(a.lower() for a in parsed)
    matched = [a for a in preferred if a.lower() in norm]
    return _serialize_json_list(matched or preferred)


def _decode_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return []


def _upsert_evidence_records(db: Session, audit_id: str) -> None:
    existing = {
        row[0]
        for row in db.query(EvidenceRecord.evidence_id).filter(EvidenceRecord.audit_id == audit_id).all()
    }
    pending: set[str] = set()

    def _enqueue(record: EvidenceRecord) -> None:
        if record.evidence_id in existing or record.evidence_id in pending:
            return
        pending.add(record.evidence_id)
        db.merge(record)
    findings = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    for row in findings:
        policy_evidence_id = f"evi:policy:{row.section_id}"
        _enqueue(
            EvidenceRecord(
                evidence_id=policy_evidence_id,
                audit_id=audit_id,
                evidence_type="policy_section",
                source_ref=row.section_id,
                text_excerpt=(row.policy_evidence_excerpt or row.gap_note or "")[:1000],
                article_number=(_decode_json_list(row.primary_legal_anchor)[0][:32] if _decode_json_list(row.primary_legal_anchor) else None),
            )
        )
        derived_ids = [f"evi:ref:{ref}" for ref in _decode_json_list(row.document_evidence_refs)]
        if row.section_id.startswith("systemic:"):
            systemic_id = f"evi:derived:{row.section_id}:{row.id}"
            _enqueue(
                EvidenceRecord(
                    evidence_id=systemic_id,
                    audit_id=audit_id,
                    evidence_type="derived_systemic_evidence",
                    source_ref=row.section_id,
                    text_excerpt=(row.gap_reasoning or row.gap_note or "")[:1000],
                    derived_from_evidence_ids=_serialize_json_list(derived_ids),
                    article_number=(_decode_json_list(row.primary_legal_anchor)[0][:32] if _decode_json_list(row.primary_legal_anchor) else None),
                )
            )
        for cit in row.citations:
            chunk_evidence_id = f"evi:chunk:{cit.chunk_id}"
            _enqueue(
                EvidenceRecord(
                    evidence_id=chunk_evidence_id,
                    audit_id=audit_id,
                    evidence_type="retrieval_chunk",
                    source_ref=cit.chunk_id,
                    text_excerpt=(cit.excerpt or "")[:1000],
                    derived_from_evidence_ids=_serialize_json_list([policy_evidence_id]),
                    article_number=cit.article_number,
                    paragraph_ref=cit.paragraph_ref,
                )
            )


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
            matched_sections.append(f"coverage_check:{obligation_key}=not_visible_in_reviewed_sections")
            omission_basis = True
        else:
            matched_sections.append(f"coverage_check:{obligation_key}=visible_in_reviewed_sections")
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
        section_scope = ", ".join(refs[:5]) if refs else "all reviewed notice sections"
        return (
            f"{base} Absence-proof mode: sections reviewed={section_scope}; result=required disclosure absent. "
            "Legal effect: GDPR transparency obligation is unmet because no explicit compliant disclosure text was found."
        )
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
                chunk_id=f"coverage_check:{systemic_row.section_id}:{idx}",
                article_number=anchor,
                paragraph_ref=None,
                article_title="Derived systemic legal anchor",
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
        # Cross-reference contradiction gate: unseen references block confirmed-document assertions.
        if unseen_reference_for_issue:
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
    valid_core_dispositions = {"satisfied", "gap", "referenced_but_unseen", "not_assessable"}
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
            duty_disposition[duty] = "referenced_but_unseen" if referenced_unseen else "gap"
            continue
        if present is True:
            duty_disposition[duty] = "satisfied"
            continue
        if present is False:
            reason = f"{obligation_key}=not_visible while no publishable systemic finding survived validators"
            duty_disposition[duty] = "not_assessable"
            _record_suppression_ledger(db, audit_id, issue_type, reason, "core_duty_completeness_gate", reason)
            continue
        duty_disposition[duty] = "not_assessable"
        _record_suppression_ledger(
            db,
            audit_id,
            issue_type,
            "insufficient obligation-map signal",
            "core_duty_completeness_gate",
            "duty has no boolean presence signal",
        )

    unresolved = [duty for duty in CORE_DUTY_TO_ISSUE if duty_disposition.get(duty) not in valid_core_dispositions]
    if unresolved:
        for row in rows:
            if row.section_id.startswith("systemic:"):
                row.publish_flag = "no"
                row.classification = "diagnostic_internal_only"
                row.publication_state = "blocked"
                row.artifact_role = "support_only"
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


def _issue_to_family(issue: str | None) -> str | None:
    mapping = {
        "missing_controller_identity": "controller_identity_contact",
        "missing_controller_contact": "controller_identity_contact",
        "missing_legal_basis": "legal_basis",
        "missing_retention_period": "retention",
        "missing_rights_notice": "rights_notice",
        "missing_complaint_right": "complaint_right",
        "missing_transfer_notice": "transfer",
        "missing_transfer_disclosure": "transfer",
        "profiling_disclosure_gap": "profiling",
        "controller_processor_role_ambiguity": "role_ambiguity",
        "article_14_indirect_collection_gap": "article14_source",
        "recipients_disclosure_gap": "recipients",
        "purpose_specificity_gap": "purpose_mapping",
        "special_category_basis_unclear": "special_category",
        "dpo_contact_gap": "dpo_contact",
    }
    return mapping.get(issue or "")


def _final_disposition_for_issue(rows: list[Finding], issue: str) -> tuple[str, str]:
    matched = [r for r in rows if _finding_issue_id(r) == issue]
    if any(r.classification in {"systemic_violation", "clear_non_compliance", "probable_gap"} and r.publish_flag == "yes" for r in matched):
        return "gap", "Fact: reviewed notice text indicates processing context. Law: GDPR transparency duties for this issue apply. Breach: required disclosure remains missing or unclear. Conclusion: publishable compliance gap."
    if any(r.classification == "referenced_but_unseen" for r in matched):
        return "referenced_but_unseen", "Fact: referenced sections are not visible in reviewed excerpts. Law: duty may apply but full verification needs cited sections. Breach: confirmation blocked by unseen material. Conclusion: referenced but unseen."
    if any(r.classification == "not_assessable" for r in matched):
        return "not_assessable", "Fact: available excerpt is fragmentary for this issue. Law: GDPR conclusion requires complete context. Breach: evidence scope is insufficient for legal confirmation. Conclusion: not assessable."
    return "satisfied", "no unresolved issue artifact survived gates"


def _has_positive_core_evidence(rows: list[Finding], obligation_key: str) -> bool:
    for row in rows:
        if row.status != "compliant":
            continue
        requirement = _norm(row.legal_requirement or "")
        under_review = _norm(row.obligation_under_review or "")
        if obligation_key in requirement or obligation_key in under_review:
            return True
    return False


def _build_final_disposition_map(
    rows: list[Finding],
    sections: list[SectionData],
    obligation_map: dict[str, bool],
) -> dict[str, dict[str, str | bool]]:
    def _issue_evidence_ids(issue_id: str) -> tuple[list[str], list[str]]:
        positive: set[str] = set()
        negative: set[str] = set()
        for r in rows:
            if _finding_issue_id(r) != issue_id:
                continue
            refs = _decode_json_list(r.document_evidence_refs)
            if r.classification in {"probable_gap", "clear_non_compliance", "systemic_violation", "referenced_but_unseen"}:
                positive.update(refs)
            if r.classification in {"not_assessable", "diagnostic_internal_only"}:
                negative.update(refs)
        return sorted(positive), sorted(negative)

    families: dict[str, dict[str, str]] = {}
    core_issue_by_family = {
        "controller_identity_contact": "missing_controller_identity",
        "legal_basis": "missing_legal_basis",
        "retention": "missing_retention_period",
        "rights_notice": "missing_rights_notice",
        "complaint_right": "missing_complaint_right",
    }
    core_obligation_key_by_family = {
        "controller_identity_contact": "controller_identity_contact",
        "legal_basis": "legal_basis",
        "retention": "retention",
        "rights_notice": "rights",
        "complaint_right": "complaint",
    }
    for family, issue in core_issue_by_family.items():
        status, reason = _final_disposition_for_issue(rows, issue)
        obligation_key = core_obligation_key_by_family.get(family)
        if status == "satisfied":
            if family != "controller_identity_contact" and obligation_key and obligation_map.get(obligation_key) is False:
                status, reason = "not_assessable", f"{obligation_key}=not_visible and no publishable issue found"
            elif family == "controller_identity_contact":
                identity_present = obligation_map.get("controller_identity")
                contact_present = obligation_map.get("controller_contact")
                if identity_present is False:
                    status, reason = "gap", "controller legal identity disclosure is missing or unclear"
                    issue = "missing_controller_identity"
                elif contact_present is False:
                    status, reason = "gap", "controller contact route disclosure is missing or unclear"
                    issue = "missing_controller_contact"
                elif identity_present is None or contact_present is None or not _has_positive_core_evidence(rows, "controller_identity_contact"):
                    status, reason = "gap", "controller identity/contact transparency is missing or not explicit"
                    issue = "missing_controller_contact"
            elif obligation_key and not _has_positive_core_evidence(rows, obligation_key):
                if family == "controller_identity_contact":
                    status, reason = "gap", "controller identity may be visible but controller contact disclosure is missing or unclear"
                    issue = "missing_controller_contact"
                else:
                    status, reason = "gap", f"required {obligation_key} disclosure is missing or not explicit"
        severity = "high" if family in {"controller_identity_contact", "legal_basis"} else "medium"
        families[family] = {
            "status": status,
            "reasoning": reason,
            "triggered": True,
            "publication_recommendation": "publish" if status in {"gap", "referenced_but_unseen"} else "internal_only",
            "source_scope_dependency": "high",
            "positive_evidence_ids": _issue_evidence_ids(issue)[0],
            "negative_evidence_ids": _issue_evidence_ids(issue)[1],
            "severity": severity,
            "issue_key": issue,
        }

    specialist_issue_by_family = {
        "transfer": "missing_transfer_notice",
        "profiling": "profiling_disclosure_gap",
        "role_ambiguity": "controller_processor_role_ambiguity",
        "article14_source": "article_14_indirect_collection_gap",
        "recipients": "recipients_disclosure_gap",
        "special_category": "special_category_basis_unclear",
        "dpo_contact": "dpo_contact_gap",
        "purpose_mapping": "purpose_specificity_gap",
    }
    corpus = " ".join(_section_context_signals(s) for s in sections)
    for family, issue in specialist_issue_by_family.items():
        triggered = any(signal in corpus for signal in SPECIALIST_TRIGGER_RULES.get(issue, ({family}, ""))[0])
        status, reason = _final_disposition_for_issue(rows, issue)
        specialist_severity = "high" if family in {"transfer", "special_category"} else "medium"
        if triggered:
            if family == "transfer":
                has_transfer_statement = _contains_any(corpus, THIRD_COUNTRY_TRANSFER_SIGNALS)
                has_safeguards = _contains_any(corpus, {"scc", "standard contractual clauses", "binding corporate rules", "adequacy", "art 49"})
                if has_transfer_statement and not has_safeguards:
                    status, reason = "gap", "transfer is explicitly described but safeguards/mechanisms are not disclosed"
            elif family == "profiling":
                profiling_disclosure = {"logic involved", "significance", "envisaged consequences", "article 22", "right to obtain human intervention"}
                tier = _profiling_tier_from_corpus(corpus)
                if tier and not _contains_any(corpus, profiling_disclosure):
                    status = "gap"
                    if tier == "high_impact_automated_decisioning":
                        reason = (
                            "high-impact automated decision-making signals are visible (legal/similarly significant effects) "
                            "but required Article 22 transparency and safeguards are not disclosed"
                        )
                        specialist_severity = "high"
                    elif tier == "automated_decisioning":
                        reason = (
                            "automated decision-making signals are visible but required transparency details "
                            "(logic, significance, effects, safeguards) are not disclosed"
                        )
                        specialist_severity = "high"
                    else:
                        reason = "profiling indicators are visible but required profiling transparency elements are not disclosed"
                        specialist_severity = "medium"
            elif family == "role_ambiguity":
                own_operations_signals = {
                    "our own purposes",
                    "independent business purposes",
                    "we determine the purposes",
                    "service improvement",
                    "product development",
                    "fraud prevention",
                }
                on_behalf_signals = {
                    "on behalf of",
                    "under customer instructions",
                    "instructions from customers",
                    "processor",
                    "customer data",
                }
                mixed_roles = (
                    (_contains_any(corpus, {"independent controller", "acts as controller", "controller"}) and _contains_any(corpus, {"on behalf of", "acts as processor", "processor"}))
                    or _contains_any(corpus, {"controller and processor", "both controller and processor"})
                    or (_contains_any(corpus, own_operations_signals) and _contains_any(corpus, on_behalf_signals))
                )
                clear_allocation = _contains_any(
                    corpus,
                    {
                        "when we act as controller",
                        "when we act as processor",
                        "role allocation",
                        "in these contexts we are controller",
                        "in these contexts we are processor",
                    },
                )
                if mixed_roles and not clear_allocation:
                    status, reason = "gap", "mixed controller/processor role signals are present without clear allocation wording"
            elif family == "article14_source":
                indirect_signals = _contains_any(
                    corpus,
                    {
                        "partner",
                        "partners",
                        "data aggregator",
                        "aggregator",
                        "public records",
                        "external datasets",
                        "third-party source",
                        "indirectly",
                        "from other sources",
                    },
                )
                source_category_disclosed = _contains_any(
                    corpus,
                    {
                        "categories of sources",
                        "source categories",
                        "sources of personal data",
                        "obtained from",
                    },
                )
                article14_timing_disclosed = _contains_any(
                    corpus,
                    {
                        "within one month",
                        "at the latest within one month",
                        "at first communication",
                        "before disclosure to another recipient",
                        "article 14(3)",
                    },
                )
                if indirect_signals and (not source_category_disclosed or not article14_timing_disclosed):
                    status = "gap"
                    if not source_category_disclosed and not article14_timing_disclosed:
                        reason = "indirect collection is visible but source categories and Article 14 timing duties are not clearly disclosed"
                    elif not source_category_disclosed:
                        reason = "indirect collection is visible but source categories are not clearly disclosed"
                    else:
                        reason = "indirect collection is visible but Article 14 timing duties are not clearly disclosed"
            elif family == "recipients":
                third_party_mentions = _contains_any(
                    corpus,
                    {
                        "third party",
                        "third-party",
                        "vendor",
                        "partner",
                        "reseller",
                        "marketplace",
                        "payment provider",
                        "cloud provider",
                    },
                )
                structured_recipients_disclosure = _contains_any(
                    corpus,
                    {
                        "categories of recipients",
                        "recipient categories",
                        "we disclose to the following categories",
                        "types of recipients",
                        "recipients of personal data",
                    },
                )
                if third_party_mentions and not structured_recipients_disclosure:
                    status, reason = "gap", "third-party actors are named but structured categories-of-recipients disclosure is missing"
            elif family == "purpose_mapping":
                category_sections = [
                    s
                    for s in sections
                    if re.search(r"\b2\.[1-7]\b", _norm(s.section_title)) or any(t in _norm(s.section_title) for t in {"data we collect", "personal data"})
                ]
                category_tokens = {"identifier", "contact", "usage", "behavioral", "device", "location", "payment", "profile", "special category"}
                purpose_tokens = {"purpose", "we use", "to provide", "to improve", "to personalize", "to communicate", "to comply"}
                catch_all_tokens = {
                    "for business purposes",
                    "as necessary",
                    "including but not limited to",
                    "for legitimate interests",
                    "for operational purposes",
                }
                category_coverage = 0
                mapped_coverage = 0
                broad_only_sections = 0
                for sec in category_sections:
                    text = _norm(f"{sec.section_title} {sec.content}")
                    has_category = any(t in text for t in category_tokens)
                    has_purpose = any(t in text for t in purpose_tokens)
                    has_only_broad = has_purpose and any(t in text for t in catch_all_tokens) and not _contains_any(
                        text,
                        {"specific", "for fraud prevention", "for account security", "for payment processing", "for support requests"},
                    )
                    if has_category:
                        category_coverage += 1
                    if has_category and has_purpose and not has_only_broad:
                        mapped_coverage += 1
                    if has_category and (not has_purpose or has_only_broad):
                        broad_only_sections += 1
                if category_coverage > 0 and mapped_coverage == 0:
                    status, reason = "gap", "data categories are listed but category-specific purposes are not clearly mapped"
                elif category_coverage > 0 and broad_only_sections > 0:
                    status, reason = "gap", "some category sections use broad/catch-all purposes without clear category-to-purpose mapping"
                elif category_coverage == 0 and _contains_any(corpus, {"data category", "categories of personal data"}):
                    status, reason = "referenced_but_unseen", "purpose mapping signals are present, but category-level mapping text appears outside reviewed excerpts"
            elif family == "special_category":
                text = corpus
                true_art9_indicators = {
                    "health data",
                    "biometric data",
                    "genetic data",
                    "racial or ethnic origin",
                    "political opinions",
                    "religious beliefs",
                    "trade union membership",
                    "sexual orientation",
                    "article 9",
                    "special category",
                }
                ambiguous_sensitive_only = {
                    "sensitive under applicable law",
                    "sensitive information",
                    "sensitive data",
                    "where considered sensitive",
                }
                avoid_or_incidental = {
                    "we do not routinely collect",
                    "we avoid collecting",
                    "not intended to collect",
                    "incidental collection",
                    "if unintentionally provided",
                }
                controller_context = _contains_any(
                    text,
                    {
                        "we determine the purposes",
                        "as controller",
                        "independent controller",
                        "we collect and use",
                    },
                )
                has_true_art9 = _contains_any(text, true_art9_indicators)
                has_ambiguous_sensitive = _contains_any(text, ambiguous_sensitive_only)
                has_avoid_wording = _contains_any(text, avoid_or_incidental)
                has_art9_condition = _contains_any(
                    text,
                    {
                        "article 9(2)",
                        "explicit consent",
                        "substantial public interest",
                        "employment law obligations",
                        "vital interests",
                        "legal claims",
                        "public health",
                    },
                )
                has_safeguards = _contains_any(
                    text,
                    {
                        "appropriate safeguards",
                        "data minimisation",
                        "access controls",
                        "retention limits",
                        "privacy by design",
                    },
                )
                if has_true_art9 and controller_context and not (has_art9_condition and has_safeguards):
                    status, reason = "gap", "true Article 9-category processing appears contemplated in controller context without clear Art 9 condition/safeguards"
                    specialist_severity = "high"
                elif has_avoid_wording and not has_true_art9:
                    status, reason = "satisfied", "policy states no routine special-category collection (incidental/avoidance posture)"
                    specialist_severity = "low"
                elif has_ambiguous_sensitive and not has_true_art9:
                    status, reason = "referenced_but_unseen", "ambiguous sensitive-language suggests possible special-category context, but reviewed excerpts do not confirm Article 9 processing"
                    specialist_severity = "medium"
        if triggered and status == "satisfied" and family != "special_category":
            status, reason = "referenced_but_unseen", "specialist trigger is visible, but reviewed excerpts do not include enough text to confirm full disclosure outcome"
        families[family] = {
            "status": status,
            "reasoning": reason,
            "triggered": triggered,
            "publication_recommendation": "publish" if status in {"gap", "referenced_but_unseen"} else "internal_only",
            "source_scope_dependency": "high" if triggered else "low",
            "positive_evidence_ids": _issue_evidence_ids(issue)[0],
            "negative_evidence_ids": _issue_evidence_ids(issue)[1],
            "severity": specialist_severity,
            "issue_key": issue,
        }
    core_families = ["controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right"]
    specialist_families = ["transfer", "profiling", "role_ambiguity", "article14_source", "recipients", "special_category", "dpo_contact"]
    specialist_families.append("purpose_mapping")
    unresolved_core = [f for f in core_families if families.get(f, {}).get("status") in {"unresolved_internal_error", "blocked"}]
    unresolved_specialist = [f for f in specialist_families if families.get(f, {}).get("triggered") and families.get(f, {}).get("status") not in {"satisfied", "gap", "referenced_but_unseen", "not_assessable"}]
    publishable_recommendations = [
        f for f in specialist_families + core_families if families.get(f, {}).get("publication_recommendation") == "publish"
    ]
    families["_controls"] = {
        "audit_status": "review_required" if unresolved_core else "complete",
        "publication_allowed": not unresolved_core,
        "publication_blockers": unresolved_core,
        "scope_confidence_cap": 0.75 if unresolved_core or unresolved_specialist else 1.0,
        "review_required_reasons": unresolved_core + unresolved_specialist,
    }
    families["_coverage_matrix"] = {
        "core_resolved": len(unresolved_core) == 0,
        "specialist_resolved": len(unresolved_specialist) == 0,
        "publish_recommendation_count": len(publishable_recommendations),
    }
    return families


def _state_invariant_validator(rows: list[Finding]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        violation = None
        if row.classification == "diagnostic_internal_only" and row.publication_state == "publishable":
            violation = "diagnostic_internal_only_publishable"
        elif row.classification == "diagnostic_internal_only" and row.artifact_role in {"publishable_candidate", "publishable_finding"}:
            violation = "diagnostic_internal_only_publishable_role"
        elif row.artifact_role == "support_only" and row.publication_state == "publishable":
            violation = "support_only_publishable"
        elif row.publication_state == "blocked" and row.publish_flag == "yes":
            violation = "blocked_publish_yes"
        elif row.finding_level == "none" and row.artifact_role == "publishable_finding":
            violation = "none_level_publishable_finding"
        elif row.status == "gap" and row.classification == "diagnostic_internal_only":
            violation = "diagnostic_internal_only_gap"
        if not violation:
            continue
        row.publish_flag = "no"
        row.publication_state = "blocked"
        row.artifact_role = "support_only"
        row.finding_level = "none"
        if row.classification == "diagnostic_internal_only":
            row.status = "not applicable"
            row.severity = None
        errors.append(f"state_invariant_violation:{violation}:{row.id}")
    return errors


def _final_publication_validator(
    db: Session,
    audit_id: str,
    disposition_map: dict[str, dict[str, str | bool]],
    source_scope: str,
) -> None:
    audit = db.get(Audit, audit_id)
    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    valid_final = {"satisfied", "gap", "referenced_but_unseen", "not_assessable"}
    core_families = ["controller_identity_contact", "legal_basis", "retention", "rights_notice", "complaint_right"]
    specialist_families = ["transfer", "profiling", "role_ambiguity", "article14_source", "recipients", "special_category", "dpo_contact"]
    specialist_families.append("purpose_mapping")
    unresolved_core = [f for f in core_families if disposition_map.get(f, {}).get("status") not in valid_final]
    hard_block_core = [
        f for f in core_families if disposition_map.get(f, {}).get("status") in {"unresolved_internal_error", "blocked"}
    ]
    unresolved_specialist = [f for f in specialist_families if disposition_map.get(f, {}).get("status") not in valid_final]
    if unresolved_core or unresolved_specialist:
        for family in unresolved_core:
            _record_suppression_ledger(
                db,
                audit_id,
                f"core_duty_unresolved:{family}",
                "core duty is unresolved/blocked/suppressed",
                "core_duty_publication_gate",
                disposition_map.get(family, {}).get("reasoning", "missing family disposition"),
            )
        for family in unresolved_specialist:
            _record_suppression_ledger(
                db,
                audit_id,
                f"specialist_family_unresolved:{family}",
                "triggered specialist family has no final disposition",
                "specialist_family_resolution_gate",
                disposition_map.get(family, {}).get("reasoning", "missing family disposition"),
            )
    core_ok = not unresolved_core and not unresolved_specialist and not hard_block_core
    if hard_block_core and audit is not None:
        audit.status = "review_required"
        db.add(audit)
        for family in hard_block_core:
            _record_suppression_ledger(
                db,
                audit_id,
                f"publication_blocker=unresolved_core_duty:{family}",
                "publication hard-stopped by unresolved core duty",
                "core_duty_publication_gate",
                disposition_map.get(family, {}).get("reasoning", "unresolved core duty"),
            )
    for row in rows:
        issue = _finding_issue_id(row)
        family = _issue_to_family(issue)
        family_status = disposition_map.get(family or "", {}).get("status")
        contradiction_pass = row.classification != "diagnostic_internal_only"
        scope_supports_assertion = source_scope == "full_notice" and row.assertion_level == "confirmed_document_gap"
        if source_scope != "full_notice" or (row.referenced_unseen_sections and row.referenced_unseen_sections not in {"[]", ""}):
            if row.assertion_level == "confirmed_document_gap" or row.missing_from_document == "yes":
                row.assertion_level = "excerpt_limited_gap" if row.classification != "referenced_but_unseen" else "referenced_but_unseen"
                row.missing_from_document = "unknown"
                scope_supports_assertion = False
        if hard_block_core or family_status == "not_assessable":
            row.source_scope_confidence = min(row.source_scope_confidence or 0.75, 0.75)
            if row.assertion_level == "confirmed_document_gap":
                row.assertion_level = "probable_document_gap"
        citation_count = db.query(FindingCitation).filter(FindingCitation.finding_id == row.id).count()
        missing_requirements: list[str] = []
        if not row.primary_legal_anchor:
            missing_requirements.append("primary_legal_anchor")
        if not (row.citation_summary_text or "").strip():
            missing_requirements.append("citation_summary_text")
        if not row.source_scope:
            missing_requirements.append("source_scope")
        if not row.assertion_level:
            missing_requirements.append("assertion_level")
        if row.confidence_overall is None:
            missing_requirements.append("confidence_overall")
        if not row.remediation_note:
            missing_requirements.append("remediation_note")
        if citation_count == 0:
            missing_requirements.append("citations")
        if not row.document_evidence_refs:
            missing_requirements.append("document_evidence_refs")
        issue_key = _finding_issue_id(row)
        if not _citation_articles_fit_issue(db, row.id, issue_key):
            missing_requirements.append("citations.article_matrix")
        if _has_positive_contradictory_disclosure(db, row, issue_key):
            missing_requirements.append("contradictory_text_present")

        should_publish = (
            row.publish_flag == "yes"
            and core_ok
            and family_status in {"satisfied", "gap", "referenced_but_unseen", "not_assessable", None}
            and contradiction_pass
            and (scope_supports_assertion or row.assertion_level in {"referenced_but_unseen", "excerpt_limited_gap", "not_assessable"})
            and bool(row.remediation_note)
            and not missing_requirements
        )
        if should_publish and (row.confidence_overall or 0.0) < 0.55:
            rationale = _norm(row.gap_reasoning or "")
            if "confidence" not in rationale and "evidence" not in rationale:
                missing_requirements.append("confidence_explanation")
                should_publish = False
        if should_publish and not _has_flbc_reasoning(row.gap_reasoning):
            missing_requirements.append("gap_reasoning.flbc")
            should_publish = False
        requires_strong_hydration = issue_key in {
            "missing_legal_basis",
            "missing_retention_period",
            "missing_rights_notice",
            "missing_complaint_right",
            "missing_transfer_notice",
            "profiling_disclosure_gap",
        }
        if requires_strong_hydration and (row.omission_basis is None or row.support_complete is None):
            if row.omission_basis is None:
                missing_requirements.append("omission_basis")
            if row.support_complete is None:
                missing_requirements.append("support_complete")
            should_publish = False
        if not should_publish:
            row.publish_flag = "no"
            row.publication_state = "blocked"
            row.artifact_role = "support_only"
            row.finding_level = "none"
            if row.gap_note:
                row.gap_note = f"{row.gap_note} [withheld by final publication validator]"
            _record_suppression_ledger(
                db,
                audit_id,
                f"hydration_incomplete:{issue_key}",
                "published finding hydration incomplete",
                "published_hydration_validator",
                (
                    f"finding_id={row.id}; issue_key={issue_key}; "
                    f"missing_fields={','.join(sorted(set(missing_requirements))) or 'unknown'}; "
                    f"failure_type="
                    f"{'evidence_linkage' if any(k in missing_requirements for k in ['document_evidence_refs', 'source_scope']) else 'citation_projection' if 'citations' in missing_requirements else 'source_ref'}"
                ),
            )
    for message in _state_invariant_validator(rows):
        _record_suppression_ledger(db, audit_id, message, "invariant violation", "state_invariant_validator", message)
    if audit is not None and audit.status != "review_required":
        family_issue = {
            "controller_identity_contact": {"missing_controller_identity", "missing_controller_contact"},
            "transfer": {"missing_transfer_notice"},
            "profiling": {"profiling_disclosure_gap"},
            "role_ambiguity": {"controller_processor_role_ambiguity"},
            "recipients": {"recipients_disclosure_gap"},
            "purpose_mapping": {"purpose_specificity_gap"},
        }
        missing_publishable: list[str] = []
        for family, issues in family_issue.items():
            item = disposition_map.get(family, {}) if isinstance(disposition_map.get(family, {}), dict) else {}
            if str(item.get("status") or "") not in {"gap", "referenced_but_unseen"}:
                continue
            if str(item.get("publication_recommendation") or "") != "publish":
                continue
            has_publishable = any(
                _finding_issue_id(r) in issues
                and r.publish_flag == "yes"
                and r.publication_state == "publishable"
                and r.classification in {"systemic_violation", "clear_non_compliance", "probable_gap", "referenced_but_unseen"}
                for r in rows
            )
            if not has_publishable:
                missing_publishable.append(family)
        if missing_publishable:
            audit.status = "audit_incomplete"
            db.add(audit)
            _record_suppression_ledger(
                db,
                audit_id,
                "audit_incomplete_missing_publishable_families",
                "final publication completeness gate failed",
                "final_publication_completeness_gate",
                ",".join(sorted(missing_publishable)),
            )
    db.commit()


def _partner_review_pass(db: Session, audit_id: str) -> None:
    reviewer_pass_total.inc()
    rows = db.query(Finding).filter(Finding.audit_id == audit_id).all()
    systemic_issue_keys = {row.section_id.split("systemic:", 1)[1] for row in rows if row.section_id.startswith("systemic:")}
    seen_root_keys: dict[str, str] = {}
    seen_supporting_pairs: set[tuple[str, str]] = set()
    fallback_by_issue = {
        "missing_controller_identity": (
            "Controller identity/contact details are not clearly visible in the reviewed material. Provide controller identity and privacy contact wording.",
            "Add controller legal-entity identity and a direct privacy contact channel for data-subject requests.",
        ),
        "missing_controller_contact": (
            "Controller contact route is not clearly visible in the reviewed material.",
            "Provide an explicit privacy contact route (email/webform/postal) for rights requests.",
        ),
        "missing_transfer_notice": (
            "Transfer-related language is visible, but the reviewed material does not show whether safeguards or mechanisms are disclosed. Provide the transfer/safeguards section.",
            "State whether third-country transfers occur, what mechanism is relied upon, and how data subjects can obtain information on safeguards.",
        ),
        "profiling_disclosure_gap": (
            "Behavioral/profiling indicators are visible, but the reviewed material does not show whether profiling logic, significance, or effects are disclosed. Provide profiling or automated-decision wording.",
            "Explain whether profiling occurs and, if so, describe logic, significance, and envisaged consequences where required.",
        ),
        "controller_processor_role_ambiguity": (
            "Customer-supplied data/service allocation language is visible, but the reviewed material does not clearly allocate controller/processor roles. Provide role-allocation or DPA wording.",
            "Clarify when the company acts as controller, joint controller, or processor, especially for customer-supplied datasets and hosted service operations.",
        ),
        "missing_rights_notice": (
            "The reviewed material does not show the full rights section. Provide the rights section or confirm whether it is included elsewhere in the notice.",
            "Add or link a complete rights section covering access, rectification, erasure, restriction, objection, and portability.",
        ),
        "article_14_indirect_collection_gap": (
            "Customer/partner-supplied data indicators are visible, but source-category wording for indirect collection is not fully shown. Provide Article 14 source wording.",
            "Identify source categories for indirectly obtained data and provide required Article 14 information.",
        ),
        "recipients_disclosure_gap": (
            "Third-party sharing indicators are visible, but categories-of-recipients wording is not clearly shown. Provide recipients disclosure wording.",
            "List recipient categories and disclosure contexts (processors/partners/payment/cloud providers) in notice language.",
        ),
        "purpose_specificity_gap": (
            "Data-category wording is visible, but category-to-purpose mapping remains too broad in the reviewed material.",
            "Map each major category of personal data to concrete processing purposes and legal-basis context where relevant.",
        ),
        "special_category_basis_unclear": (
            "Special-category/sensitive-data indicators are visible, but Article 9 condition and safeguards are not clearly shown.",
            "Clarify whether true Article 9 categories are processed and identify the Article 9(2) condition with safeguards.",
        ),
    }
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
            issue_id = _finding_issue_id(row)
            fallback_gap, fallback_remediation = fallback_by_issue.get(
                issue_id or "",
                (
                    "Not assessable from provided excerpt; additional documentary context is required.",
                    "Provide complete notice excerpts and rerun legal qualification.",
                ),
            )
            support_classification = "not_assessable"
            support_status = "partial"
            context_text = _norm(f"{row.policy_evidence_excerpt or ''} {row.gap_note or ''} {row.remediation_note or ''}")
            explicit_context = any(t in context_text for t in {"we collect", "we process", "we share", "we transfer", "profil", "controller", "processor"})
            clear_obligation_trigger = issue_id in {
                "missing_controller_contact",
                "missing_transfer_notice",
                "profiling_disclosure_gap",
                "controller_processor_role_ambiguity",
                "recipients_disclosure_gap",
                "purpose_specificity_gap",
                "special_category_basis_unclear",
                "missing_legal_basis",
                "missing_retention_period",
                "missing_rights_notice",
                "missing_complaint_right",
            }
            visible_omission = any(t in context_text for t in {"missing", "not disclosed", "not clearly", "without", "does not"})
            visible_problematic_fact = any(
                t in context_text
                for t in {
                    "inferred consent",
                    "continued use",
                    "indefinite",
                    "indefinitely",
                    "outside the eea",
                    "third country",
                    "data aggregators",
                    "partners",
                    "risk scoring",
                    "automated decision",
                    "without human intervention",
                }
            )
            if explicit_context and clear_obligation_trigger and visible_omission:
                support_classification = "gap_support"
                support_status = "gap"
            elif explicit_context and clear_obligation_trigger and visible_problematic_fact:
                support_classification = "gap_support"
                support_status = "gap"
            elif explicit_context and clear_obligation_trigger:
                support_classification = "section_support"
            elif clear_obligation_trigger:
                support_classification = "evidence_support"
            row.status = "partial"
            row.status = support_status
            row.classification = support_classification
            row.finding_type = "supporting_evidence"
            row.publish_flag = "no"
            row.artifact_role = "support_only"
            row.finding_level = "none"
            row.publication_state = "internal_only"
            row.gap_note = fallback_gap
            row.remediation_note = fallback_remediation
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
        if key in CLAIM_ARTICLE_RULES and row.primary_legal_anchor:
            anchors = _decode_json_list(row.primary_legal_anchor)
            anchor_articles = {_article_int(a) for a in anchors if _article_int(a) is not None}
            rule = CLAIM_ARTICLE_RULES[key]
            if anchor_articles:
                has_primary_or_support = bool(anchor_articles & (rule["primary"] | rule["support"]))
                has_disallowed = bool(anchor_articles & rule["disallowed"])
                if not has_primary_or_support or has_disallowed:
                    row.status = "not applicable"
                    row.classification = "diagnostic_internal_only"
                    row.finding_type = "supporting_evidence"
                    row.publish_flag = "no"
                    row.artifact_role = "support_only"
                    row.finding_level = "none"
                    row.publication_state = "internal_only"
                    row.gap_note = (
                        f"Issue/article family mismatch rejected for issue '{key}'. "
                        f"Anchors={sorted(anchor_articles)}; expected primary/support={sorted(rule['primary'] | rule['support'])}."
                    )
                    row.remediation_note = "Re-map fact pattern to the correct GDPR article family before publication."
                    row.confidence = min(row.confidence or 0.4, 0.4)
                    continue
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
        issue_type = _finding_issue_id(row)
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
            issue_type=issue_type,
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
            candidate_issue=issue_type,
            policy_evidence_excerpt=row.policy_evidence_excerpt,
            legal_requirement_candidate=row.legal_requirement,
            article_candidates=_normalize_analysis_anchors(issue_type, row.primary_legal_anchor),
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
    source_scope, source_scope_confidence = _source_scope_proof_gate(
        sections,
        source_scope,
        source_scope_confidence,
        unseen_sections,
    )
    document_mode = _infer_document_mode(sections)
    posture = _document_posture_agent(sections, document_mode)
    duty_validation = _document_wide_duty_validation(sections, posture["document_type"])
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
        unmet_candidates = [
            issue_name
            for issue_name in [
                "missing_controller_contact",
                "purpose_specificity_gap",
                "missing_legal_basis",
                "recipients_disclosure_gap",
                "missing_transfer_notice",
                "missing_retention",
                "missing_rights_information",
                "missing_complaint_right",
                "article_14_indirect_collection_gap",
                "profiling_disclosure_gap",
            ]
            if duty_validation.get(_duty_registry_key_for_issue(issue_name) or "", "compliant") in {"non_compliant", "partially_compliant"}
        ]
        unmet_duty_issue = None
        if unmet_candidates:
            ranked = sorted(
                ((issue_name, _issue_relevance_score(issue_name, section)) for issue_name in unmet_candidates),
                key=lambda pair: pair[1],
                reverse=True,
            )
            if ranked and ranked[0][1] > 0:
                unmet_duty_issue = ranked[0][0]
        if unmet_duty_issue and not any(c["candidate_issue_type"] == unmet_duty_issue for c in candidate_issues):
            candidate_issues.insert(
                0,
                CandidateIssue(
                    candidate_issue_type=unmet_duty_issue,
                    evidence_text=section.content[:200],
                    evidence_strength=0.6,
                    local_or_document_level="document",
                    possible_collection_mode=collection_mode,
                    is_visible_gap=True,
                    legal_posture="missing_disclosure",
                    legal_posture_reason="Injected from obligation-first document-wide duty validation.",
                ),
            )
        primary_issue = candidate_issues[0] if candidate_issues else CandidateIssue(
            candidate_issue_type="missing_controller_identity",
            evidence_text=section.content[:180],
            evidence_strength=0.35,
            local_or_document_level="local",
            possible_collection_mode=collection_mode,
            is_visible_gap=False,
            legal_posture="missing_disclosure",
            legal_posture_reason="Fallback due to no spotted issue candidates.",
        )
        legal_facts = _extract_legal_facts(f"{section.section_title}. {section.content}")
        qualification = _legal_qualification_for_issue(primary_issue, legal_facts)
        legal_facts, legal_pipeline_note = _legal_reasoning_step(section, primary_issue, qualification, legal_facts)
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
            explicit_fact_visible = _has_explicit_gdpr_fact(f"{section.section_title}. {section.content}")
            if f.status in {"gap", "partial"} and any(i["candidate_issue_type"].startswith("missing_") for i in candidate_issues):
                f.status = "partial"
                f.severity = "medium"
                f.gap_note = (
                    "Probable gap: core notice element appears missing, but direct vs indirect source mode is not fully resolved "
                    f"({applicability['unresolved_trigger']})."
                )
            elif explicit_fact_visible:
                f = LlmFinding(
                    status="partial",
                    severity="medium",
                    gap_note=(
                        "Probable gap from explicit GDPR-relevant disclosure signals, but source-mode applicability remains unresolved "
                        f"({applicability['unresolved_trigger']})."
                    ),
                    remediation_note="Clarify source-collection context and complete the required notice disclosure mapping.",
                    citations=valid_citations,
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
        violation_hits = _explicit_violation_hits(f"{section.section_title}. {section.content} {f.gap_note or ''}")
        if violation_hits and f.status in {"needs review", "not applicable"}:
            first_key, first_cfg = violation_hits[0]
            f.status = "gap"
            f.severity = "high"
            f.gap_note = (
                f"Explicit violation validator matched: {first_key}. "
                "Substantive finding forced by deterministic violation library."
            )
            f.remediation_note = f.remediation_note or "Provide explicit compliant disclosure aligned to cited GDPR duties."
            issue_hint = str(first_cfg.get("issue") or qualification["issue_name"])
            claim_types = _claim_types_from_text(issue_hint) or claim_types
        f.severity = _normalize_severity(f.status, f.severity, claim_types)
        if qualification["priority_bucket"] == "fatal" and f.status in {"gap", "partial"}:
            f.severity = "high"
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
                f"obligation_family={qualification['obligation_family']}; "
                f"defect_type={qualification['defect_type']}; priority_bucket={qualification['priority_bucket']}; "
                f"primary={qualification['primary_article']}; secondary={', '.join(qualification['secondary_articles'])}; "
                f"rejected={', '.join(qualification['rejected_articles'])}. "
                f"Primary fit: {qualification['reason_primary_article_fits']} "
                f"Rejected rationale: {qualification['reason_rejected_articles_do_not_fit']}"
            )
            if legal_facts:
                f.gap_note = f"{f.gap_note} {legal_pipeline_note}"
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
        if classification == "not_assessable" and not _not_assessable_allowed(
            f"{section.section_title}. {section.content}. {f.gap_note or ''}. {f.remediation_note or ''}",
            f.status,
            classification,
        ):
            classification = "probable_gap" if f.status in {"gap", "partial"} else "clear_non_compliance"
            if f.status == "needs review":
                f.status = "partial"
                f.severity = f.severity or "medium"
                f.gap_note = (
                    "Substantive disclosure signal detected; not-assessable is disallowed by strict legal gate."
                )
        explicit_after_classification = _explicit_violation_hits(f"{section.section_title}. {section.content} {f.gap_note or ''}")
        if explicit_after_classification and classification in {"not_assessable", "diagnostic_internal_only", "retrieval_failure_internal_only"}:
            classification = "clear_non_compliance"
            f.status = "gap"
            f.severity = "high"
            f.gap_note = (
                f"Explicit violation validator matched ({explicit_after_classification[0][0]}). "
                "Finding promoted to substantive non-compliance."
            )
        consistency_ok, consistency_reason = _pre_persist_consistency_gate(
            qualification["issue_name"],
            claim_types,
            memo["obligation"],
            valid_citations,
            f.remediation_note,
            classification,
        )
        if not consistency_ok:
            controller_issue = qualification["issue_name"] in {"missing_controller_identity", "missing_controller_contact"}
            contradictory_disclosure = _has_positive_controller_contradiction(section.content)
            if controller_issue and not contradictory_disclosure:
                classification = classification or "probable_gap"
                f.gap_note = (
                    f"{f.gap_note or ''} Fact: controller-related processing context is visible. "
                    "Law: GDPR Articles 13(1)(a)/14(1)(a) require controller identity and contact-route disclosure. "
                    f"Breach: {consistency_reason or 'controller-contact disclosure remains unclear'}. "
                    "Conclusion: keep as publishable controller identity/contact gap absent contradictory disclosure."
                ).strip()
                confidence = max(confidence or 0.55, 0.55)
            else:
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
                classification = "diagnostic_internal_only"
                confidence = 0.4
            else:
                seen_signatures[signature] = section.id

        if classification == "not_assessable" and _has_explicit_gdpr_fact(f"{section.section_title}. {section.content}"):
            classification = "probable_gap"
            if f.status == "needs review":
                f.status = "partial"
                f.severity = f.severity or "medium"
                f.gap_note = (
                    "Probable GDPR gap: explicit processing/legal signals are present, so finding is not treated as not-assessable."
                )
                f.remediation_note = f.remediation_note or "Provide complete, mapped disclosure text to confirm final legal posture."

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
            policy_evidence_excerpt=(
                f.policy_evidence_excerpt
                or (primary_issue["evidence_text"] or section.content[:220]).strip()
            ),
            legal_requirement=(
                f.legal_requirement
                or (
                    f"Primary legal anchor: GDPR Article {qualification['primary_article']} for issue "
                    f"{qualification['issue_name']}."
                )
            ),
            gap_reasoning=f.gap_reasoning or f.gap_note,
            confidence_level=f.confidence_level or _confidence_level_for(confidence),
            assessment_type=f.assessment_type or _assessment_type_for(f, classification),
            severity_rationale=f.severity_rationale or _severity_rationale(f, claim_types),
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
    rows_for_disposition = db.query(Finding).filter(Finding.audit_id == audit.id).all()
    final_disposition_map = _build_final_disposition_map(rows_for_disposition, sections, obligation_map)
    _final_publication_validator(db, audit.id, final_disposition_map, source_scope)
    _record_suppression_ledger(
        db,
        audit.id,
        "final_disposition_map",
        "snapshot",
        "final_disposition_map",
        json.dumps(final_disposition_map, sort_keys=True),
    )
    _partner_review_pass(db, audit.id)
    _upsert_evidence_records(db, audit.id)
    post_review_rows = db.query(Finding).filter(Finding.audit_id == audit.id).all()
    invariant_errors = _state_invariant_validator(post_review_rows)
    if invariant_errors:
        for message in invariant_errors:
            _record_suppression_ledger(
                db,
                audit.id,
                message,
                "post-review invariant rewrite",
                "state_invariant_validator",
                message,
            )
        db.commit()
    _snapshot_analysis_items(db, audit.id)

    audit.status = "complete"
    audit.completed_at = datetime.utcnow()
    db.add(audit)
    db.commit()
    db.refresh(audit)
    audit_duration_seconds.observe(time.monotonic() - audit_started)
    return audit
