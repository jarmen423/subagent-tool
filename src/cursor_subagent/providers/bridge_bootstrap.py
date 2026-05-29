"""Windows-safe bootstrap for the cursor-sdk local bridge.

``cursor-sdk`` discovers the bridge by reading stderr with ``selectors``,
which fails on Windows pipe handles (``WinError 10038``). When bridge URL and
token env vars are preset, the SDK connects to an existing bridge instead of
launching one. This module starts the bridge with a thread-based stderr reader
and exports ``CURSOR_SDK_BRIDGE_URL`` / ``CURSOR_SDK_BRIDGE_TOKEN``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from cursor_sdk._bridge import READY_LINE_PREFIX, parse_discovery_line
from cursor_sdk._vendor import resolve_bridge_path
from cursor_sdk.errors import CursorSDKError


_BRIDGE_PROCESSES: dict[str, subprocess.Popen[str]] = {}


def _bridge_env_configured() -> bool:
    url = os.environ.get("CURSOR_SDK_BRIDGE_URL")
    token = os.environ.get("CURSOR_SDK_BRIDGE_TOKEN") or os.environ.get(
        "CURSOR_SDK_BRIDGE_AUTH_TOKEN"
    )
    return bool(url and token)


def _endpoint_from_discovery(discovery: dict[str, Any]) -> tuple[str, str]:
    if discovery.get("schemaVersion") != 1:
        raise CursorSDKError(f"Unsupported bridge schema: {discovery.get('schemaVersion')}")
    url = str(discovery.get("url") or "")
    if not url:
        host = str(discovery.get("host") or "")
        port = discovery.get("port")
        if not host or port is None:
            raise CursorSDKError("Bridge discovery payload is missing a URL")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        url = f"http://{host}:{port}"
    auth_token = str(discovery.get("authToken") or "")
    token_file = discovery.get("authTokenFile")
    if not auth_token and token_file:
        auth_token = Path(str(token_file)).read_text(encoding="utf-8")
    auth_token = auth_token.strip()
    if not auth_token:
        raise CursorSDKError("Bridge discovery payload is missing an auth token")
    return url, auth_token


def _read_discovery_threaded(
    process: subprocess.Popen[str],
    *,
    timeout: float,
) -> dict[str, Any]:
    if process.stderr is None:
        raise CursorSDKError("Bridge process stderr is unavailable")

    holder: dict[str, Any] = {}
    stderr_lines: list[str] = []

    def _reader() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line)
            discovery = parse_discovery_line(line)
            if discovery is not None:
                holder["discovery"] = dict(discovery)
                return

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "discovery" in holder:
            return holder["discovery"]
        exit_code = process.poll()
        if exit_code is not None:
            break
        time.sleep(0.05)

    if "discovery" in holder:
        return holder["discovery"]

    detail = "".join(stderr_lines)
    exit_code = process.poll()
    if exit_code is not None:
        raise CursorSDKError(
            f"Bridge exited before discovery with status {exit_code}: {detail}"
        )
    raise CursorSDKError(f"Timed out waiting for bridge discovery: {detail}")


def ensure_sdk_bridge(workspace: str | os.PathLike[str], *, timeout: float = 30.0) -> None:
    """Ensure ``CURSOR_SDK_BRIDGE_*`` env vars point at a running local bridge."""
    if _bridge_env_configured():
        return

    workspace_path = str(Path(workspace).resolve())
    if workspace_path in _BRIDGE_PROCESSES and _BRIDGE_PROCESSES[workspace_path].poll() is None:
        return

    argv = [resolve_bridge_path(), "--workspace", workspace_path]
    process = subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )
    try:
        discovery = _read_discovery_threaded(process, timeout=timeout)
        url, auth_token = _endpoint_from_discovery(discovery)
        os.environ["CURSOR_SDK_BRIDGE_URL"] = url
        os.environ["CURSOR_SDK_BRIDGE_TOKEN"] = auth_token
        _BRIDGE_PROCESSES[workspace_path] = process
    except Exception:
        if process.poll() is None:
            process.terminate()
        raise


def needs_bridge_bootstrap() -> bool:
    """Return True when this platform should pre-launch the SDK bridge."""
    return sys.platform == "win32"
