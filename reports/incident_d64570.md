# Incident d64570 — ESCALATED

**Pipeline:** orders ETL  |  **Injected fault:** `corrupt`  |  **Total time:** 0.9s

## Summary (plain English)
The pipeline failed with `ParserError: Error tokenizing data. C error: Expected 4 fields in line 11, saw 7`. This is a 'runtime_error' failure that PipelineGuard cannot safely repair, so it was escalated to an engineer. Live data was not touched.

## Diagnosis
- **Error seen:** `ParserError: Error tokenizing data. C error: Expected 4 fields in line 11, saw 7`
- **Classified as:** `runtime_error` (confidence 0.83)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** no safe automatic repair exists for 'runtime_error'
- **Validated in sandbox:** False
- **Changes made:** n/a


## Risk gate
- **Score:** 1.0  →  **HOLD (escalate)**
- Breakdown: no safe fix available

## Outcome
Escalated to on-call engineer. **Live pipeline NOT modified.**

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 05:34:10 | +0.24s | BASELINE | pipeline healthy: OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
| 05:34:10 | +0.24s | INJECT | fault 'corrupt' injected into live input |
| 05:34:11 | +0.47s | WATCH | FAILURE detected (exit 1): ParserError: Error tokenizing data. C error: Expected 4 fields in line 11, saw 7 |
| 05:34:11 | +0.47s | CLASSIFY | ML model -> runtime_error (confidence 83%) |
| 05:34:11 | +0.94s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 05:34:11 | +0.94s | FIX | no automatic fix: no safe automatic repair exists for 'runtime_error' |
| 05:34:11 | +0.94s | ESCALATE | handed to human |
