"""Isolated execution. Docker if available (no network, read-only root, non-root user, limits, hard kill on timeout)."""
import os, shutil, subprocess, sys, time, uuid
from pathlib import Path

IMAGE = "pipelineguard-sandbox"
ROOT = Path(__file__).parent

def docker_ok():
    if not shutil.which("docker"): return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0

def ensure_image():
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        subprocess.run(["docker", "build", "-t", IMAGE, str(ROOT)], check=True)

def run(workdir, cmd, timeout=60):
    """cmd uses {py} as the python placeholder. Returns dict with mode/exit_code/stdout/stderr/seconds."""
    workdir = str(Path(workdir).resolve()); t0 = time.time(); name = f"pg-{uuid.uuid4().hex[:8]}"; use_docker = docker_ok()
    if use_docker:
        ensure_image(); mode = "docker"
        full = ["docker", "run", "--rm", "--name", name, "--network", "none", "--memory", "256m", "--memory-swap", "256m",
                "--cpus", "1", "--pids-limit", "128", "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--tmpfs", "/tmp",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "-v", f"{workdir}:/work", "-w", "/work", IMAGE, "sh", "-c", cmd.format(py="python")]
        kw = {}
    else:
        # Weaker fallback: NO container isolation — only a separate working
        # directory. Never claim container-level security when mode says
        # "process-fallback". Docker path above is the real sandbox.
        mode = "process-fallback (docker unavailable)"
        if os.name == "nt":   # dev/CI on Windows: cmd.exe has no `sh`
            full = cmd.format(py=f'"{sys.executable}"'); kw = {"cwd": workdir, "shell": True}
        else:
            full = ["sh", "-c", cmd.format(py=sys.executable)]; kw = {"cwd": workdir}
    try:
        p = subprocess.run(full, capture_output=True, text=True, timeout=timeout, **kw)
        return dict(mode=mode, exit_code=p.returncode, stdout=p.stdout.strip(), stderr=p.stderr.strip(), seconds=round(time.time() - t0, 2))
    except subprocess.TimeoutExpired:
        if use_docker: subprocess.run(["docker", "kill", name], capture_output=True)   # killing the CLI alone leaves the container running
        return dict(mode=mode, exit_code=124, stdout="", stderr="sandbox timeout", seconds=round(time.time() - t0, 2))
