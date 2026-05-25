from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEFAULT_HOST = os.environ.get("SUBAGENT_DAEMON_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("SUBAGENT_DAEMON_PORT", "17340"))


def daemon_url() -> str:
    return os.environ.get("SUBAGENT_DAEMON_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")


def pidfile_path() -> Path:
    base = Path.home() / ".cursor" / "subagents"
    base.mkdir(parents=True, exist_ok=True)
    return base / "daemon.pid"


def is_daemon_running(url: str | None = None) -> bool:
    try:
        resp = httpx.get(f"{url or daemon_url()}/health", timeout=1.0)
        return resp.status_code == 200
    except Exception:
        return False


def start_daemon(*, wait: bool = True, timeout: float = 10.0) -> None:
    if is_daemon_running():
        return
    subprocess.Popen(
        [sys.executable, "-m", "cursor_subagent.daemon_entry"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    if wait:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_daemon_running():
                return
            time.sleep(0.2)
        raise RuntimeError("Daemon failed to start within timeout")


def stop_daemon() -> bool:
    path = pidfile_path()
    if not path.exists():
        return False
    pid = int(path.read_text().strip())
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
    else:
        import signal

        os.kill(pid, signal.SIGTERM)
    path.unlink(missing_ok=True)
    return True


def ensure_daemon() -> str:
    url = daemon_url()
    if not is_daemon_running(url):
        start_daemon()
    return url
