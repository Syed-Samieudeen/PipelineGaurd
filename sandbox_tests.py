"""Security self-test: proves the sandbox contains hostile/buggy code. Screenshot the table for the demo."""
import tempfile, sandbox
from pathlib import Path

TESTS = [  # (name, code, timeout, passes_if)
 ("Network is blocked", "import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)", 15, "fail"),
 ("Cannot write outside /work", "open('/etc/pg_test', 'w').write('x')", 15, "fail"),
 ("CAN write inside /work (sanity)", "open('ok.txt', 'w').write('x')", 15, "ok"),
 ("Runs as non-root", "import os, sys\nsys.exit(1 if os.getuid() == 0 else 0)", 15, "ok"),
 ("Infinite loop is killed", "while True: pass", 5, "timeout"),
 ("Memory hog is killed (256MB cap)", "x = bytearray(1024 * 1024 * 1024)\nx[::4096] = b'1' * len(x[::4096])", 20, "fail"),
 ("Fork bomb is capped (128 pids)", "import os, sys, time\nfor i in range(400):\n    try:\n        if os.fork() == 0:\n            time.sleep(3); os._exit(0)\n    except OSError:\n        sys.exit(1)\nsys.exit(0)", 20, "fail"),
]

def main():
    ws = Path(tempfile.mkdtemp()); results = []; mode = "?"
    for name, code, to, want in TESTS:
        (ws / "t.py").write_text(code); r = sandbox.run(ws, "{py} t.py", timeout=to); mode = r["mode"]
        ok = {"fail": r["exit_code"] != 0, "ok": r["exit_code"] == 0, "timeout": r["exit_code"] == 124}[want]
        results.append((name, ok, r["exit_code"]))
    print(f"\nSandbox mode: {mode}\n" + "-" * 58)
    for name, ok, code in results: print(f"{'PASS' if ok else 'FAIL'}  {name:<36} (exit {code})")
    print("-" * 58 + f"\n{sum(o for _, o, _ in results)}/{len(results)} passed")

if __name__ == "__main__": main()
