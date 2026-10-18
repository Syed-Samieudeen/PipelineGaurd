"""Sample enterprise pipeline: orders.csv -> validated -> enriched -> clean output."""
import argparse, sys
import pandas as pd

EXPECTED = ["order_id", "customer", "amount", "order_date"]
NULL_LIMIT = 0.20
TAX = 1.18

class SchemaMismatchError(Exception): pass
class TypeMismatchError(Exception): pass
class NullExplosionError(Exception): pass
class DuplicateKeyError(Exception): pass

def run(inp, out):
    df = pd.read_csv(inp)
    missing = [c for c in EXPECTED if c not in df.columns]
    if missing:
        raise SchemaMismatchError(f"missing expected columns {missing}; found columns {list(df.columns)}")
    num = pd.to_numeric(df["amount"], errors="coerce")
    bad = df["amount"].notna() & num.isna()
    if bad.any():
        raise TypeMismatchError(f"column 'amount' has {int(bad.sum())} non-numeric values (e.g. '{df.loc[bad,'amount'].iloc[0]}')")
    for col in ("amount", "customer"):
        frac = df[col].isna().mean()
        if frac > NULL_LIMIT:
            raise NullExplosionError(f"column '{col}' is {frac:.0%} null (limit {NULL_LIMIT:.0%})")
    dups = int(df["order_id"].duplicated().sum())
    if dups:
        raise DuplicateKeyError(f"{dups} duplicate values in primary key 'order_id'")
    df["amount"] = num
    df["amount_with_tax"] = (df["amount"] * TAX).round(2)
    df["order_month"] = pd.to_datetime(df["order_date"]).dt.to_period("M").astype(str)
    df.to_csv(out, index=False)
    return len(df)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--input", required=True); ap.add_argument("--output", required=True)
    a = ap.parse_args()
    try:
        n = run(a.input, a.output)
        print(f"OK: processed {n} rows -> {a.output}")
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
