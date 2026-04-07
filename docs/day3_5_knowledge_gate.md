# Day 3–5 Knowledge Service Formal Gate

This checklist formalizes the Day 3–5 gate from the build plan.

## What to validate

1. Retrieval quality on 10–15 representative GDPR queries.
2. `/search` endpoint stability and repeatability.
3. `/chunks/{id}` endpoint behavior for IDs returned by `/search`.
4. Threshold calibration note captured for orchestration logic:
   - retry threshold: `0.45`
   - evidence gate: `0.50`

## Run

```bash
python scripts/validation/knowledge_gate_day3_5.py --base-url http://localhost:8002 --k 5 --repeats 2
```

The script writes:

- `docs/day3_5_knowledge_gate_report.json`

## Pass guidance

- `topk_expected_hit_rate` should be high (target >= 0.8 for this stage).
- `chunks_success_rate` must be `1.0`.
- Investigate low `top3_expected_hit_rate` cases and refine query phrasing/model selection if needed.

## Threshold calibration note (carry forward)

Keep these thresholds as frozen defaults in orchestration until calibration says otherwise:

- Retry threshold trigger when top-1 score `< 0.45` OR weak keyword signal.
- Evidence sufficiency gate requires at least 2 chunks with score `>= 0.50` + obligation signal.

These numbers come from the project SRS/build plan and should be validated against observed retrieval score distribution.
