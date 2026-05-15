"""
Benchmark test script — runs both benchmark PDFs through the audit pipeline
and prints results in the standard format.

Usage:  python scripts/benchmark.py
"""
import time
import requests

BASE = "http://localhost:8003"
ING  = "http://localhost:8001"
DOC_DIR = "docs"

DOCS = {
    "compliant":     f"{DOC_DIR}/pp_compliant.pdf",
    "non_compliant": f"{DOC_DIR}/pp_NonCompliant.pdf",
}


def upload(path: str) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{ING}/documents", files={"file": (path, f, "application/pdf")})
    r.raise_for_status()
    return r.json()["id"]


def start_audit(doc_id: str) -> str:
    r = requests.post(f"{BASE}/audits", json={"document_id": doc_id})
    r.raise_for_status()
    return r.json()["id"]


def wait_audit(audit_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE}/audits/{audit_id}")
        r.raise_for_status()
        data = r.json()
        if data["status"] in {"complete", "failed"}:
            return data
        time.sleep(5)
    raise TimeoutError(f"Audit {audit_id} did not complete within {timeout}s")


def get_findings(audit_id: str) -> list[dict]:
    r = requests.get(f"{BASE}/audits/{audit_id}/findings")
    r.raise_for_status()
    return r.json()


def get_analysis(audit_id: str) -> list[dict]:
    r = requests.get(f"{BASE}/audits/{audit_id}/analysis")
    try:
        r.raise_for_status()
        return r.json()
    except Exception:
        return []


def summarise(label: str, audit_id: str, findings: list[dict], analysis: list[dict]) -> None:
    # /audits/{id}/findings already returns only published findings (filtered server-side)
    published = findings
    # Deduplicate by issue key
    seen: set[str] = set()
    unique_published: list[dict] = []
    for f in published:
        key = f.get("issue_key") or f.get("obligation_under_review") or f.get("id")
        if key not in seen:
            seen.add(key)
            unique_published.append(f)

    print(f"\n{'='*55}")
    label_upper = label.upper().replace("_", "-")
    print(f" {label_upper}: {len(unique_published)} published finding(s)")
    print(f"{'='*55}")
    for f in unique_published:
        issue = f.get("issue_key") or f.get("obligation_under_review") or "unknown"
        level = "[SYS]" if "systemic" in (f.get("finding_type") or "") or (f.get("section_id") or "").startswith("systemic:") else "[SEC]"
        cits  = len(f.get("citations") or [])
        doc_ev = "OK" if (f.get("policy_evidence_excerpt") or "").strip() else "MISSING"
        cit_sum = "OK" if (f.get("citation_summary_text") or "").strip() else "MISSING"
        conf_val = f.get("confidence_overall") or f.get("confidence") or 0.0
        conf_lbl = f.get("confidence_level") or ("high" if conf_val >= 0.75 else "medium" if conf_val >= 0.5 else "low")
        refs = len(f.get("document_evidence_refs") or []) if isinstance(f.get("document_evidence_refs"), list) else 0
        print(f"  {level} {issue}")
        print(f"      cits={cits}  doc_ev={doc_ev}  refs={refs}  cit_summary={cit_sum}  conf={conf_val:.2f}({conf_lbl})")

    # Analysis breakdown
    if analysis:
        by_outcome: dict[str, int] = {}
        null_issue = 0
        gap_null = 0
        for a in analysis:
            outcome = a.get("analysis_outcome") or a.get("status_candidate") or "unknown"
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
            if a.get("issue_type") is None:
                null_issue += 1
                if (a.get("status_candidate") or "").startswith("candidate_gap"):
                    gap_null += 1
        breakdown = " | ".join(f"{k}:{v}" for k, v in sorted(by_outcome.items()))
        print(f"\n  Analysis ({len(analysis)} items): {breakdown}")
        print(f"  Null issue_type: {null_issue}/{len(analysis)} (gap nulls: {gap_null})")


def main() -> None:
    print("=== Uploading compliant doc ===")
    co_doc = upload(DOCS["compliant"])
    print(f"Compliant doc_id={co_doc}")
    print("=== Uploading non-compliant doc ===")
    nc_doc = upload(DOCS["non_compliant"])
    print(f"Non-compliant doc_id={nc_doc}")
    print("=== Starting audits ===")
    co_audit = start_audit(co_doc)
    nc_audit = start_audit(nc_doc)
    print(f"Compliant audit={co_audit}")
    print(f"Non-compliant audit={nc_audit}")
    print("=== Waiting for completion ===")
    co_result = wait_audit(co_audit)
    nc_result = wait_audit(nc_audit)
    print(f"CO: {co_result['status']}  NC: {nc_result['status']}")

    co_findings = get_findings(co_audit)
    nc_findings = get_findings(nc_audit)
    co_analysis = get_analysis(co_audit)
    nc_analysis = get_analysis(nc_audit)

    summarise("compliant", co_audit, co_findings, co_analysis)
    summarise("non_compliant", nc_audit, nc_findings, nc_analysis)
    print()


if __name__ == "__main__":
    main()
