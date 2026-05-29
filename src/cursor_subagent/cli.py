from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx
import typer
import websockets

from cursor_subagent.bus.startup import (
    bus_status,
    gateway_ws_url,
    start_bus,
    stop_bus,
)
from cursor_subagent.daemon.startup import (
    daemon_url,
    ensure_daemon,
    is_daemon_running,
    start_daemon,
    stop_daemon,
)
from cursor_subagent.models import CreateWaveRequest, ResumeSessionRequest, WaveTask
from cursor_subagent.output import emit_error, emit_json

app = typer.Typer(add_completion=False, no_args_is_help=True)
daemon_app = typer.Typer(help="Manage the cursor-subagent daemon")
bus_app = typer.Typer(help="Manage NATS + Rust gateway")
wave_app = typer.Typer(help="Wave execution orchestration")
app.add_typer(daemon_app, name="daemon")
app.add_typer(bus_app, name="bus")
app.add_typer(wave_app, name="wave")


def _client() -> httpx.Client:
    return httpx.Client(base_url=ensure_daemon(), timeout=600.0)


def _request_json(method: str, path: str, **kwargs) -> dict | list:
    with _client() as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            emit_error(str(detail), code=1 if resp.status_code >= 500 else 2)
        if not resp.content:
            return {}
        return resp.json()


def _session_ws_url(session_id: str) -> str:
    return f"{gateway_ws_url().rstrip('/')}/sessions/{session_id}/stream"


@daemon_app.command("start")
def daemon_start() -> None:
    """Start the Python REST daemon."""
    start_daemon()
    typer.echo(f"Daemon running at {daemon_url()}")


@daemon_app.command("stop")
def daemon_stop() -> None:
    """Stop the Python REST daemon."""
    if stop_daemon():
        typer.echo("Daemon stopped")
    else:
        typer.echo("Daemon was not running")


@daemon_app.command("status")
def daemon_status(json_out: bool = typer.Option(False, "--json")) -> None:
    """Check daemon health."""
    data = {"running": is_daemon_running(), "url": daemon_url()}
    if json_out:
        emit_json(data)
    else:
        typer.echo(json.dumps(data))


@bus_app.command("start")
def bus_start() -> None:
    """Start nats-server and subagent-gateway."""
    start_bus()
    typer.echo(json.dumps(bus_status(), indent=2))


@bus_app.command("stop")
def bus_stop() -> None:
    """Stop nats-server and subagent-gateway."""
    stop_bus()
    typer.echo("Bus stopped")


@bus_app.command("status")
def bus_status_cmd(json_out: bool = typer.Option(False, "--json")) -> None:
    """Check NATS and gateway health."""
    data = bus_status()
    if json_out:
        emit_json(data)
    else:
        typer.echo(json.dumps(data, indent=2))


@app.command("spawn")
def spawn(
    task: str = typer.Option(..., "--task"),
    cwd: str = typer.Option(".", "--cwd"),
    provider: str = typer.Option("cursor-composer", "--provider"),
    model: str = typer.Option("composer-2.5", "--model"),
    runtime: str = typer.Option("local", "--runtime"),
    repo_url: Optional[str] = typer.Option(None, "--repo"),
    persist: bool = typer.Option(False, "--persist"),
    from_template: Optional[str] = typer.Option(None, "--from-template"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Spawn a stateful sub-agent session."""
    payload = {
        "task": task,
        "cwd": str(Path(cwd).resolve()),
        "provider": provider,
        "model": model,
        "runtime": runtime,
        "repo_url": repo_url,
        "persist": persist,
        "from_template": from_template,
    }
    result = _request_json("POST", "/sessions", json=payload)
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command("resume")
def resume_cmd(
    agent_id: str = typer.Option(..., "--agent-id"),
    cwd: str = typer.Option(".", "--cwd"),
    provider: str = typer.Option("cursor-composer", "--provider"),
    model: str = typer.Option("composer-2.5", "--model"),
    runtime: str = typer.Option("local", "--runtime"),
    repo_url: Optional[str] = typer.Option(None, "--repo"),
    persist: bool = typer.Option(False, "--persist"),
    task: Optional[str] = typer.Option(None, "--task"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Re-register a session from an existing Cursor agent ID."""
    payload = ResumeSessionRequest(
        agent_id=agent_id,
        cwd=str(Path(cwd).resolve()),
        provider=provider,
        model=model,
        runtime=runtime,
        repo_url=repo_url,
        persist=persist,
        task=task,
    ).model_dump()
    result = _request_json("POST", "/sessions/resume", json=payload)
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command("send")
def send_cmd(
    session_id: str = typer.Argument(...),
    message: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
    watch: bool = typer.Option(False, "--watch"),
) -> None:
    """Send a follow-up message to an open session."""
    if watch:
        _watch_and_send(session_id, message, json_out=json_out)
        return
    result = _request_json("POST", f"/sessions/{session_id}/messages", json={"message": message})
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


def _watch_and_send(session_id: str, message: str, *, json_out: bool) -> None:
    import asyncio

    async def _run() -> dict:
        ws_url = _session_ws_url(session_id)
        result: dict = {}

        async def _listen() -> None:
            nonlocal result
            async with websockets.connect(ws_url) as ws:
                while True:
                    raw = await ws.recv()
                    event = json.loads(raw)
                    if json_out:
                        print(json.dumps(event, default=str))
                    if event.get("event") == "run_complete":
                        result = event
                        break

        listen_task = asyncio.create_task(_listen())
        with httpx.Client(base_url=ensure_daemon(), timeout=600.0) as client:
            resp = client.post(f"/sessions/{session_id}/messages", json={"message": message})
            resp.raise_for_status()
            result = resp.json()
        await listen_task
        return result

    final = asyncio.run(_run())
    if json_out:
        emit_json(final)


@app.command("watch")
def watch_cmd(
    session_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Stream live session events from the Rust gateway over WebSocket."""
    import asyncio

    async def _run() -> None:
        ws_url = _session_ws_url(session_id)
        async with websockets.connect(ws_url) as ws:
            while True:
                raw = await ws.recv()
                if json_out:
                    print(raw)
                else:
                    typer.echo(raw)

    asyncio.run(_run())


@app.command("status")
def status_cmd(
    session_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Get session status."""
    result = _request_json("GET", f"/sessions/{session_id}")
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command("events")
def events_cmd(
    session_id: str = typer.Argument(...),
    since: Optional[str] = typer.Option(None, "--since"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Replay stored session events."""
    params = {"since": since} if since else None
    result = _request_json("GET", f"/sessions/{session_id}/events", params=params)
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command("cancel")
def cancel_cmd(
    session_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Cancel the active run."""
    result = _request_json("POST", f"/sessions/{session_id}/cancel")
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command("close")
def close_cmd(
    session_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Close a session and dispose the provider handle."""
    result = _request_json("DELETE", f"/sessions/{session_id}")
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@app.command("list")
def list_cmd(
    cwd: Optional[str] = typer.Option(None, "--cwd"),
    wave: Optional[str] = typer.Option(None, "--wave"),
    status: Optional[str] = typer.Option(None, "--status"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List sessions."""
    params = {}
    if cwd:
        params["cwd"] = str(Path(cwd).resolve())
    if wave:
        params["wave_id"] = wave
    if status:
        params["status"] = status
    result = _request_json("GET", "/sessions", params=params or None)
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@wave_app.command("create")
def wave_create(
    wave_id: str = typer.Option(..., "--wave-id"),
    goal: str = typer.Option(..., "--goal"),
    tasks: Path = typer.Option(..., "--tasks", exists=True, dir_okay=False),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Register a wave and task registry."""
    raw = json.loads(tasks.read_text(encoding="utf-8"))
    task_items = raw.get("tasks", raw if isinstance(raw, list) else [])
    wave_tasks = [WaveTask.model_validate(t) for t in task_items]
    payload = CreateWaveRequest(wave_id=wave_id, goal=goal, tasks=wave_tasks).model_dump()
    result = _request_json("POST", "/waves", json=payload)
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@wave_app.command("spawn")
def wave_spawn(
    wave_id: str = typer.Argument(...),
    task_ids: Optional[str] = typer.Option(None, "--task-ids"),
    cwd: str = typer.Option(".", "--cwd"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Spawn one session per wave task."""
    payload = {
        "cwd": str(Path(cwd).resolve()),
        "task_ids": [t.strip() for t in task_ids.split(",")] if task_ids else None,
    }
    result = _request_json("POST", f"/waves/{wave_id}/spawn", json=payload)
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@wave_app.command("status")
def wave_status(
    wave_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Get wave status and linked sessions."""
    result = _request_json("GET", f"/waves/{wave_id}")
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


@wave_app.command("close")
def wave_close(
    wave_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Close all sessions in a wave."""
    result = _request_json("POST", f"/waves/{wave_id}/close")
    if json_out:
        emit_json(result)
    else:
        typer.echo(json.dumps(result, indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
