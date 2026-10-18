"""Safety gate: decide proceed / review / hold."""
BASE = {"schema_mismatch": 0.05, "type_mismatch": 0.15, "duplicate_keys": 0.15, "null_explosion": 0.30, "runtime_error": 0.90}

def score(label, confidence, affected_rows, total_rows, validated):
    frac = affected_rows / max(total_rows, 1)
    parts = {"failure_type": BASE.get(label, 0.9), "classifier_uncertainty": round(0.3 * (1 - confidence), 3),
             "data_touched": round(0.5 * frac, 3), "unvalidated_fix": 0.0 if validated else 0.5}
    s = round(min(1.0, sum(parts.values())), 3)
    decision = "PROCEED (auto-apply)" if s < 0.25 else "REVIEW (human approval)" if s < 0.50 else "HOLD (escalate)"
    return s, decision, parts
