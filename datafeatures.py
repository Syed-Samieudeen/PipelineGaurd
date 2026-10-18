"""Data-profile features: what the broken file itself looks like (independent of the error text)."""
import pandas as pd
from etl import EXPECTED

FEATURES = ["parse_ok", "n_missing_expected", "max_null_frac", "nonnumeric_frac", "dup_key_frac", "empty_file"]

def profile_features(path):
    f = dict.fromkeys(FEATURES, 0.0)
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        f["empty_file"] = 1.0; return f
    except Exception:
        return f                                   # parse_ok stays 0
    f["parse_ok"] = 1.0
    f["n_missing_expected"] = float(len([c for c in EXPECTED if c not in df.columns]))
    if len(df) == 0:
        f["empty_file"] = 1.0; return f
    present = [c for c in ("amount", "customer") if c in df.columns]
    f["max_null_frac"] = max([float(df[c].isna().mean()) for c in present], default=0.0)
    if "amount" in df.columns:
        num = pd.to_numeric(df["amount"], errors="coerce")
        f["nonnumeric_frac"] = float((df["amount"].notna() & num.isna()).mean())
    if "order_id" in df.columns:
        f["dup_key_frac"] = float(df["order_id"].duplicated().mean())
    return f
