from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from cursor_subagent.models import (
    EventRecord,
    RunRecord,
    RunStatus,
    SessionRecord,
    SessionStatus,
    SpawnSessionRequest,
    utc_now_iso,
)
from cursor_subagent.providers import get_provider
from cursor_subagent.providers.base import ProviderSession, RunHandle
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore


@dataclass
class LiveSession:
    record: SessionRecord
    provider_session: ProviderSession
    active_run: RunHandle | None = None


@dataclass
class SessionManager:
    session_store: SessionStore
    event_store: EventStore
    _live: dict[str, LiveSession] = field(default_factory=dict)
    _subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def _to_response(self, record: SessionRecord, run: RunRecord | None = None) -> dict[str, Any]:
        return {
            "session_id": record.id,
            "agent_id": record.agent_id,
            "run_id": run.id if run else None,
            "status": record.status.value,
            "result": run.result if run else None,
            "cwd": record.cwd,
            "model": record.model,
            "provider": record.provider,
            "wave_id": record.wave_id,
            "task_id": record.task_id,
            "stream_url": f"/sessions/{record.id}/stream",
        }

    async def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[session_id].append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subs = self._subscribers.get(session_id, [])
        if queue in subs:
            subs.remove(queue)

    async def _broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(session_id, [])):
            await queue.put(event)

    async def recover_open_sessions(self) -> None:
        for record in self.session_store.list_open_sessions():
            if record.id in self._live or not record.agent_id:
                continue
            provider = get_provider(record.provider)
            provider_session = provider.resume(
                session_id=record.id,
                agent_id=record.agent_id,
                cwd=record.cwd,
                model=record.model,
                runtime=record.runtime,
                repo_url=record.repo_url,
            )
            self._live[record.id] = LiveSession(record=record, provider_session=provider_session)

    async def spawn(self, req: SpawnSessionRequest) -> dict[str, Any]:
        session_id = self.session_store.new_session_id()
        provider = get_provider(req.provider)
        provider_session = provider.create_session(
            session_id=session_id,
            cwd=req.cwd,
            model=req.model,
            runtime=req.runtime,
            repo_url=req.repo_url,
        )
        record = SessionRecord(
            id=session_id,
            provider=req.provider,
            agent_id=provider_session.agent_id,
            cwd=req.cwd,
            model=req.model,
            runtime=req.runtime,
            status=SessionStatus.RUNNING,
            wave_id=req.wave_id,
            task_id=req.task_id,
            task_summary=req.task[:500],
            persist=req.persist,
            repo_url=req.repo_url,
        )
        self.session_store.create_session(record)
        self._live[session_id] = LiveSession(record=record, provider_session=provider_session)
        return await self.send_message(session_id, req.task)

    async def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        live = self._get_live(session_id)
        provider = get_provider(live.record.provider)
        live.record.status = SessionStatus.RUNNING
        self.session_store.update_session(session_id, status=SessionStatus.RUNNING.value)

        handle = provider.send(live.provider_session, message)
        live.active_run = handle
        run = RunRecord(id=handle.run_id, session_id=session_id, status=RunStatus.RUNNING)
        self.session_store.create_run(run)

        loop = asyncio.get_running_loop()

        def _stream_and_wait() -> tuple[str, str]:
            for event in provider.stream(handle):
                payload = {"type": event.type, "payload": event.payload}
                self.event_store.append(
                    EventRecord(
                        session_id=session_id,
                        run_id=handle.run_id,
                        type=event.type,
                        payload=event.payload,
                    )
                )
                asyncio.run_coroutine_threadsafe(
                    self._broadcast(
                        session_id,
                        {"event": "stream", "run_id": handle.run_id, **payload},
                    ),
                    loop,
                )
            status, result = provider.wait(handle)
            return status, result

        status, result = await loop.run_in_executor(None, _stream_and_wait)

        run_status = RunStatus.FINISHED if status == "finished" else RunStatus.ERROR
        if status == "cancelled":
            run_status = RunStatus.CANCELLED
        self.session_store.update_run(handle.run_id, status=run_status, result=result)

        session_status = SessionStatus.IDLE if run_status == RunStatus.FINISHED else SessionStatus.OPEN
        self.session_store.update_session(session_id, status=session_status.value)
        live.record.status = session_status
        live.active_run = None

        latest = self.session_store.get_latest_run(session_id)
        await self._broadcast(
            session_id,
            {
                "event": "run_complete",
                "run_id": handle.run_id,
                "status": run_status.value,
                "result": result,
            },
        )
        return self._to_response(live.record, latest)

    async def cancel(self, session_id: str) -> dict[str, Any]:
        live = self._get_live(session_id)
        if not live.active_run:
            return {"session_id": session_id, "status": "idle", "cancelled": False}
        provider = get_provider(live.record.provider)
        provider.cancel(live.active_run)
        return {"session_id": session_id, "status": "cancelling", "cancelled": True}

    async def close(self, session_id: str) -> dict[str, Any]:
        live = self._live.pop(session_id, None)
        record = self.session_store.get_session(session_id)
        if not record:
            raise KeyError(session_id)
        if live:
            provider = get_provider(live.record.provider)
            provider.close(live.provider_session)
        purge = not record.persist and not record.wave_id
        self.session_store.close_session(session_id, purge=purge)
        await self._broadcast(session_id, {"event": "session_closed", "session_id": session_id})
        return {"session_id": session_id, "status": "closed", "purged": purge}

    def get_session(self, session_id: str) -> dict[str, Any]:
        record = self.session_store.get_session(session_id)
        if not record:
            raise KeyError(session_id)
        run = self.session_store.get_latest_run(session_id)
        return self._to_response(record, run)

    def list_sessions(
        self,
        *,
        cwd: str | None = None,
        wave_id: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[dict[str, Any]]:
        records = self.session_store.list_sessions(cwd=cwd, wave_id=wave_id, status=status)
        return [self._to_response(r, self.session_store.get_latest_run(r.id)) for r in records]

    def _get_live(self, session_id: str) -> LiveSession:
        live = self._live.get(session_id)
        if live:
            return live
        record = self.session_store.get_session(session_id)
        if not record or not record.agent_id:
            raise KeyError(session_id)
        provider = get_provider(record.provider)
        provider_session = provider.resume(
            session_id=record.id,
            agent_id=record.agent_id,
            cwd=record.cwd,
            model=record.model,
            runtime=record.runtime,
            repo_url=record.repo_url,
        )
        live = LiveSession(record=record, provider_session=provider_session)
        self._live[session_id] = live
        return live
