# Incident ddc7f5 — RECOVERED

**Pipeline:** orders ETL  |  **Injected fault:** `schema`  |  **Total time:** 1.9s

## Summary (plain English)
The pipeline broke with `SchemaMismatchError: missing expected columns ['customer', 'amount']; found columns ['order_id', 'customer_name', 'order_amount', 'order_date', 'discount_code']`. PipelineGuard classified it as 'schema_mismatch', reproduced it in an isolated sandbox, tested a repair there, scored the risk at 0.091 (PROCEED (auto-apply)), applied it, and the pipeline is running again. Total time 1.9s with no human involved.

## Diagnosis
- **Error seen:** `SchemaMismatchError: missing expected columns ['customer', 'amount']; found columns ['order_id', 'customer_name', 'order_amount', 'order_date', 'discount_code']`
- **Classified as:** `schema_mismatch` (confidence 0.86)
- **Reproduced in sandbox:** True  — mode: `docker`

## Fix
- **Source:** template (no API key set)
- **Validated in sandbox:** True
- **Changes made:** renamed customer_name -> customer; renamed order_amount -> amount

```python
import sys, json, difflib, pandas as pd
EXPECTED = ['order_id', 'customer', 'amount', 'order_date']
src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src); n0 = len(df); affected = 0; notes = []

used = set()
for want in EXPECTED:
    if want not in df.columns:
        pool = [c for c in df.columns if c not in EXPECTED and c not in used]
        m = difflib.get_close_matches(want, pool, n=1, cutoff=0.5)
        if not m: sys.exit(f"cannot map column {want}")
        df = df.rename(columns={m[0]: want}); used.add(m[0]); notes.append(f"renamed {m[0]} -> {want}")

df.to_csv(dst, index=False)
json.dump({"rows_before": n0, "rows_after": len(df), "affected_rows": int(affected), "notes": notes}, open("repair_stats.json", "w"))

```

## Risk gate
- **Score:** 0.091  →  **PROCEED (auto-apply)**
- Breakdown: {'failure_type': 0.05, 'classifier_uncertainty': 0.041, 'data_touched': 0.0, 'unvalidated_fix': 0.0}

## Outcome
Live pipeline recovered. Output: `clean_orders.csv`. Original input backed up for rollback.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 05:33:51 | +0.23s | BASELINE | pipeline healthy: OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
| 05:33:51 | +0.24s | INJECT | fault 'schema' injected into live input |
| 05:33:51 | +0.46s | WATCH | FAILURE detected (exit 1): SchemaMismatchError: missing expected columns ['customer', 'amount']; found columns ['order_id', 'customer_name', 'order_amount', 'order_date', 'discount_code'] |
| 05:33:51 | +0.46s | CLASSIFY | ML model -> schema_mismatch (confidence 86%) |
| 05:33:52 | +0.93s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 05:33:52 | +0.93s | FIX | repair script generated via template (no API key set) |
| 05:33:52 | +1.62s | VALIDATE | fix in sandbox: PASS — OK: processed 500 rows -> out.csv |
| 05:33:52 | +1.62s | RISK | score 0.091 -> PROCEED (auto-apply) |
| 05:33:52 | +1.62s | APPLY | fix applied to live input (original backed up to data/backup/orders_ddc7f5.csv) |
| 05:33:53 | +1.85s | RECOVER | live pipeline rerun: RECOVERED — OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
