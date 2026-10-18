"""Always-on watcher. Terminal 1: python monitor.py   Terminal 2: python guard.py inject --fault nulls"""
import hashlib, sys, time
import guard, report, ui

def digest():
    return hashlib.md5(guard.LIVE_IN.read_bytes()).hexdigest() if guard.LIVE_IN.exists() else None

def main():
    if not guard.LIVE_IN.exists(): guard.reset_live()
    ui.banner("LIVE MONITOR"); print(ui.c("36", f"watching {guard.LIVE_IN}  (Ctrl+C to stop)\n"))
    last = None; mon = report.Incident(guard.ROOT, "monitor", "n/a")
    while True:
        try:
            h = digest()
            if h != last:
                time.sleep(0.6)                      # debounce: wait for the writer to finish
                h = digest(); last = h
                code, out, err = guard.run_live()
                if code == 0: mon.log("MONITOR", "pipeline healthy ✔  " + out.split("->")[0].strip())
                else: guard.detect_and_heal(); last = digest()   # a successful fix changes the file; don't re-trigger on it
            time.sleep(1)
        except KeyboardInterrupt: print("\nstopped"); sys.exit(0)

if __name__ == "__main__": main()
