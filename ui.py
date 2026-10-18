"""Terminal dashboard helpers (stdlib only, ANSI colours)."""
import os, sys
try:  # Windows dev consoles may use cp1252; LinuxONE already runs UTF-8
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(errors="replace")
except Exception: pass
ON = sys.stdout.isatty() or os.getenv("PG_COLOR") == "1"
def c(code, t): return f"\033[{code}m{t}\033[0m" if ON else t
COL = {"BASELINE": "90", "INJECT": "35", "MONITOR": "36;1", "WATCH": "31;1", "CLASSIFY": "36", "REPRODUCE": "33", "FIX": "34",
       "VALIDATE": "32", "RISK": "33;1", "APPROVAL": "35;1", "APPLY": "32", "RECOVER": "32;1", "ESCALATE": "31;1"}
def event(ev):
    t = "[%5ss]" % ev["t"]; print(f"{c('90', t)} {c(COL.get(ev['stage'], '0'), ev['stage'].ljust(10))} {ev['msg']}")
def box(title, lines, col="36"):
    w = max([len(title)] + [len(l) for l in lines]) + 2
    print(c(col, "┌" + "─" * w + "┐")); print(c(col, "│") + " " + c(col + ";1", title.ljust(w - 1)) + c(col, "│"))
    print(c(col, "├" + "─" * w + "┤"))
    for l in lines: print(c(col, "│") + " " + l.ljust(w - 1) + c(col, "│"))
    print(c(col, "└" + "─" * w + "┘"))
def banner(sub=""): box("PipelineGuard — self-healing data pipelines", ["IBM LinuxONE  |  Predictive AI + GenAI + sandbox" + (f"  |  {sub}" if sub else "")])
def summary(S, inc, rpath):
    col = "32" if S["outcome"] == "RECOVERED" else "31"
    box(f"INCIDENT {inc.id}: {S['outcome']}", [
        f"Failure     : {S.get('label','?')} ({S.get('confidence','?')})", f"Sandbox     : {S.get('sandbox_mode','?')}",
        f"Risk        : {S.get('risk','?')} -> {S.get('decision','?')}", f"Time        : {round(__import__('time').time()-inc.t0,1)}s",
        f"Report      : {rpath}"], col)
