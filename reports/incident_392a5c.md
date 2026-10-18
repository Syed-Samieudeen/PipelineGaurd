# Incident 392a5c — RECOVERED

**Pipeline:** orders ETL  |  **Injected fault:** `type`  |  **Total time:** 1.4s

## Summary (plain English)
The pipeline broke with `TypeMismatchError: column 'amount' has 30 non-numeric values (e.g. 'ERR')`. PipelineGuard classified it as 'type_mismatch', reproduced it in an isolated sandbox, tested a repair there, scored the risk at 0.18 (PROCEED (auto-apply)), applied it, and the pipeline is running again. Total time 1.4s with no human involved.

## Diagnosis
- **Error seen:** `TypeMismatchError: column 'amount' has 30 non-numeric values (e.g. 'ERR')`
- **Classified as:** `type_mismatch` (confidence 100%)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** template (no API key set)
- **Validated in sandbox:** True
- **Changes made:** coerced amount to numeric; 22 unparseable values imputed with median

```python
import sys, json, difflib, pandas as pd
EXPECTED = ['order_id', 'customer', 'amount', 'order_date']
src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src); n0 = len(df); affected = 0; notes = []

s = df["amount"].astype(str).str.replace("$", "", regex=False)
num = pd.to_numeric(s, errors="coerce")
bad = df["amount"].notna() & num.isna()
affected = int((s != df["amount"].astype(str)).sum() + bad.sum())
num = num.fillna(num.median()); df["amount"] = num
notes.append(f"coerced amount to numeric; {int(bad.sum())} unparseable values imputed with median")

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
- **Score:** 0.18  →  **PROCEED (auto-apply)**
- Breakdown: {'failure_type': 0.15, 'classifier_uncertainty': 0.0, 'data_touched': 0.03, 'unvalidated_fix': 0.0}

## Outcome
Live pipeline recovered. Original input backed up for rollback.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 09:06:15 | +0.0s | WATCH | FAILURE detected (exit 1): TypeMismatchError: column 'amount' has 30 non-numeric values (e.g. 'ERR') |
| 09:06:15 | +0.04s | CLASSIFY | ML model -> type_mismatch (confidence 100%) |
| 09:06:16 | +0.49s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 09:06:16 | +0.5s | FIX | repair script generated via template (no API key set) |
| 09:06:16 | +1.2s | VALIDATE | sandbox run ok; 8/8 checks passed |
| 09:06:16 | +1.2s | RISK | score 0.18 -> PROCEED (auto-apply) |
| 09:06:16 | +1.2s | APPLY | fix applied to live input (original backed up to data/backup/orders_392a5c.csv) |
| 09:06:16 | +1.45s | RECOVER | live pipeline rerun: RECOVERED — OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
