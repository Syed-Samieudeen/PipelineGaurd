# Incident 4a118a — RECOVERED

**Pipeline:** orders ETL  |  **Injected fault:** `duplicates`  |  **Total time:** 1.8s

## Summary (plain English)
The pipeline broke with `DuplicateKeyError: 15 duplicate values in primary key 'order_id'`. PipelineGuard classified it as 'duplicate_keys', reproduced it in an isolated sandbox, tested a repair there, scored the risk at 0.223 (PROCEED (auto-apply)), applied it, and the pipeline is running again. Total time 1.8s with no human involved.

## Diagnosis
- **Error seen:** `DuplicateKeyError: 15 duplicate values in primary key 'order_id'`
- **Classified as:** `duplicate_keys` (confidence 0.81)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** template (no API key set)
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

## Risk gate
- **Score:** 0.223  →  **PROCEED (auto-apply)**
- Breakdown: {'failure_type': 0.15, 'classifier_uncertainty': 0.058, 'data_touched': 0.015, 'unvalidated_fix': 0.0}

## Outcome
Live pipeline recovered. Output: `clean_orders.csv`. Original input backed up for rollback.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 05:34:09 | +0.24s | BASELINE | pipeline healthy: OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
| 05:34:09 | +0.24s | INJECT | fault 'duplicates' injected into live input |
| 05:34:09 | +0.47s | WATCH | FAILURE detected (exit 1): DuplicateKeyError: 15 duplicate values in primary key 'order_id' |
| 05:34:09 | +0.47s | CLASSIFY | ML model -> duplicate_keys (confidence 81%) |
| 05:34:09 | +0.89s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 05:34:09 | +0.9s | FIX | repair script generated via template (no API key set) |
| 05:34:10 | +1.59s | VALIDATE | fix in sandbox: PASS — OK: processed 500 rows -> out.csv |
| 05:34:10 | +1.59s | RISK | score 0.223 -> PROCEED (auto-apply) |
| 05:34:10 | +1.59s | APPLY | fix applied to live input (original backed up to data/backup/orders_4a118a.csv) |
| 05:34:10 | +1.82s | RECOVER | live pipeline rerun: RECOVERED — OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
