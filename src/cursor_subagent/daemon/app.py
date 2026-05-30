"""FastAPI REST surface for the cursor-subagent daemon.

Session streaming is published to NATS and consumed through the Rust gateway
WebSocket bridge; this module intentionally exposes REST only.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from cursor_subagent.bus.nats_publisher import create_publisher
from cursor_subagent.daemon.session_manager import SessionManager
from cursor_subagent.daemon.startup import DEFAULT_HOST, DEFAULT_PORT, pidfile_path
from cursor_subagent.models import (
    CreateWaveRequest,
    ResumeSessionRequest,
    SendMessageRequest,
    SessionStatus,
    SpawnSessionRequest,
    WaveRecord,
    WaveSpawnRequest,
    WaveStatus,
)
from cursor_subagent.store.db import connect
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore
from cursor_subagent.store.waves import WaveStore


def create_app() -> FastAPI:
    conn = connect()
    session_store = SessionStore(conn)
    event_store = EventStore(conn)
    wave_store = WaveStore(conn)
    manager = SessionManager(session_store=session_store, event_store=event_store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pidfile_path().write_text(str(os.getpid()))
        manager.publisher = await create_publisher()
        await manager.recover_open_sessions()
        try:
            yield
        finally:
            await manager.publisher.close()
            pidfile_path().unlink(missing_ok=True)

    app = FastAPI(title="cursor-subagentd", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/shutdown")
    async def shutdown() -> dict[str, str]:
        """Gracefully stop the daemon process."""

        def _exit_soon() -> None:
            if sys.platform == "win32":
                os.kill(os.getpid(), signal.SIGTERM)
            else:
                os.kill(os.getpid(), signal.SIGINT)

        asyncio.get_running_loop().call_later(0.2, _exit_soon)
        return {"status": "shutting_down"}

    @app.post("/sessions")
    async def spawn_session(req: SpawnSessionRequest) -> JSONResponse:
        try:
            result = await manager.spawn(req)
            return JSONResponse(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/sessions/resume")
    async def resume_session(req: ResumeSessionRequest) -> JSONResponse:
        try:
            result = await manager.resume(req)
            return JSONResponse(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/sessions")
    async def list_sessions(
        cwd: str | None = None,
        wave_id: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        st = SessionStatus(status) if status else None
        return manager.list_sessions(cwd=cwd, wave_id=wave_id, status=st)

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        try:
            return manager.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.post("/sessions/{session_id}/messages")
    async def send_message(session_id: str, req: SendMessageRequest) -> JSONResponse:
        try:
            result = await manager.send_message(session_id, req.message)
            return JSONResponse(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/sessions/{session_id}/events")
    async def list_events(session_id: str, since: str | None = None) -> list[dict]:
        events = event_store.list_events(session_id, since_run_id=since)
        return [e.model_dump() for e in events]

    @app.post("/sessions/{session_id}/cancel")
    async def cancel_session(session_id: str) -> dict:
        try:
            return await manager.cancel(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.delete("/sessions/{session_id}")
    async def close_session(session_id: str) -> dict:
        try:
            return await manager.close(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc

    @app.post("/waves")
    async def create_wave(req: CreateWaveRequest) -> dict:
        wave = WaveRecord(id=req.wave_id, goal=req.goal, tasks=req.tasks, status=WaveStatus.OPEN)
        wave_store.create_wave(wave)
        return wave.model_dump()

    @app.get("/waves/{wave_id}")
    async def get_wave(wave_id: str) -> dict:
        wave = wave_store.get_wave(wave_id)
        if not wave:
            raise HTTPException(status_code=404, detail="Wave not found")
        sessions = manager.list_sessions(wave_id=wave_id)
        return {"wave": wave.model_dump(), "sessions": sessions}

    @app.post("/waves/{wave_id}/spawn")
    async def spawn_wave(wave_id: str, req: WaveSpawnRequest) -> list[dict]:
        wave = wave_store.get_wave(wave_id)
        if not wave:
            raise HTTPException(status_code=404, detail="Wave not found")
        tasks = wave.tasks
        if req.task_ids:
            tasks = [t for t in tasks if t.task_id in req.task_ids]
        wave_store.update_status(wave_id, WaveStatus.RUNNING)
        results: list[dict] = []
        for task in tasks:
            spawn_req = SpawnSessionRequest(
                task=task.goal,
                cwd=task.cwd or req.cwd,
                provider=task.provider,
                model=task.model,
                wave_id=wave_id,
                task_id=task.task_id,
            )
            results.append(await manager.spawn(spawn_req))
        return results

    @app.post("/waves/{wave_id}/close")
    async def close_wave(wave_id: str) -> dict:
        sessions = manager.list_sessions(wave_id=wave_id)
        closed: list[str] = []
        for session in sessions:
            if session["status"] != SessionStatus.CLOSED.value:
                await manager.close(session["session_id"])
                closed.append(session["session_id"])
        wave_store.update_status(wave_id, WaveStatus.CLOSED)
        return {"wave_id": wave_id, "closed_sessions": closed}

    app.state.manager = manager
    app.state.event_store = event_store
    app.state.wave_store = wave_store
    return app


def run_server() -> None:
    import uvicorn

    uvicorn.run(create_app(), host=DEFAULT_HOST, port=DEFAULT_PORT, log_level="info")
