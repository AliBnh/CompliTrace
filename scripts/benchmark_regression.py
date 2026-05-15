"""
Benchmark regression gate for pp_NonCompliant.pdf and pp_Compliant.pdf.

Usage:
    python scripts/benchmark_regression.py

Exit code 0 = all checks pass.  Exit code 1 = one or more failures.

Run from the repo root:
    cd <repo-root>  &&  python scripts/benchmark_regression.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE = "http://localhost:8003"
ING = "http://localhost:8001"

DOCS = {
    "nc": Path("docs/pp_NonCompliant.pdf"),
    "co": Path("docs/pp_compliant.pdf"),
}

BANNED_TEXT = [
    "support_only",
    "internal_only",
    "candidate_issue",
    "provisional_local",
    "support_evidence",
    "post_reviewer_snapshot",
    "meta_section",
    "auditability gate",
    "not_assessable",
    "clear_non_compliance",
    "duty validation marked",
    "filtered by",
    "explicit violation validator matched",
    "validator token",
    "no explicit evidence refs from final map",
    "withheld by final publication validator",
    "signal detected",
    "legal gate",
    "duty-level",
    "suppressed",
    "no_exportable_findings_after_safety_filters",
    "invariant",
    "candidate_gap",
    "candidate_compliant",
]

# ── helpers ──────────────────────────────────────────────────────────────────

def upload(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{ING}/documents", files={"file": (path.name, f, "application/pdf")})
    r.raise_for_status()
    return r.json()["id"]


def start_audit(doc_id: str) -> str:
    r = requests.post(f"{BASE}/audits", json={"document_id": doc_id})
    r.raise_for_status()
    return r.json()["id"]


def wait_audit(audit_id: str, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE}/audits/{audit_id}")
        r.raise_for_status()
        data = r.json()
        if data["status"] in {"complete", "failed"}:
            return data
        time.sleep(6)
    raise TimeoutError(f"Audit {audit_id} did not complete within {timeout}s")


def get_findings(audit_id: str) -> list[dict]:
    r = requests.get(f"{BASE}/audits/{audit_id}/findings")
    r.raise_for_status()
    return r.json()


def get_review(audit_id: str) -> list[dict]:
    r = requests.get(f"{BASE}/audits/{audit_id}/review")
    r.raise_for_status()
    return r.json()


def get_export_contract(audit_id: str) -> dict:
    r = requests.get(f"{BASE}/audits/{audit_id}/export-contract")
    r.raise_for_status()
    return r.json()


def trigger_report(audit_id: str) -> str:
    r = requests.post(f"{BASE}/audits/{audit_id}/report")
    r.raise_for_status()
    return r.json()["report_id"]


def wait_report(audit_id: str, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE}/audits/{audit_id}/report")
        r.raise_for_status()
        data = r.json()
        if data["status"] in {"ready", "failed"}:
            return data
        time.sleep(3)
    raise TimeoutError(f"Report for {audit_id} did not become ready within {timeout}s")


def download_report(audit_id: str) -> bytes:
    r = requests.get(f"{BASE}/audits/{audit_id}/report/download")
    r.raise_for_status()
    return r.content


# ── checker ──────────────────────────────────────────────────────────────────

class Check:
    def __init__(self) -> None:
        self._results: list[tuple[bool, str]] = []

    def ok(self, label: str) -> None:
        self._results.append((True, label))

    def fail(self, label: str) -> None:
        self._results.append((False, label))

    def expect(self, condition: bool, label: str) -> None:
        if condition:
            self.ok(label)
        else:
            self.fail(label)

    def summary(self) -> tuple[int, int]:
        passed = sum(1 for ok, _ in self._results if ok)
        return passed, len(self._results)

    def print_report(self) -> None:
        for ok, label in self._results:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {label}")


def banned_text_in(obj: Any) -> list[str]:
    """Scan all fields of obj for banned text tokens."""
    hits: list[str] = []
    serialized = json.dumps(obj).lower()
    for token in BANNED_TEXT:
        if token.lower() in serialized:
            hits.append(token)
    return hits


# Fields in ReviewItemOut that carry internal DB enum state — not user-facing text.
_REVIEW_INTERNAL_FIELDS = frozenset({
    "classification", "artifact_role", "publication_state", "finding_level",
    "publication_recommendation", "source_scope_dependency", "item_kind",
})


def banned_text_in_review(rows: list[dict]) -> list[str]:
    """Scan only user-facing text fields in review rows for banned tokens.

    Skips internal state enum fields (classification, artifact_role, etc.) which
    legitimately contain values like 'clear_non_compliance' that would otherwise
    trigger false positives.
    """
    hits: list[str] = []
    for row in rows:
        user_facing = {k: v for k, v in row.items() if k not in _REVIEW_INTERNAL_FIELDS}
        row_hits = banned_text_in(user_facing)
        hits.extend(row_hits)
    return list(set(hits))


# ── per-finding field checks ──────────────────────────────────────────────────

def check_finding_fields(chk: Check, label: str, findings: list[dict]) -> None:
    for f in findings:
        fid = f.get("issue_key") or f.get("id") or "?"
        prefix = f"{label} finding {fid}"
        chk.expect(bool(f.get("issue_key", "").strip()), f"{prefix}: has issue_key")
        chk.expect(bool(f.get("issue_label", "").strip()), f"{prefix}: has issue_label")
        chk.expect(bool(f.get("severity", "").strip()), f"{prefix}: has severity")
        chk.expect(bool((f.get("policy_evidence_excerpt") or "").strip()), f"{prefix}: has document evidence")
        chk.expect(len(f.get("citations") or []) > 0, f"{prefix}: has citations")
        chk.expect(len(f.get("primary_legal_anchor") or []) > 0, f"{prefix}: has legal anchors")
        chk.expect(bool((f.get("gap_note") or "").strip()), f"{prefix}: has gap_note")
        chk.expect(bool((f.get("remediation_note") or "").strip()), f"{prefix}: has remediation_note")


# ── main regression ───────────────────────────────────────────────────────────

def run_benchmark() -> bool:
    chk = Check()

    # ── verify docs exist ──────────────────────────────────────────────────────
    for key, path in DOCS.items():
        chk.expect(path.exists(), f"benchmark doc exists: {path}")
    if not all(p.exists() for p in DOCS.values()):
        print("\n[FATAL] Benchmark PDFs not found — aborting.")
        chk.print_report()
        return False

    # ── upload ─────────────────────────────────────────────────────────────────
    print("Uploading documents ...")
    nc_doc = upload(DOCS["nc"])
    co_doc = upload(DOCS["co"])
    print(f"  NC doc_id={nc_doc}")
    print(f"  CO doc_id={co_doc}")

    # ── start audits ───────────────────────────────────────────────────────────
    print("Starting audits ...")
    nc_audit = start_audit(nc_doc)
    co_audit = start_audit(co_doc)
    print(f"  NC audit_id={nc_audit}")
    print(f"  CO audit_id={co_audit}")

    # ── wait for completion ────────────────────────────────────────────────────
    print("Waiting for audits (this may take several minutes) ...")
    nc_result = wait_audit(nc_audit)
    co_result = wait_audit(co_audit)
    print(f"  NC status={nc_result['status']}  CO status={co_result['status']}")

    chk.expect(nc_result["status"] == "complete", "NC audit completed successfully")
    chk.expect(co_result["status"] == "complete", "CO audit completed successfully")

    # ── fetch findings ─────────────────────────────────────────────────────────
    nc_findings = get_findings(nc_audit)
    co_findings = get_findings(co_audit)

    # ── fetch review ───────────────────────────────────────────────────────────
    nc_review = get_review(nc_audit)
    co_review = get_review(co_audit)

    # ── fetch export contracts ─────────────────────────────────────────────────
    nc_contract = get_export_contract(nc_audit)
    co_contract = get_export_contract(co_audit)

    # ── generate + download reports ────────────────────────────────────────────
    print("Generating reports ...")
    trigger_report(nc_audit)
    trigger_report(co_audit)
    nc_report = wait_report(nc_audit)
    co_report = wait_report(co_audit)
    chk.expect(nc_report["status"] == "ready", "NC report generated successfully")
    chk.expect(co_report["status"] == "ready", "CO report generated successfully")

    nc_pdf_bytes = b""
    co_pdf_bytes = b""
    try:
        nc_pdf_bytes = download_report(nc_audit)
        chk.expect(len(nc_pdf_bytes) > 1024, "NC report download returned non-empty PDF")
    except Exception as exc:
        chk.fail(f"NC report download: {exc}")

    try:
        co_pdf_bytes = download_report(co_audit)
        chk.expect(len(co_pdf_bytes) > 1024, "CO report download returned non-empty PDF")
    except Exception as exc:
        chk.fail(f"CO report download: {exc}")

    # ══════════════════════════════════════════════════════════════════════════
    # NC assertions
    # ══════════════════════════════════════════════════════════════════════════
    nc_keys = {f.get("issue_key", "") for f in nc_findings}

    chk.expect(
        6 <= len(nc_findings) <= 10,
        f"NC published findings count in [6, 10]: got {len(nc_findings)}"
    )

    # Required mandatory issue keys
    chk.expect(
        bool(nc_keys & {"missing_legal_basis", "invalid_consent_or_legal_basis", "lawful_basis_and_consent"}),
        "NC includes lawful_basis_and_consent (or constituent missing_legal_basis / invalid_consent_or_legal_basis)"
    )
    chk.expect("missing_retention_period" in nc_keys, "NC includes missing_retention_period")
    chk.expect("missing_transfer_notice" in nc_keys, "NC includes missing_transfer_notice")
    chk.expect("profiling_disclosure_gap" in nc_keys, "NC includes profiling_disclosure_gap")
    chk.expect(
        bool(nc_keys & {"missing_rights_notice", "incomplete_rights_notice"}),
        "NC includes missing_rights_notice or incomplete_rights_notice"
    )
    chk.expect("missing_complaint_right" in nc_keys, "NC includes missing_complaint_right")

    # Optional issue keys (report presence only — not required to pass gate)
    for opt_key in ["cookies_tracking_consent_gap", "article14_source_transparency_gap", "recipients_disclosure_gap"]:
        present = opt_key in nc_keys
        print(f"  [INFO] NC optional key {opt_key}: {'present' if present else 'absent'}")

    # Per-finding field completeness
    check_finding_fields(chk, "NC", nc_findings)

    # No banned/debug text in published NC output
    nc_banned = banned_text_in(nc_findings)
    chk.expect(len(nc_banned) == 0, f"NC published findings: no banned text (found: {nc_banned or 'none'})")

    # NC export contract counts match published findings count
    chk.expect(
        nc_contract.get("export_allowed", False),
        "NC export contract: export_allowed=true"
    )
    contract_nc_total = nc_contract.get("counts_by_status", {}).get("total", -1)
    chk.expect(
        contract_nc_total == len(nc_findings),
        f"NC export contract total ({contract_nc_total}) == published findings count ({len(nc_findings)})"
    )

    # No banned text in NC review (default mode — no debug rows)
    nc_review_non_diag = [r for r in nc_review if r.get("item_kind") not in ("diagnostics_summary", "review_block")]
    nc_review_banned = banned_text_in_review(nc_review_non_diag)
    chk.expect(len(nc_review_banned) == 0, f"NC review: no banned text (found: {nc_review_banned or 'none'})")

    # ══════════════════════════════════════════════════════════════════════════
    # CO assertions
    # ══════════════════════════════════════════════════════════════════════════
    co_keys = {f.get("issue_key", "") for f in co_findings}

    chk.expect(len(co_findings) == 0, f"CO published findings == 0: got {len(co_findings)}")

    # No high-severity findings in CO
    co_high = [f for f in co_findings if (f.get("severity") or "").lower() == "high"]
    chk.expect(len(co_high) == 0, f"CO has no high-severity findings (got {len(co_high)})")

    # None of the mandatory NC keys appear as published gaps in CO
    forbidden_co = {
        "missing_transfer_notice",
        "missing_rights_notice",
        "missing_complaint_right",
        "profiling_disclosure_gap",
        "missing_retention_period",
    }
    leaked = co_keys & forbidden_co
    chk.expect(len(leaked) == 0, f"CO has no forbidden published gaps (leaked: {leaked or 'none'})")

    # No banned/internal text in CO published output
    co_banned = banned_text_in(co_findings)
    chk.expect(len(co_banned) == 0, f"CO published findings: no banned text (found: {co_banned or 'none'})")

    co_review_non_diag = [r for r in co_review if r.get("item_kind") not in ("diagnostics_summary", "review_block")]
    co_review_banned = banned_text_in_review(co_review_non_diag)
    chk.expect(len(co_review_banned) == 0, f"CO review: no banned text (found: {co_review_banned or 'none'})")

    co_contract_total = co_contract.get("counts_by_status", {}).get("total", -1)
    chk.expect(
        co_contract_total == 0,
        f"CO export contract total == 0: got {co_contract_total}"
    )
    chk.expect(
        co_contract.get("export_allowed", True) is True or co_contract_total == 0,
        "CO export contract: zero-findings state consistent"
    )

    # ══════════════════════════════════════════════════════════════════════════
    # Cross-doc assertions
    # ══════════════════════════════════════════════════════════════════════════
    nc_contract_finding_count = len(nc_contract.get("finding_ids", []))
    chk.expect(
        nc_contract_finding_count == len(nc_findings),
        f"NC: export contract finding_ids count ({nc_contract_finding_count}) == published findings ({len(nc_findings)})"
    )

    # ── print results ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BENCHMARK REGRESSION RESULTS")
    print("=" * 60)

    print("\n[NC] Published findings:")
    for f in nc_findings:
        scope = "[SYS]" if (f.get("section_id") or "").startswith("systemic:") else "[SEC]"
        sev = (f.get("severity") or "?").upper()
        print(f"  {scope} {f.get('issue_key')}  sev={sev}  cits={len(f.get('citations') or [])}")

    print("\n[CO] Published findings:")
    if co_findings:
        for f in co_findings:
            print(f"  {f.get('issue_key')}")
    else:
        print("  (none — correct)")

    print("\nChecklist:")
    chk.print_report()

    passed, total = chk.summary()
    print(f"\n{'=' * 60}")
    print(f"TOTAL: {passed}/{total} checks passed")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    ok = run_benchmark()
    sys.exit(0 if ok else 1)
