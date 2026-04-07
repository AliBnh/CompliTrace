#!/usr/bin/env python3
"""Day 3-5 gate validator for CompliTrace Knowledge Service.

Checks:
1) Retrieval quality over representative GDPR queries.
2) Endpoint behavior stability for /search and /chunks/{id}.
3) Writes a JSON report you can share back for review.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QueryCase:
    name: str
    query: str
    expected_articles: tuple[str, ...]


QUERY_SET: tuple[QueryCase, ...] = (
    QueryCase("Storage limitation", "data retention period storage limitation personal data", ("5", "13")),
    QueryCase("Lawful basis", "lawful basis for processing personal data contract consent", ("6",)),
    QueryCase("Data subject rights", "access rectification erasure objection portability rights", ("15", "16", "17", "18", "20", "21")),
    QueryCase("International transfers", "transfer personal data third country safeguards", ("44", "45", "46")),
    QueryCase("Processor obligations", "processor contract obligations controller processor", ("28",)),
    QueryCase("Security measures", "appropriate technical organisational security measures", ("32",)),
    QueryCase("Breach notification", "notify supervisory authority personal data breach 72 hours", ("33",)),
    QueryCase("DPO designation", "data protection officer designation tasks", ("37", "38", "39")),
    QueryCase("Purpose limitation", "purpose limitation collected for specified explicit legitimate purposes", ("5",)),
    QueryCase("Children consent", "child consent information society services age", ("8",)),
    QueryCase("Transparency info", "information to be provided to data subject", ("13", "14")),
    QueryCase("Records of processing", "records of processing activities controller processor", ("30",)),
)


def _http_json(method: str, url: str, body: dict | None = None, timeout: float = 30.0) -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8") if e.fp else "{}"
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = {"raw": payload}
        return e.code, parsed


def validate(base_url: str, k: int, repeats: int) -> dict:
    base_url = base_url.rstrip("/")

    health_code, health = _http_json("GET", f"{base_url}/health")
    if health_code != 200:
        raise RuntimeError(f"Health check failed: status={health_code}, payload={health}")

    retrieval_rows = []
    chunk_endpoint_checks = []

    for case in QUERY_SET:
        run_rows = []
        for _ in range(repeats):
            code, payload = _http_json("POST", f"{base_url}/search", {"query": case.query, "k": k})
            if code != 200:
                raise RuntimeError(f"/search failed for '{case.name}': status={code}, payload={payload}")

            results = payload.get("results", [])
            article_ranking = [str(r.get("article_number")) for r in results]
            scores = [float(r.get("score", 0.0)) for r in results]
            top_chunk_id = results[0]["chunk_id"] if results else None

            # /chunks behavior check on first result
            chunk_status = None
            if top_chunk_id:
                ccode, cpay = _http_json("GET", f"{base_url}/chunks/{urllib.parse.quote(top_chunk_id)}")
                chunk_status = ccode
                chunk_endpoint_checks.append(
                    {
                        "query": case.name,
                        "chunk_id": top_chunk_id,
                        "status_code": ccode,
                        "article_number": cpay.get("article_number") if isinstance(cpay, dict) else None,
                    }
                )

            expected = set(case.expected_articles)
            found_top_k = expected.intersection(article_ranking)
            found_top_3 = expected.intersection(article_ranking[:3])

            run_rows.append(
                {
                    "articles": article_ranking,
                    "scores": scores,
                    "top_chunk_id": top_chunk_id,
                    "expected_found_top_k": sorted(found_top_k),
                    "expected_found_top_3": sorted(found_top_3),
                    "chunk_status": chunk_status,
                }
            )

        top1_articles = [row["articles"][0] if row["articles"] else None for row in run_rows]
        stability = len(set(top1_articles)) == 1
        avg_top1_score = statistics.mean((row["scores"][0] if row["scores"] else 0.0) for row in run_rows)

        retrieval_rows.append(
            {
                "name": case.name,
                "query": case.query,
                "expected_articles": list(case.expected_articles),
                "runs": run_rows,
                "top1_stable": stability,
                "avg_top1_score": round(avg_top1_score, 4),
                "expected_in_top_k_any_run": any(bool(r["expected_found_top_k"]) for r in run_rows),
                "expected_in_top_3_any_run": any(bool(r["expected_found_top_3"]) for r in run_rows),
            }
        )

    total = len(retrieval_rows)
    topk_pass = sum(1 for r in retrieval_rows if r["expected_in_top_k_any_run"])
    top3_pass = sum(1 for r in retrieval_rows if r["expected_in_top_3_any_run"])
    stable_pass = sum(1 for r in retrieval_rows if r["top1_stable"])
    chunk_200 = sum(1 for c in chunk_endpoint_checks if c["status_code"] == 200)

    summary = {
        "queries_total": total,
        "topk_expected_hit": topk_pass,
        "topk_expected_hit_rate": round(topk_pass / total, 3),
        "top3_expected_hit": top3_pass,
        "top3_expected_hit_rate": round(top3_pass / total, 3),
        "top1_stable_queries": stable_pass,
        "top1_stable_rate": round(stable_pass / total, 3),
        "chunks_200": chunk_200,
        "chunks_total": len(chunk_endpoint_checks),
        "chunks_success_rate": round(chunk_200 / max(1, len(chunk_endpoint_checks)), 3),
    }

    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "k": k,
        "repeats": repeats,
        "health": health,
        "summary": summary,
        "queries": retrieval_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8002")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--out", default="docs/day3_5_knowledge_gate_report.json")
    args = parser.parse_args()

    report = validate(args.base_url, args.k, args.repeats)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report["summary"], indent=2))
    print(f"\nReport saved to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
