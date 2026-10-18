# Incident 77d06c — RECOVERED

**Pipeline:** orders ETL  |  **Injected fault:** `nulls`  |  **Total time:** 1.4s

## Summary (plain English)
The pipeline broke with `NullExplosionError: column 'amount' is 35% null (limit 20%)`. PipelineGuard classified it as 'null_explosion', reproduced it in an isolated sandbox, tested a repair there, scored the risk at 0.475 (REVIEW (human approval)), a human approved it, applied it, and the pipeline is running again. Total time 1.4s.

## Diagnosis
- **Error seen:** `NullExplosionError: column 'amount' is 35% null (limit 20%)`
- **Classified as:** `null_explosion` (confidence 100%)
- **Reproduced in sandbox:** True  — mode: `docker`

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
| 06:28:32 | +0.0s | WATCH | FAILURE detected (exit 1): NullExplosionError: column 'amount' is 35% null (limit 20%) |
| 06:28:32 | +0.04s | CLASSIFY | Existing classifier (fallback) -> null_explosion (confidence 100%) |
| 06:28:33 | +0.52s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 06:28:33 | +0.52s | FIX | repair script generated via deterministic template (GRANITE_ENABLED not set) |
| 06:28:33 | +1.22s | VALIDATE | sandbox run ok; 8/8 checks passed |
| 06:28:33 | +1.22s | RISK | score 0.475 -> REVIEW (human approval) |
| 06:28:33 | +1.22s | APPROVAL | human reviewer approved (simulated via --approve) |
| 06:28:33 | +1.22s | APPLY | fix applied to live input (original backed up to data/backup/orders_77d06c.csv) |
| 06:28:34 | +1.43s | RECOVER | live pipeline rerun: RECOVERED — OK: processed 500 rows -> /home/linux1/pipelineguard-granite-test/data/live/clean_orders.csv |
