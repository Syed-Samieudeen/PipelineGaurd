"""Fix validation: does the repaired data still look like the original, minus the problem? Runs on the sandbox's output files."""
import pandas as pd
from etl import EXPECTED

MAX_EXTRA_ROW_LOSS = 0.05      # beyond rows that are legitimately duplicates
MAX_MEDIAN_SHIFT = 0.20        # imputation must not drag the typical amount by >20%

def check(ws, stats):
    """Returns list of (name, passed, detail)."""
    R = []; add = lambda n, ok, d="": R.append((n, bool(ok), d))
    try:
        orig = pd.read_csv(ws / "input.csv"); fixed = pd.read_csv(ws / "fixed.csv"); out = pd.read_csv(ws / "out.csv")
    except Exception as e:
        return [("Output files readable", False, f"{type(e).__name__}: {e}")]
    n0, n1 = len(orig), len(fixed)
    dups = int(orig["order_id"].duplicated().sum()) if "order_id" in orig.columns else 0
    floor = n0 - dups - MAX_EXTRA_ROW_LOSS * n0
    add("Row count preserved", n1 >= floor, f"{n1}/{n0} rows kept (min allowed {int(floor)})")
    add("All expected columns present", all(c in fixed.columns for c in EXPECTED), f"missing: {[c for c in EXPECTED if c not in fixed.columns]}")
    if not all(c in fixed.columns for c in EXPECTED): return R
    add("Primary key unique & non-null", fixed["order_id"].is_unique and fixed["order_id"].notna().all())
    add("No nulls in required fields", not fixed[["amount", "customer"]].isna().any().any())
    amt = pd.to_numeric(fixed["amount"], errors="coerce")
    add("Amounts numeric and non-negative", amt.notna().all() and (amt >= 0).all())
    o = pd.to_numeric(orig.get("amount", pd.Series(dtype=float)).astype(str).str.replace("$", "", regex=False), errors="coerce").dropna()
    if len(o) and amt.notna().all():
        shift = abs(amt.median() - o.median()) / max(abs(o.median()), 1e-9)
        add("Typical amount not distorted", shift <= MAX_MEDIAN_SHIFT, f"median shifted {shift:.1%}")
    add("No invented rows (ids ⊆ original)", set(fixed["order_id"]) <= set(orig["order_id"]) if "order_id" in orig.columns else True)
    add("Pipeline output matches repaired data", len(out) == n1 and "amount_with_tax" in out.columns, f"{len(out)} output rows")
    return R
