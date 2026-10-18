"""Fix generation.

Repair sources (in priority order):
  1. IBM Granite (local LLM, optional)  -> structured JSON *proposal* only. PipelineGuard
     validates the proposal against a per-failure allowlist of repair strategies and then
     executes ITS OWN deterministic template for the chosen strategy. Model output is
     NEVER executed as code and NEVER bypasses validation/risk/approval gates.
  2. Deterministic templates (BODY)     -> always available fallback; the system works
     fully with GRANITE_ENABLED unset or with no model server running.
  3. PG_BAD_FIX=1                       -> deliberately harmful script, for validator tests.

Configuration (environment variables):
  GRANITE_ENABLED   "1"/"true"/"yes"/"on" to enable (default: disabled)
  GRANITE_BASE_URL  OpenAI-compatible endpoint base, e.g. http://127.0.0.1:8080/v1
                    (llama-server default in our docs) or http://127.0.0.1:11434/v1 (Ollama)
  GRANITE_MODEL     model name sent to the server (default: ibm-granite/granite-3.3-2b-instruct;
                    for llama-server this is informational, for Ollama it must be the pulled tag)
  GRANITE_TIMEOUT   seconds to wait for a proposal (default: 30)
  GRANITE_API_KEY   optional bearer token if the server requires one (never logged)

The executed artefact is ALWAYS a repair.py script that is ONLY run inside the sandbox first.
"""
import json, os, re, socket, urllib.error, urllib.request
from etl import EXPECTED

HEAD = f'''import sys, json, difflib, pandas as pd
EXPECTED = {EXPECTED!r}
src, dst = sys.argv[1], sys.argv[2]
df = pd.read_csv(src); n0 = len(df); affected = 0; notes = []
'''
TAIL = '''
df.to_csv(dst, index=False)
json.dump({"rows_before": n0, "rows_after": len(df), "affected_rows": int(affected), "notes": notes}, open("repair_stats.json", "w"))
'''
BODY = {
"schema_mismatch": '''
used = set()
for want in EXPECTED:
    if want not in df.columns:
        pool = [c for c in df.columns if c not in EXPECTED and c not in used]
        m = difflib.get_close_matches(want, pool, n=1, cutoff=0.5)
        if not m: sys.exit(f"cannot map column {want}")
        df = df.rename(columns={m[0]: want}); used.add(m[0]); notes.append(f"renamed {m[0]} -> {want}")
''',
"type_mismatch": '''
s = df["amount"].astype(str).str.replace("$", "", regex=False)
num = pd.to_numeric(s, errors="coerce")
bad = df["amount"].notna() & num.isna()
affected = int((s != df["amount"].astype(str)).sum() + bad.sum())
num = num.fillna(num.median()); df["amount"] = num
notes.append(f"coerced amount to numeric; {int(bad.sum())} unparseable values imputed with median")
''',
"null_explosion": '''
a = df["amount"].isna() | df["customer"].isna(); affected = int(a.sum())
df["amount"] = df["amount"].fillna(df["amount"].median()); df["customer"] = df["customer"].fillna("UNKNOWN")
notes.append(f"imputed {affected} rows (amount=median, customer=UNKNOWN)")
''',
"duplicate_keys": '''
affected = int(df["order_id"].duplicated().sum())
df = df.drop_duplicates(subset="order_id", keep="last"); notes.append(f"dropped {affected} duplicate order_id rows (kept latest)")
''',
}

# --- Restricted repair operations (the ONLY things Granite may propose) -------------
ESCALATE = "escalate_to_human"
ALLOWED_STRATEGIES = {
    "schema_mismatch": ("rename_columns_to_expected",),
    "type_mismatch": ("coerce_amount_numeric",),
    "null_explosion": ("impute_missing_values",),
    "duplicate_keys": ("drop_duplicate_keys",),
}
STRATEGY_BODY = {
    "rename_columns_to_expected": BODY["schema_mismatch"],
    "coerce_amount_numeric": BODY["type_mismatch"],
    "impute_missing_values": BODY["null_explosion"],
    "drop_duplicate_keys": BODY["duplicate_keys"],
}

ETL_RULES = ("amount must be numeric; null fraction <= 20% for amount and customer; "
             "order_id must be unique; output adds amount_with_tax = amount * 1.18 and order_month")
VALIDATION_REQS = ("row count preserved (only known duplicates may go); all expected columns present; "
                   "order_id unique and non-null; no nulls in amount/customer; amounts numeric and non-negative; "
                   "typical amount not distorted (median shift <= 20%); no invented rows; pipeline output matches repaired data")

DEFAULT_MODEL = "ibm-granite/granite-3.3-2b-instruct"
DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
MAX_ERROR_CHARS, MAX_SAMPLE_CHARS = 500, 1200


class GraniteError(Exception):
    """Granite could not deliver a usable proposal. kind: unavailable | invalid | unsafe."""
    def __init__(self, reason, kind="unavailable"):
        super().__init__(reason); self.kind = kind


def granite_enabled():
    return os.getenv("GRANITE_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _config():
    try:
        timeout = float(os.getenv("GRANITE_TIMEOUT", "30"))
    except ValueError:
        timeout = 30.0
    return {"base_url": os.getenv("GRANITE_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            "model": os.getenv("GRANITE_MODEL", DEFAULT_MODEL),
            "timeout": max(0.1, timeout),
            "api_key": os.getenv("GRANITE_API_KEY", "")}


def _build_prompt(label, error, sample_text, columns):
    allowed = ", ".join(ALLOWED_STRATEGIES[label])
    cols = ", ".join(columns) if columns else "unknown (data did not parse)"
    return (f"You are the diagnosis component of PipelineGuard, a data-pipeline safety tool. "
            f"You analyse failures and propose a repair plan. You never execute code; your "
            f"output is a proposal that independent validation and a human approval gate must accept.\n\n"
            f"Failure classification: {label}\n"
            f"Error message: {error[:MAX_ERROR_CHARS]}\n"
            f"Expected schema (columns): {EXPECTED}\n"
            f"Observed columns: {cols}\n"
            f"ETL rules: {ETL_RULES}\n"
            f"Validation requirements the repair must pass: {VALIDATION_REQS}\n"
            f"Safe data sample (first 3 rows, truncated):\n{sample_text[:MAX_SAMPLE_CHARS]}\n\n"
            f"Allowed repair strategies for this failure class: {allowed} "
            f"(or {ESCALATE} if the evidence is insufficient and a human must review).\n"
            f"Reply with ONLY one JSON object, no markdown, with exactly these fields:\n"
            f'{{"root_cause": "...", "repair_strategy": "...", "proposed_changes": ["..."], '
            f'"reasoning": "...", "risks": ["..."], "confidence": 0.0}}\n'
            f"proposed_changes and risks must be short human-readable statements in English, "
            f"never code, SQL or shell commands. confidence is a number between 0 and 1.")


def _call_granite(cfg, prompt):
    """POST to an OpenAI-compatible /chat/completions endpoint. Raises GraniteError on any problem."""
    url = cfg["base_url"] + "/chat/completions"
    payload = json.dumps({"model": cfg["model"], "temperature": 0.0,
                          "messages": [{"role": "system",
                                        "content": "You return strict JSON only."},
                                       {"role": "user", "content": prompt}]}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise GraniteError(f"server returned HTTP {e.code}", "unavailable")
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise GraniteError(f"cannot reach model server at {cfg['base_url']} ({type(e).__name__})", "unavailable")
    try:
        content = json.loads(raw)["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise GraniteError("response is not an OpenAI-style completion", "invalid")
    if not isinstance(content, str) or not content.strip():
        raise GraniteError("empty completion", "invalid")
    return content


def parse_proposal(content):
    """Extract the JSON object from model output (tolerates code fences / stray prose)."""
    s = content.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            raise GraniteError("no JSON object in response", "invalid")
        try:
            obj = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            raise GraniteError("malformed JSON in response", "invalid")
    if not isinstance(obj, dict):
        raise GraniteError("response is not a JSON object", "invalid")
    return obj


def validate_proposal(obj, label):
    """Structural + allowlist validation. Returns a normalised proposal or raises GraniteError."""
    req = ("root_cause", "repair_strategy", "proposed_changes", "reasoning", "risks", "confidence")
    missing = [k for k in req if k not in obj]
    if missing:
        raise GraniteError(f"missing fields: {', '.join(missing)}", "invalid")
    for k in ("root_cause", "reasoning", "repair_strategy"):
        if not isinstance(obj[k], str) or not obj[k].strip():
            raise GraniteError(f"field '{k}' must be a non-empty string", "invalid")
    if not isinstance(obj["proposed_changes"], list) or not all(isinstance(x, str) for x in obj["proposed_changes"]):
        raise GraniteError("field 'proposed_changes' must be a list of strings", "invalid")
    if len(obj["proposed_changes"]) > 25:
        raise GraniteError("too many proposed_changes", "invalid")
    risks = obj["risks"]
    if isinstance(risks, str):
        risks = [risks]
    if not isinstance(risks, list) or not all(isinstance(x, str) for x in risks):
        raise GraniteError("field 'risks' must be a string or list of strings", "invalid")
    conf = obj["confidence"]
    if isinstance(conf, bool):
        raise GraniteError("field 'confidence' must be a number between 0 and 1", "invalid")
    if isinstance(conf, str):
        try: conf = float(conf)
        except ValueError:
            raise GraniteError("field 'confidence' must be a number between 0 and 1", "invalid")
    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        raise GraniteError("field 'confidence' must be between 0 and 1", "invalid")
    strategy = obj["repair_strategy"].strip()
    allowed = ALLOWED_STRATEGIES.get(label, ())
    if strategy != ESCALATE and strategy not in allowed:
        raise GraniteError(f"unsupported strategy '{strategy}' for {label} (allowed: {', '.join(allowed) or ESCALATE})", "unsafe")
    return {"root_cause": obj["root_cause"].strip()[:2000],
            "repair_strategy": strategy,
            "proposed_changes": [c.strip()[:300] for c in obj["proposed_changes"]],
            "reasoning": obj["reasoning"].strip()[:4000],
            "risks": [r.strip()[:300] for r in risks],
            "confidence": round(float(conf), 3)}


def granite_propose(label, error, sample_text, columns=None, cfg=None):
    """Ask Granite for a repair proposal. Raises GraniteError on any failure."""
    cfg = cfg or _config()
    prompt = _build_prompt(label, error, sample_text, columns or [])
    return validate_proposal(parse_proposal(_call_granite(cfg, prompt)), label)


BAD = HEAD + '''
before = len(df); df = df.dropna(); affected = before - len(df); notes.append(f"deleted {affected} rows with missing values")
''' + TAIL


def _template(label, strategy=None):
    body = STRATEGY_BODY[strategy] if strategy in STRATEGY_BODY else BODY[label]
    return HEAD + body + TAIL


def generate_repair(label, error, sample_text, columns=None):
    """Returns dict: {code, source, strategy, diagnosis}.
    code=None  -> escalate (reason in source). diagnosis is set when Granite produced a
    validated proposal (advisory only; never used to bypass gates)."""
    if os.getenv("PG_BAD_FIX") and label in BODY:
        return {"code": BAD, "source": "BAD-FIX (deliberately harmful, for testing the validator)",
                "strategy": None, "diagnosis": None}
    if label not in BODY or label not in ALLOWED_STRATEGIES:
        return {"code": None, "source": f"no safe automatic repair exists for '{label}'",
                "strategy": None, "diagnosis": None}
    if granite_enabled():
        cfg = _config()
        try:
            proposal = granite_propose(label, error, sample_text, columns=columns, cfg=cfg)
        except GraniteError as e:
            diagnosis = None
            why = {"unavailable": f"Granite unavailable: {e}",
                   "invalid": f"Granite response invalid: {e}",
                   "unsafe": f"Granite proposal rejected: {e}"}[e.kind]
            source = f"template ({why})"
        else:
            diagnosis = dict(proposal, model=cfg["model"])
            if proposal["repair_strategy"] == ESCALATE:
                return {"code": None,
                        "source": f"Granite ({cfg['model']}) recommends human review: {proposal['root_cause']}",
                        "strategy": ESCALATE, "diagnosis": diagnosis}
            diagnosis["low_confidence"] = proposal["confidence"] < 0.5
            return {"code": _template(label, proposal["repair_strategy"]),
                    "source": f"Granite ({cfg['model']}) strategy '{proposal['repair_strategy']}' executed via deterministic template",
                    "strategy": proposal["repair_strategy"], "diagnosis": diagnosis}
        return {"code": _template(label), "source": source, "strategy": None, "diagnosis": None}
    return {"code": _template(label), "source": "deterministic template (GRANITE_ENABLED not set)",
            "strategy": None, "diagnosis": None}


def generate(label, error, sample_text):
    """Backwards-compatible interface: Returns (code, source) or (None, reason)."""
    r = generate_repair(label, error, sample_text)
    return r["code"], r["source"]
