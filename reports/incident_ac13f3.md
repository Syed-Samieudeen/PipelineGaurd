# Incident ac13f3 — RECOVERED

**Pipeline:** orders ETL  |  **Injected fault:** `nulls`  |  **Total time:** 4.7s

## Summary (plain English)
The pipeline broke with `NullExplosionError: column 'amount' is 35% null (limit 20%)`. PipelineGuard classified it as 'null_explosion', reproduced it in an isolated sandbox, tested a repair there, scored the risk at 0.475 (REVIEW (human approval)), a human approved it, applied it, and the pipeline is running again. Total time 4.7s.

## Diagnosis
- **Error seen:** `NullExplosionError: column 'amount' is 35% null (limit 20%)`
- **Classified as:** `null_explosion` (confidence 100%)
- **Reproduced in sandbox:** True  — mode: `process-fallback (docker unavailable)`

## Fix
- **Source:** deterministic template (GRANITE_ENABLED not set)
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
Live pipeline recovered. Original input backed up for rollback.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 11:09:03 | +0.0s | WATCH | FAILURE detected (exit 1): NullExplosionError: column 'amount' is 35% null (limit 20%) |
| 11:09:03 | +0.15s | CLASSIFY | Existing classifier (fallback) -> null_explosion (confidence 100%) |
| 11:09:04 | +1.34s | REPRODUCE | sandbox [process-fallback (docker unavailable)] reproduced failure: True |
| 11:09:04 | +1.36s | FIX | repair script generated via deterministic template (GRANITE_ENABLED not set) |
| 11:09:07 | +3.6s | VALIDATE | sandbox run ok; 8/8 checks passed |
| 11:09:07 | +3.6s | RISK | score 0.475 -> REVIEW (human approval) |
| 11:09:07 | +3.6s | APPROVAL | human reviewer approved (simulated via --approve) |
| 11:09:07 | +3.61s | APPLY | fix applied to live input (original backed up to data/backup/orders_ac13f3.csv) |
| 11:09:08 | +4.74s | RECOVER | live pipeline rerun: RECOVERED — OK: processed 500 rows -> C:\Users\acer\Desktop\PipelineGuard-source\data\live\clean_orders.csv |
