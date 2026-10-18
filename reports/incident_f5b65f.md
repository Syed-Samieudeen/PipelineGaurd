# Incident f5b65f — ESCALATED

**Pipeline:** orders ETL  |  **Injected fault:** `nulls`  |  **Total time:** 1.2s

## Summary (plain English)
The pipeline broke with `NullExplosionError: column 'amount' is 35% null (limit 20%)` ('null_explosion'). A fix was proposed and tested in the sandbox, but it FAILED validation (Row count preserved), so it was rejected and never applied. Live data was not touched.

## Diagnosis
- **Error seen:** `NullExplosionError: column 'amount' is 35% null (limit 20%)`
- **Classified as:** `null_explosion` (confidence 100%)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** BAD-FIX (deliberately harmful, for testing the validator)
- **Validated in sandbox:** False
- **Changes made:** deleted 175 rows with missing values

```python
import sys, json, difflib, pandas as pd
EXPECTED = ['order_id', 'customer', 'amount', 'order_date']
src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src); n0 = len(df); affected = 0; notes = []

before = len(df); df = df.dropna(); affected = before - len(df); notes.append(f"deleted {affected} rows with missing values")

df.to_csv(dst, index=False)
json.dump({"rows_before": n0, "rows_after": len(df), "affected_rows": int(affected), "notes": notes}, open("repair_stats.json", "w"))

```

## Validation checks (run on sandbox output)
- ❌ Row count preserved — 325/500 rows kept (min allowed 475)
- ✅ All expected columns present — missing: []
- ✅ Primary key unique & non-null
- ✅ No nulls in required fields
- ✅ Amounts numeric and non-negative
- ✅ Typical amount not distorted — median shifted 0.0%
- ✅ No invented rows (ids ⊆ original)
- ✅ Pipeline output matches repaired data — 325 output rows

## Risk gate
- **Score:** 0.975  →  **HOLD (escalate)**
- Breakdown: {'failure_type': 0.3, 'classifier_uncertainty': 0.0, 'data_touched': 0.175, 'unvalidated_fix': 0.5}

## Outcome
Waiting for human. **Live pipeline NOT modified.** Fix REJECTED by the validator (see checks above). Inspect runs/f5b65f/ and fix manually.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 06:59:14 | +0.0s | WATCH | FAILURE detected (exit 1): NullExplosionError: column 'amount' is 35% null (limit 20%) |
| 06:59:14 | +0.04s | CLASSIFY | ML model -> null_explosion (confidence 100%) |
| 06:59:15 | +0.51s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 06:59:15 | +0.51s | FIX | repair script generated via BAD-FIX (deliberately harmful, for testing the validator) |
| 06:59:15 | +1.21s | VALIDATE | sandbox run ok; 7/8 checks passed — FAILED: Row count preserved |
| 06:59:15 | +1.21s | RISK | score 0.975 -> HOLD (escalate) |
| 06:59:15 | +1.21s | ESCALATE | fix rejected by validator — nothing applied |
