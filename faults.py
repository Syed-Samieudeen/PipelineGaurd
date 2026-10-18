"""Generate clean data and inject realistic faults."""
import random
import numpy as np, pandas as pd

CUSTOMERS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Stark", "Wayne", "Wonka"]
KINDS = ["schema", "type", "nulls", "duplicates", "corrupt"]

def generate_clean(path, n=500, seed=7):
    rng = np.random.default_rng(seed)
    pd.DataFrame({
        "order_id": range(1, n + 1),
        "customer": rng.choice(CUSTOMERS, n),
        "amount": rng.uniform(10, 500, n).round(2),
        "order_date": pd.date_range("2026-01-01", periods=n, freq="6h").strftime("%Y-%m-%d"),
    }).to_csv(path, index=False)

def inject(kind, path, seed=1):
    rnd = random.Random(seed)
    if kind == "corrupt":
        lines = open(path).read().splitlines()
        lines.insert(10, "1,2,3,4,5,6,7")
        open(path, "w").write("\n".join(lines) + "\n"); return
    df = pd.read_csv(path)
    if kind == "schema":
        df = df.rename(columns={"customer": "customer_name", "amount": "order_amount"})
        df["discount_code"] = "NONE"
    elif kind == "type":
        df["amount"] = df["amount"].astype(object)
        for i in rnd.sample(range(len(df)), int(len(df) * 0.06)):
            df.at[i, "amount"] = rnd.choice(["twelve", "$45.50", "ERR", "abc"])
    elif kind == "nulls":
        df.loc[df.sample(frac=0.35, random_state=seed).index, "amount"] = None
    elif kind == "duplicates":
        df = pd.concat([df, df.sample(15, random_state=seed)], ignore_index=True)
    else:
        raise ValueError(kind)
    df.to_csv(path, index=False)
