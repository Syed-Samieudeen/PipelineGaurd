# Incident 5891cf — ESCALATED

**Pipeline:** orders ETL  |  **Injected fault:** `nulls`  |  **Total time:** 1.7s

## Summary (plain English)
The pipeline broke with `NullExplosionError: column 'amount' is 35% null (limit 20%)` ('null_explosion'). A fix was tested in the sandbox and works, but the risk score (0.475) is above the auto-apply limit, so it is waiting for an engineer. Live data was not touched.

## Diagnosis
- **Error seen:** `NullExplosionError: column 'amount' is 35% null (limit 20%)`
- **Classified as:** `n/a` (confidence n/a)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** template (no API key set)
- **Validated in sandbox:** True
- **Changes made:** imputed 175 rows (amount=median, customer=UNKNOWN)

```python
import sys, json, difflib, pandas as pd
EXPECTED = ['order_id', 'customer', 'amount', 'order_date']
src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src); n0 = len(df); affected = 0; notes = []

a = df["amount"].isna() | df["customer"].isna(); affected = int(a.sum())
df["amount"] = df["amount"].fillna(df["amount"].median()); df["customer"] = df["customer"].fillna("UNKNOWN")
notes.append(f"imputed {affected} rows (amount=median, customer=UNKNOWN)")

df.to_csv(dst, index=False)
json.dump({"rows_before": n0, "rows_after": len(df), "affected_rows": int(affected), "notes": notes}, open("repair_stats.json", "w"))

```

## Validation checks (run on sandbox output)
- ✅ Row count preserved — 500/500 rows kept (min allowed 475)
- ✅ All expected columns present — missing: []
- ✅ Primary key unique & non-null
- ✅ No nulls in required fields
- ✅ Amounts numeric and non-negative
- ✅ Typical amount not distorted — median shifted 0.0%
- ✅ No invented rows (ids ⊆ original)
- ✅ Pipeline output matches repaired data — 500 output rows

## Risk gate
- **Score:** 0.475  →  **REVIEW (human approval)**
- Breakdown: {'failure_type': 0.3, 'classifier_uncertainty': 0.0, 'data_touched': 0.175, 'unvalidated_fix': 0.0}

## Outcome
Waiting for human. **Live pipeline NOT modified.** Run: `python guard.py approve 5891cf`

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 04:02:53 | +0.0s | WATCH | FAILURE detected (exit 1): NullExplosionError: column 'amount' is 35% null (limit 20%) |
| 04:02:53 | +0.51s | CLASSIFY | ML model -> null_explosion (confidence 100%) |
| 04:02:54 | +0.97s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 04:02:54 | +0.97s | FIX | repair script generated via template (no API key set) |
| 04:02:54 | +1.69s | VALIDATE | sandbox run ok; 8/8 checks passed |
| 04:02:54 | +1.69s | RISK | score 0.475 -> REVIEW (human approval) |
| 04:02:54 | +1.69s | ESCALATE | waiting for human — python guard.py approve 5891cf |
