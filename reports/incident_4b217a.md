# Incident 4b217a — RECOVERED

**Pipeline:** orders ETL  |  **Injected fault:** `duplicates`  |  **Total time:** 1.3s

## Summary (plain English)
The pipeline broke with `DuplicateKeyError: 15 duplicate values in primary key 'order_id'`. PipelineGuard classified it as 'duplicate_keys', reproduced it in an isolated sandbox, tested a repair there, scored the risk at 0.165 (PROCEED (auto-apply)), applied it, and the pipeline is running again. Total time 1.3s with no human involved.

## Diagnosis
- **Error seen:** `DuplicateKeyError: 15 duplicate values in primary key 'order_id'`
- **Classified as:** `duplicate_keys` (confidence 100%)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** deterministic template (GRANITE_ENABLED not set)
- **Validated in sandbox:** True
- **Changes made:** dropped 15 duplicate order_id rows (kept latest)

```python
import sys, json, difflib, pandas as pd
EXPECTED = ['order_id', 'customer', 'amount', 'order_date']
src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src); n0 = len(df); affected = 0; notes = []

affected = int(df["order_id"].duplicated().sum())
df = df.drop_duplicates(subset="order_id", keep="last"); notes.append(f"dropped {affected} duplicate order_id rows (kept latest)")

df.to_csv(dst, index=False)
json.dump({"rows_before": n0, "rows_after": len(df), "affected_rows": int(affected), "notes": notes}, open("repair_stats.json", "w"))

```


## Validation checks (run on sandbox output)
- ✅ Row count preserved — 500/515 rows kept (min allowed 474)
- ✅ All expected columns present — missing: []
- ✅ Primary key unique & non-null
- ✅ No nulls in required fields
- ✅ Amounts numeric and non-negative
- ✅ Typical amount not distorted — median shifted 0.8%
- ✅ No invented rows (ids ⊆ original)
- ✅ Pipeline output matches repaired data — 500 output rows

## Risk gate
- **Score:** 0.165  →  **PROCEED (auto-apply)**
- Breakdown: {'failure_type': 0.15, 'classifier_uncertainty': 0.0, 'data_touched': 0.015, 'unvalidated_fix': 0.0}

## Outcome
Live pipeline recovered. Original input backed up for rollback.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 06:28:36 | +0.0s | WATCH | FAILURE detected (exit 1): DuplicateKeyError: 15 duplicate values in primary key 'order_id' |
| 06:28:36 | +0.04s | CLASSIFY | Existing classifier (fallback) -> duplicate_keys (confidence 100%) |
| 06:28:37 | +0.46s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 06:28:37 | +0.46s | FIX | repair script generated via deterministic template (GRANITE_ENABLED not set) |
| 06:28:37 | +1.11s | VALIDATE | sandbox run ok; 8/8 checks passed |
| 06:28:37 | +1.11s | RISK | score 0.165 -> PROCEED (auto-apply) |
| 06:28:37 | +1.11s | APPLY | fix applied to live input (original backed up to data/backup/orders_4b217a.csv) |
| 06:28:38 | +1.33s | RECOVER | live pipeline rerun: RECOVERED — OK: processed 500 rows -> /home/linux1/pipelineguard-granite-test/data/live/clean_orders.csv |
