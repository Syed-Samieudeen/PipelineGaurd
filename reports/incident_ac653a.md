# Incident ac653a — ESCALATED

**Pipeline:** orders ETL  |  **Injected fault:** `nulls`  |  **Total time:** 1.6s

## Summary (plain English)
The pipeline broke with `NullExplosionError: column 'amount' is 35% null (limit 20%)` ('null_explosion'). A fix was tested in the sandbox and works, but the risk score (0.522) is above the auto-apply limit, so it is waiting for an engineer to approve. Live data was not touched.

## Diagnosis
- **Error seen:** `NullExplosionError: column 'amount' is 35% null (limit 20%)`
- **Classified as:** `null_explosion` (confidence 0.84)
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

## Risk gate
- **Score:** 0.522  →  **HOLD (escalate)**
- Breakdown: {'failure_type': 0.3, 'classifier_uncertainty': 0.047, 'data_touched': 0.175, 'unvalidated_fix': 0.0}

## Outcome
Risk too high for auto-apply or simple approval. **Live pipeline NOT modified.** An engineer must review the sandbox-validated repair script before anything is applied.

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
| 05:34:07 | +0.24s | BASELINE | pipeline healthy: OK: processed 500 rows -> /home/linux1/pipelineguard/data/live/clean_orders.csv |
| 05:34:07 | +0.24s | INJECT | fault 'nulls' injected into live input |
| 05:34:07 | +0.47s | WATCH | FAILURE detected (exit 1): NullExplosionError: column 'amount' is 35% null (limit 20%) |
| 05:34:07 | +0.47s | CLASSIFY | ML model -> null_explosion (confidence 84%) |
| 05:34:08 | +0.94s | REPRODUCE | sandbox [docker] reproduced failure: True |
| 05:34:08 | +0.94s | FIX | repair script generated via template (no API key set) |
| 05:34:08 | +1.63s | VALIDATE | fix in sandbox: PASS — OK: processed 500 rows -> out.csv |
| 05:34:08 | +1.63s | RISK | score 0.522 -> HOLD (escalate) |
| 05:34:08 | +1.63s | ESCALATE | waiting for human approval |
