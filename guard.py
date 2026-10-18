"""PipelineGuard orchestrator.
  python guard.py train
  python guard.py demo --fault schema|type|nulls|duplicates|corrupt  [--approve]   |  demo --all
  python guard.py inject --fault nulls     # break the live file (used with monitor.py)
  python guard.py reset                    # restore clean live data
  python guard.py pending                  # list fixes waiting for a human
  python guard.py approve <id> [--force]   # human approves a waiting fix"""
import argparse, json, shutil, subprocess, sys, time, uuid
from pathlib import Path
import pandas as pd
import os, faults, classifier, snapml_adapter, sandbox, fixer, risk, report, ui, datafeatures, validate

ROOT = Path(__file__).parent
LIVE, BACKUP, RUNS, PENDING = ROOT / "data" / "live", ROOT / "data" / "backup", ROOT / "runs", ROOT / "data" / "pending"
LIVE_IN, LIVE_OUT = LIVE / "orders.csv", LIVE / "clean_orders.csv"

def run_live():
    p = subprocess.run([sys.executable, str(ROOT / "etl.py"), "--input", str(LIVE_IN), "--output", str(LIVE_OUT)], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

def reset_live():
    for d in (LIVE, BACKUP, PENDING): d.mkdir(parents=True, exist_ok=True)
    faults.generate_clean(LIVE_IN); LIVE_OUT.unlink(missing_ok=True)

def apply_and_recover(inc, iid, ws):
    shutil.copy(LIVE_IN, BACKUP / f"orders_{iid}.csv"); shutil.copy(Path(ws) / "fixed.csv", LIVE_IN)
    inc.log("APPLY", f"fix applied to live input (original backed up to data/backup/orders_{iid}.csv)")
    code, out, err = run_live(); ok = code == 0
    inc.log("RECOVER", f"live pipeline rerun: {'RECOVERED — ' + out if ok else 'STILL FAILING ' + err}")
    return ok, (out if ok else err)

def heal(inc, S, approve_review=False):
    """Everything after a failure has been detected: classify -> reproduce -> fix -> validate -> risk -> apply/escalate."""
    iid = inc.id; feats = datafeatures.profile_features(LIVE_IN)
    prediction = snapml_adapter.predict(
        S["error"],
        feats,
        input_path=LIVE_IN,
        execution_time_ms=S.get("execution_time_ms", 0.0),
    )
    if prediction is None:
        classifier_source = "Existing classifier (fallback)"
        label, conf = classifier.predict(S["error"], feats)
    else:
        classifier_source = "Snap ML"
        label, conf = prediction

    S.update(
        label=label,
        confidence=f"{conf:.0%}",
        classifier_source=classifier_source,
    )
    inc.log(
        "CLASSIFY",
        f"{classifier_source} -> {label} (confidence {conf:.0%})",
        features=feats,
    )
    ws = RUNS / iid; ws.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "etl.py", ws / "etl.py"); shutil.copy(LIVE_IN, ws / "input.csv")
    r = sandbox.run(ws, "{py} etl.py --input input.csv --output out.csv"); S["sandbox_mode"] = r["mode"]
    S["reproduced"] = r["exit_code"] != 0 and r["stderr"].splitlines()[-1] == S["error"]
    inc.log("REPRODUCE", f"sandbox [{r['mode']}] reproduced failure: {S['reproduced']}", exit_code=r["exit_code"])
    sample = pd.read_csv(LIVE_IN, on_bad_lines="skip").head(3).to_string() if feats["parse_ok"] else ""
    obs_cols = list(pd.read_csv(LIVE_IN, nrows=0).columns) if feats["parse_ok"] else []
    fix = fixer.generate_repair(label, S["error"], sample, columns=obs_cols)
    code_txt, src = fix["code"], fix["source"]; S["fix_source"] = src
    if fix.get("diagnosis"):
        S["diagnosis"] = fix["diagnosis"]
        inc.log("DIAGNOSE", f"Granite proposal: {fix['diagnosis']['root_cause']} "
                            f"(strategy {fix['diagnosis']['repair_strategy']}, confidence {fix['diagnosis']['confidence']})",
                proposal=fix["diagnosis"])
    if not code_txt:
        inc.log("FIX", f"no automatic fix: {src}")
        S.update(risk=1.0, decision="HOLD (escalate)", risk_parts="no safe fix available", validated=False, outcome="ESCALATED",
                 summary=f"The pipeline failed with `{S['error']}`. This is a '{label}' failure that PipelineGuard cannot safely repair, so it was escalated to an engineer. Live data was not touched.",
                 outcome_detail="Escalated to on-call engineer. **Live pipeline NOT modified.**")
        inc.log("ESCALATE", "no safe fix — handed to human"); return finish(inc, S)
    S["fix_code"] = code_txt; (ws / "repair.py").write_text(code_txt); inc.log("FIX", f"repair script generated via {src}", source=src)
    r = sandbox.run(ws, "{py} repair.py input.csv fixed.csv && {py} etl.py --input fixed.csv --output out.csv")
    stats = json.loads((ws / "repair_stats.json").read_text()) if (ws / "repair_stats.json").exists() else {}
    ran = r["exit_code"] == 0 and (ws / "out.csv").exists()
    checks = validate.check(ws, stats) if ran else [("Fix runs cleanly in sandbox", False, (r["stderr"] or r["stdout"])[-150:])]
    failed = [n for n, ok, _ in checks if not ok]; S["checks"] = checks; S["validated"] = ran and not failed
    S["notes"] = stats.get("notes", [])
    inc.log("VALIDATE", f"sandbox run {'ok' if ran else 'FAILED'}; {len(checks)-len(failed)}/{len(checks)} checks passed" + (f" — FAILED: {', '.join(failed)}" if failed else ""))
    s, decision, parts = risk.score(label, conf, stats.get("affected_rows", 0), stats.get("rows_before", 1), S["validated"])
    S.update(risk=s, decision=decision, risk_parts=parts); inc.log("RISK", f"score {s} -> {decision}", parts=parts)
    review = decision.startswith("REVIEW")
    if S["validated"] and (decision.startswith("PROCEED") or (review and approve_review)):
        if review: inc.log("APPROVAL", "human reviewer approved (simulated via --approve)")
        ok, _ = apply_and_recover(inc, iid, ws)
        S.update(outcome="RECOVERED" if ok else "FAILED",
                 summary=f"The pipeline broke with `{S['error']}`. PipelineGuard classified it as '{label}', reproduced it in an isolated sandbox, tested a repair there, scored the risk at {s} ({decision}), {'a human approved it, ' if review else ''}applied it, and the pipeline is running again. Total time {round(time.time()-inc.t0,1)}s{'' if review else ' with no human involved'}.",
                 outcome_detail="Live pipeline recovered. Original input backed up for rollback.")
    else:
        if S["validated"]:
            PENDING.mkdir(parents=True, exist_ok=True)
            (PENDING / f"{iid}.json").write_text(json.dumps({"iid": iid, "fault": inc.fault, "ws": str(ws), "decision": decision}))
        rejected = not S["validated"]
        how = f"Fix REJECTED by the validator (see checks above). Inspect runs/{iid}/ and fix manually." if rejected else f"Run: `python guard.py approve {iid}`" if review else f"Needs engineer review: `python guard.py approve {iid} --force` after inspecting runs/{iid}/repair.py"
        S.update(outcome="ESCALATED", summary=(f"The pipeline broke with `{S['error']}` ('{label}'). A fix was proposed and tested in the sandbox, but it FAILED validation ({', '.join(n for n, ok, _ in S['checks'] if not ok)}), so it was rejected and never applied. Live data was not touched." if rejected else f"The pipeline broke with `{S['error']}` ('{label}'). A fix was tested in the sandbox and works, but the risk score ({s}) is above the auto-apply limit, so it is waiting for an engineer. Live data was not touched."),
                 outcome_detail=f"Waiting for human. **Live pipeline NOT modified.** {how}")
        inc.log("ESCALATE", "fix rejected by validator — nothing applied" if rejected else f"waiting for human — python guard.py approve {iid}" + ("" if review else " --force"))
    return finish(inc, S)

def finish(inc, S):
    p = inc.write(S); ui.summary(S, inc, p.relative_to(ROOT)); print(); return S

def detect_and_heal(fault="unknown", approve_review=False):
    """One monitoring check. Returns True if the pipeline is healthy or got healed."""
    started = time.perf_counter()
    code, out, err = run_live()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if code == 0: return True, out
    inc = report.Incident(ROOT, uuid.uuid4().hex[:6], fault)
    S = {"error": err.splitlines()[-1], "execution_time_ms": elapsed_ms}
    inc.log("WATCH", f"FAILURE detected (exit {code}): {S['error']}")
    return heal(inc, S, approve_review)["outcome"] == "RECOVERED", None

def handle(fault, approve_review=False):
    reset_live(); code, out, _ = run_live(); tmp = report.Incident(ROOT, "base", fault); tmp.log("BASELINE", f"pipeline healthy: {out}")
    faults.inject(fault, LIVE_IN); tmp.log("INJECT", f"fault '{fault}' injected into live input")
    detect_and_heal(fault, approve_review)

def approve(iid, force=False):
    p = PENDING / f"{iid}.json"
    if not p.exists(): print(f"no pending incident {iid}"); return
    P = json.loads(p.read_text())
    if P["decision"].startswith("HOLD") and not force:
        print(f"{iid} is HOLD-level (high risk). Inspect runs/{iid}/repair.py, then re-run with --force"); return
    inc = report.Incident(ROOT, iid, P["fault"]); inc.log("APPROVAL", f"engineer approved ({P['decision']}{', forced' if force else ''})")
    ok, out = apply_and_recover(inc, iid, P["ws"])
    with open(ROOT / "reports" / f"incident_{iid}.md", "a") as f:
        f.write(f"\n## Update — approved by engineer ({time.strftime('%H:%M:%S')})\n{'RECOVERED' if ok else 'FAILED'}: {out}\n")
    p.unlink(); print(f"incident {iid}: {'RECOVERED' if ok else 'FAILED'}")

def main(argv=None):
    """CLI entry point (extracted so tests can drive the real flow). Returns an exit code."""
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["demo", "train", "inject", "reset", "pending", "approve"]); ap.add_argument("iid", nargs="?")
    ap.add_argument("--fault", choices=faults.KINDS); ap.add_argument("--all", action="store_true"); ap.add_argument("--approve", action="store_true"); ap.add_argument("--force", action="store_true"); ap.add_argument("--bad-fix", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "train":
        m = classifier.train()
        print(f"samples {m['n_samples']} | test acc {m['test_accuracy']:.1%} | macro-F1 {m['test_macro_f1']:.1%} | 5-fold CV {m['cv5_accuracy']:.1%} | text-only acc {m['text_only_accuracy']:.1%}\nsaved models/metrics.json")
    elif a.cmd == "inject": faults.inject(a.fault or "schema", LIVE_IN); print(f"injected '{a.fault or 'schema'}' into {LIVE_IN}")
    elif a.cmd == "reset": reset_live(); print("live data reset to clean")
    elif a.cmd == "pending":
        PENDING.mkdir(parents=True, exist_ok=True); ps = list(PENDING.glob("*.json"))
        for p in ps: P = json.loads(p.read_text()); print(P["iid"], P["fault"], P["decision"])
        if not ps: print("nothing pending")
    elif a.cmd == "approve": approve(a.iid, a.force)
    else:
        if a.bad_fix: os.environ["PG_BAD_FIX"] = "1"
        ui.banner()
        for f in (faults.KINDS if a.all else [a.fault or "schema"]): print(f"\n===== FAULT: {f} ====="); handle(f, a.approve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
