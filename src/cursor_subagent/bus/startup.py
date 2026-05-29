from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEFAULT_NATS_PORT = int(os.environ.get("SUBAGENT_NATS_PORT", "4222"))
DEFAULT_GATEWAY_HOST = os.environ.get("SUBAGENT_GATEWAY_HOST", "127.0.0.1")
DEFAULT_GATEWAY_PORT = int(os.environ.get("SUBAGENT_GATEWAY_PORT", "17341"))


def subagents_dir() -> Path:
    base = Path.home() / ".cursor" / "subagents"
    base.mkdir(parents=True, exist_ok=True)
    return base


def nats_pidfile() -> Path:
    return subagents_dir() / "nats.pid"


def gateway_pidfile() -> Path:
    return subagents_dir() / "gateway.pid"


def nats_url() -> str:
    return os.environ.get("SUBAGENT_NATS_URL", f"nats://127.0.0.1:{DEFAULT_NATS_PORT}")


def gateway_http_url() -> str:
    return os.environ.get(
        "SUBAGENT_GATEWAY_HTTP_URL",
        f"http://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}",
    )


def gateway_ws_url() -> str:
    return os.environ.get(
        "SUBAGENT_GATEWAY_URL",
        f"ws://{DEFAULT_GATEWAY_HOST}:{DEFAULT_GATEWAY_PORT}",
    )


def nats_server_bin() -> Path | None:
    env = os.environ.get("SUBAGENT_NATS_SERVER_BIN")
    if env:
        path = Path(env)
        return path if path.exists() else None
    local = subagents_dir() / "bin" / ("nats-server.exe" if sys.platform == "win32" else "nats-server")
    if local.exists():
        return local
    return shutil.which("nats-server") and Path(shutil.which("nats-server"))  # type: ignore[arg-type]


def gateway_bin() -> Path | None:
    env = os.environ.get("SUBAGENT_GATEWAY_BIN")
    if env:
        path = Path(env)
        return path if path.exists() else None
    name = "subagent-gateway.exe" if sys.platform == "win32" else "subagent-gateway"
    candidates = [
        Path(__file__).resolve().parents[3] / "bus" / "target" / "release" / name,
        subagents_dir() / "bin" / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return shutil.which("subagent-gateway") and Path(shutil.which("subagent-gateway"))  # type: ignore[arg-type]


def is_nats_running() -> bool:
    try:
        import socket

        with socket.create_connection(("127.0.0.1", DEFAULT_NATS_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def is_gateway_running() -> bool:
    try:
        resp = httpx.get(f"{gateway_http_url()}/health", timeout=1.0)
        return resp.status_code == 200
    except Exception:
        return False


def start_nats_server(*, wait: bool = True, timeout: float = 10.0) -> None:
    if is_nats_running():
        return
    binary = nats_server_bin()
    if binary is None:
        raise RuntimeError(
            "nats-server not found. Run scripts/install-nats-server.ps1 or set SUBAGENT_NATS_SERVER_BIN"
        )
    log_path = subagents_dir() / "nats-server.log"
    proc = subprocess.Popen(
        [str(binary), "-p", str(DEFAULT_NATS_PORT), "-l", str(log_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    nats_pidfile().write_text(str(proc.pid))
    if wait:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_nats_running():
                return
            time.sleep(0.2)
        raise RuntimeError("nats-server failed to start within timeout")


def stop_nats_server() -> bool:
    path = nats_pidfile()
    if not path.exists():
        return False
    pid = int(path.read_text().strip())
    _kill_pid(pid)
    path.unlink(missing_ok=True)
    return True


def start_gateway(*, wait: bool = True, timeout: float = 10.0) -> None:
    if is_gateway_running():
        return
    binary = gateway_bin()
    if binary is None:
        raise RuntimeError(
            "subagent-gateway not found. Build with: cargo build --release -p subagent-gateway"
        )
    env = os.environ.copy()
    env.setdefault("SUBAGENT_NATS_URL", nats_url())
    env.setdefault("SUBAGENT_GATEWAY_HOST", DEFAULT_GATEWAY_HOST)
    env.setdefault("SUBAGENT_GATEWAY_PORT", str(DEFAULT_GATEWAY_PORT))
    proc = subprocess.Popen(
        [str(binary)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    gateway_pidfile().write_text(str(proc.pid))
    if wait:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if is_gateway_running():
                return
            time.sleep(0.2)
        raise RuntimeError("subagent-gateway failed to start within timeout")


def stop_gateway() -> bool:
    path = gateway_pidfile()
    if not path.exists():
        return False
    pid = int(path.read_text().strip())
    _kill_pid(pid)
    path.unlink(missing_ok=True)
    return True


def start_bus(*, wait: bool = True) -> None:
    start_nats_server(wait=wait)
    start_gateway(wait=wait)


def stop_bus() -> None:
    stop_gateway()
    stop_nats_server()


def bus_status() -> dict[str, object]:
    return {
        "nats_running": is_nats_running(),
        "gateway_running": is_gateway_running(),
        "nats_url": nats_url(),
        "gateway_http_url": gateway_http_url(),
        "gateway_ws_url": gateway_ws_url(),
    }


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
    else:
        import signal

        os.kill(pid, signal.SIGTERM)
