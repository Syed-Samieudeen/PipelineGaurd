# Incident 21973a — ESCALATED

**Pipeline:** orders ETL  |  **Injected fault:** `corrupt`  |  **Total time:** 1.0s

## Summary (plain English)
The pipeline failed with `ParserError: Error tokenizing data. C error: Expected 4 fields in line 11, saw 7`. This is a 'runtime_error' failure that PipelineGuard cannot safely repair, so it was escalated to an engineer. Live data was not touched.

## Diagnosis
- **Error seen:** `ParserError: Error tokenizing data. C error: Expected 4 fields in line 11, saw 7`
- **Classified as:** `n/a` (confidence n/a)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** no safe automatic repair exists for 'runtime_error'
- **Validated in sandbox:** False
- **Changes made:** n/a


## Validation checks (run on sandbox output)
n/a

## Risk gate
- **Score:** 1.0  →  **HOLD (escalate)**
- Breakdown: no safe fix available

## Outcome
Escalated to on-call engineer. **Live pipeline NOT modified.**

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 04:02:57 | +0.0s | WATCH | FAILURE detected (exit 1): ParserError: Error tokenizing data. C error: Expected 4 fields in line 11, saw 7 |
| 04:02:57 | +0.52s | CLASSIFY | ML model -> runtime_error (confidence 100%) |
| 04:02:58 | +0.95s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 04:02:58 | +0.95s | FIX | no automatic fix: no safe automatic repair exists for 'runtime_error' |
| 04:02:58 | +0.95s | ESCALATE | no safe fix — handed to human |
