# Incident 0f3251 — ESCALATED

**Pipeline:** orders ETL  |  **Injected fault:** `type`  |  **Total time:** 1.7s

## Summary (plain English)
The pipeline broke with `TypeMismatchError: column 'amount' has 30 non-numeric values (e.g. 'ERR')` ('type_mismatch'). A fix was tested in the sandbox and works, but the risk score (0.268) is above the auto-apply limit, so it is waiting for an engineer to approve. Live data was not touched.

## Diagnosis
- **Error seen:** `TypeMismatchError: column 'amount' has 30 non-numeric values (e.g. 'ERR')`
- **Classified as:** `type_mismatch` (confidence 0.71)
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

## Risk gate
- **Score:** 0.268  →  **REVIEW (human approval)**
- Breakdown: {'failure_type': 0.15, 'classifier_uncertainty': 0.088, 'data_touched': 0.03, 'unvalidated_fix': 0.0}

## Outcome
Waiting for human approval. **Live pipeline NOT modified.** Re-run with `--approve` to simulate approval.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 05:34:05 | +0.24s | BASELINE | pipeline healthy: OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
| 05:34:05 | +0.24s | INJECT | fault 'type' injected into live input |
| 05:34:06 | +0.47s | WATCH | FAILURE detected (exit 1): TypeMismatchError: column 'amount' has 30 non-numeric values (e.g. 'ERR') |
| 05:34:06 | +0.48s | CLASSIFY | ML model -> type_mismatch (confidence 71%) |
| 05:34:06 | +0.94s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 05:34:06 | +0.94s | FIX | repair script generated via template (no API key set) |
| 05:34:07 | +1.67s | VALIDATE | fix in sandbox: PASS — OK: processed 500 rows -> out.csv |
| 05:34:07 | +1.67s | RISK | score 0.268 -> REVIEW (human approval) |
| 05:34:07 | +1.67s | ESCALATE | waiting for human approval |
