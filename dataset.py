"""Build a training set by ACTUALLY running the pipeline on randomly broken data and recording the real failures."""
import random, tempfile
from pathlib import Path
import numpy as np, pandas as pd
import etl, faults
from datafeatures import profile_features

ALIASES = {"customer": ["customer_name", "cust", "client", "CustomerID", "buyer"],
           "amount": ["order_amount", "amt", "total", "price_usd", "value"],
           "order_id": ["id", "orderid", "order_no"], "order_date": ["date", "created_at", "orderdate"]}
JUNK = ["twelve", "$45.50", "ERR", "abc", "--", "n.a.", "1,2", "TBD", "ten"]
OPAQUE = ["RuntimeError: transform step 'enrich_orders' failed", "Exception: pipeline execution aborted", "ValueError: validation failed",
          "Error: job exited with status 1", "RuntimeError: task failed after 0 retries", "Exception: unexpected error in stage 2"]
GENERIC = ["Exception", "ValueError", "RuntimeError", "PipelineError", "Error"]

def _break(kind, path, rnd, rng):
    if kind == "runtime":
        sub = rnd.choice(["fields", "empty", "binary", "missing"])
        if sub == "fields":
            lines = open(path).read().splitlines(); lines.insert(rnd.randint(2, len(lines) - 1), ",".join("x" * rnd.randint(5, 9)))
            open(path, "w").write("\n".join(lines) + "\n")
        elif sub == "empty": open(path, "w").write("")
        elif sub == "binary": open(path, "wb").write(bytes(rng.integers(128, 256, 400, dtype=np.uint8)))
        else: Path(path).unlink()
        return
    df = pd.read_csv(path)
    if kind == "schema":
        cols = rnd.sample(list(ALIASES), rnd.randint(1, 2))
        if rnd.random() < 0.3: df = df.drop(columns=[cols[0]])
        else: df = df.rename(columns={c: rnd.choice(ALIASES[c]) for c in cols})
        if rnd.random() < 0.5: df["extra_col"] = "x"
    elif kind == "type":
        df["amount"] = df["amount"].astype(object)
        for i in rnd.sample(range(len(df)), max(1, int(len(df) * rnd.uniform(0.01, 0.3)))): df.at[i, "amount"] = rnd.choice(JUNK)
    elif kind == "nulls":
        col = rnd.choice(["amount", "customer"])
        df.loc[df.sample(frac=rnd.uniform(0.21, 0.7), random_state=rnd.randint(0, 999)).index, col] = None
    elif kind == "duplicates":
        df = pd.concat([df, df.sample(max(1, int(len(df) * rnd.uniform(0.01, 0.1))), random_state=rnd.randint(0, 999))], ignore_index=True)
    df.to_csv(path, index=False)

def generate(n=600, seed=0):
    rnd, rng = random.Random(seed), np.random.default_rng(seed); rows = []
    kinds = {"schema": "schema_mismatch", "type": "type_mismatch", "nulls": "null_explosion", "duplicates": "duplicate_keys", "runtime": "runtime_error"}
    with tempfile.TemporaryDirectory() as d:
        for i in range(n):
            kind = list(kinds)[i % len(kinds)]; p = Path(d) / "in.csv"
            faults.generate_clean(p, n=rnd.randint(100, 1500), seed=rnd.randint(0, 10**6)); _break(kind, p, rnd, rng)
            try: etl.run(str(p), str(Path(d) / "out.csv"))
            except Exception as e:
                text = f"{type(e).__name__}: {e}"
                r = rnd.random()
                if r < 0.35: text = rnd.choice(OPAQUE)                                   # vague error: only the data profile can tell
                elif r < 0.65 and ":" in text: text = f"{rnd.choice(GENERIC)}:{text.split(':', 1)[1]}"   # hide the class name
                rows.append({"error_text": text, "label": kinds[kind], **profile_features(p)})
    return pd.DataFrame(rows)
