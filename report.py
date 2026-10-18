"""Audit trail: JSONL for machines, Markdown report for humans."""
import json, time
from pathlib import Path

class Incident:
    def __init__(self, root, iid, fault):
        self.id, self.fault, self.root = iid, fault, Path(root); self.events = []; self.t0 = time.time()
        (self.root / "logs").mkdir(exist_ok=True); (self.root / "reports").mkdir(exist_ok=True)
    def log(self, stage, msg, **data):
        ev = {"ts": time.strftime("%H:%M:%S"), "t": round(time.time() - self.t0, 2), "incident": self.id, "stage": stage, "msg": msg, **data}
        self.events.append(ev)
        with open(self.root / "logs" / "audit.jsonl", "a") as f: f.write(json.dumps(ev) + "\n")
        import ui; ui.event(ev)
    def write(self, s):
        e = {x["stage"]: x for x in self.events}; g = lambda k, f, d="n/a": e.get(k, {}).get(f, d)
        rows = "\n".join(f"| {x['ts']} | +{x['t']}s | {x['stage']} | {x['msg']} |" for x in self.events)
        fix = s.get("fix_code")
        chk = "\n".join(f"- {'✅' if ok else '❌'} {n}" + (f" — {d}" if d else "") for n, ok, d in s.get("checks", [])) or "n/a"
        d = s.get("diagnosis")
        diag = (f"""## Diagnosis proposal (advisory — not authorization)
- **Model:** {d.get('model','n/a')}
- **Root cause:** {d.get('root_cause','n/a')}
- **Strategy:** `{d.get('repair_strategy','n/a')}` (confidence {d.get('confidence','n/a')}{', ⚠️ LOW — treat as uncertain' if d.get('low_confidence') else ''})
- **Proposed changes:** {'; '.join(d.get('proposed_changes', [])) or 'n/a'}
- **Reasoning:** {d.get('reasoning','n/a')}
- **Risks the model flags:** {'; '.join(d.get('risks', [])) or 'n/a'}

The model cannot authorize changes: the same validation, risk scoring and approval gates apply to every repair regardless of source.
""" if d else "")
        md = f"""# Incident {self.id} — {s['outcome']}

**Pipeline:** orders ETL  |  **Injected fault:** `{self.fault}`  |  **Total time:** {round(time.time()-self.t0,1)}s

## Summary (plain English)
{s['summary']}

## Diagnosis
- **Error seen:** `{s.get('error','n/a')}`
- **Classified as:** `{s.get('label','n/a')}` (confidence {s.get('confidence','n/a')})
- **Reproduced in sandbox:** {s.get('reproduced','n/a')}  — mode: `{s.get('sandbox_mode','n/a')}`

## Fix
- **Source:** {s.get('fix_source','n/a')}
- **Validated in sandbox:** {s.get('validated','n/a')}
- **Changes made:** {'; '.join(s.get('notes', [])) or 'n/a'}
{f"{chr(10)}```python{chr(10)}{fix}{chr(10)}```" if fix else ""}
{diag}

## Validation checks (run on sandbox output)
{chk}

## Risk gate
- **Score:** {s.get('risk','n/a')}  →  **{s.get('decision','n/a')}**
- Breakdown: {s.get('risk_parts','n/a')}

## Outcome
{s['outcome_detail']}

## Timeline
| Time | Elapsed | Stage | Event |
|---|---|---|---|
{rows}
"""
        p = self.root / "reports" / f"incident_{self.id}.md"; p.write_text(md, encoding="utf-8"); return p
