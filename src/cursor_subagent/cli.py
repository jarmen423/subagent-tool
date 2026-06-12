from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import httpx
import typer
import websockets

from cursor_subagent.env import load_env_for_cwd, load_env_files

load_env_files()

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
from cursor_subagent.models import (
    CreateAutomationRequest,
    CreateWaveRequest,
    ResumeSessionRequest,
    UpdateAutomationRequest,
    WaveTask,
)
from cursor_subagent.output import emit_error, emit_json

app = typer.Typer(add_completion=False, no_args_is_help=True)
daemon_app = typer.Typer(help="Manage the cursor-subagent daemon")
bus_app = typer.Typer(help="Manage NATS + Rust gateway")
wave_app = typer.Typer(help="Wave execution orchestration")
automation_app = typer.Typer(help="Manage project-local automations")
app.add_typer(daemon_app, name="daemon")
app.add_typer(bus_app, name="bus")
app.add_typer(wave_app, name="wave")
app.add_typer(automation_app, name="automation")


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


def _emit_cli_result(data: dict | list, *, json_out: bool) -> None:
    if json_out:
        emit_json(data)
    else:
        typer.echo(json.dumps(data, indent=2, default=str))


def _parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        emit_error("--payload must be a JSON object", code=2)
    return data


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
    resolved_cwd = str(Path(cwd).resolve())
    load_env_for_cwd(resolved_cwd)
    payload = {
        "task": task,
        "cwd": resolved_cwd,
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
    resolved_cwd = str(Path(cwd).resolve())
    load_env_for_cwd(resolved_cwd)
    payload = ResumeSessionRequest(
        agent_id=agent_id,
        cwd=resolved_cwd,
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
        connected = asyncio.Event()

        async def _listen() -> None:
            nonlocal result
            async with websockets.connect(ws_url) as ws:
                connected.set()
                while True:
                    raw = await ws.recv()
                    event = json.loads(raw)
                    if json_out:
                        print(json.dumps(event, default=str))
                    if event.get("event") == "run_complete":
                        result = event
                        break

        listen_task = asyncio.create_task(_listen())
        try:
            # The gateway must be subscribed before the REST call starts;
            # otherwise fast runs can publish run_complete before watch is live.
            await asyncio.wait_for(connected.wait(), timeout=10.0)
            async with httpx.AsyncClient(base_url=ensure_daemon(), timeout=600.0) as client:
                resp = await client.post(
                    f"/sessions/{session_id}/messages",
                    json={"message": message},
                )
                resp.raise_for_status()
                result = resp.json()
            await listen_task
        except Exception:
            listen_task.cancel()
            raise
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


@automation_app.command("create")
def automation_create(
    name: str = typer.Option(..., "--name"),
    task: str = typer.Option(..., "--task"),
    cwd: str = typer.Option(".", "--cwd"),
    cron: Optional[str] = typer.Option(None, "--cron"),
    webhook: bool = typer.Option(False, "--webhook"),
    provider: str = typer.Option("cursor-composer", "--provider"),
    model: str = typer.Option("composer-2.5", "--model"),
    runtime: str = typer.Option("local", "--runtime"),
    repo_url: Optional[str] = typer.Option(None, "--repo"),
    recent_run_count: int = typer.Option(5, "--recent-run-count"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Create a local automation definition."""
    resolved_cwd = str(Path(cwd).resolve())
    payload = CreateAutomationRequest(
        name=name,
        task=task,
        cwd=resolved_cwd,
        cron_expression=cron,
        webhook_enabled=webhook,
        provider=provider,
        model=model,
        runtime=runtime,
        repo_url=repo_url,
        recent_run_count=recent_run_count,
    ).model_dump()
    result = _request_json("POST", "/automations", json=payload)
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("list")
def automation_list(
    status: Optional[str] = typer.Option(None, "--status"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List local automations."""
    params = {"status": status} if status else None
    result = _request_json("GET", "/automations", params=params)
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("show")
def automation_show(
    automation_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show one automation definition."""
    result = _request_json("GET", f"/automations/{automation_id}")
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("pause")
def automation_pause(
    automation_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Pause cron, webhook, and manual triggers for an automation."""
    result = _request_json(
        "PATCH",
        f"/automations/{automation_id}",
        json=UpdateAutomationRequest(status="paused").model_dump(exclude_unset=True),
    )
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("resume")
def automation_resume(
    automation_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Resume a paused automation."""
    result = _request_json(
        "PATCH",
        f"/automations/{automation_id}",
        json=UpdateAutomationRequest(status="enabled").model_dump(exclude_unset=True),
    )
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("delete")
def automation_delete(
    automation_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Delete an automation and its local run history."""
    result = _request_json("DELETE", f"/automations/{automation_id}")
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("trigger")
def automation_trigger(
    automation_id: str = typer.Argument(...),
    payload: Optional[str] = typer.Option(None, "--payload"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run an automation immediately with an optional JSON payload."""
    result = _request_json(
        "POST",
        f"/automations/{automation_id}/trigger",
        json={"payload": _parse_payload(payload)},
    )
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("runs")
def automation_runs(
    automation_id: str = typer.Argument(...),
    limit: int = typer.Option(50, "--limit"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List recorded automation runs."""
    result = _request_json("GET", f"/automations/{automation_id}/runs", params={"limit": limit})
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("history")
def automation_history(
    automation_id: str = typer.Argument(...),
    full: bool = typer.Option(False, "--full"),
    limit: int = typer.Option(50, "--limit"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show rolling memory, optionally with full run records."""
    result = _request_json(
        "GET",
        f"/automations/{automation_id}/history",
        params={"full": full, "limit": limit},
    )
    _emit_cli_result(result, json_out=json_out)


@automation_app.command("rotate-secret")
def automation_rotate_secret(
    automation_id: str = typer.Argument(...),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Generate a new bearer secret for an automation webhook."""
    result = _request_json("POST", f"/automations/{automation_id}/rotate-secret")
    _emit_cli_result(result, json_out=json_out)


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
    resolved_cwd = str(Path(cwd).resolve())
    load_env_for_cwd(resolved_cwd)
    payload = {
        "cwd": resolved_cwd,
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
