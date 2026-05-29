from __future__ import annotations

import pytest

from cursor_subagent.daemon.session_manager import SessionManager
from cursor_subagent.models import ResumeSessionRequest, SpawnSessionRequest
from cursor_subagent.providers.base import ProviderSession, RunHandle, StreamEvent
from cursor_subagent.store.db import connect
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore


class FakeProvider:
    provider_id = "cursor-composer"
    _run_counter = 0

    def create_session(self, *, session_id: str, cwd: str, model: str, runtime: str = "local", repo_url=None):
        return ProviderSession(
            session_id=session_id,
            agent_id=f"agent-{session_id}",
            provider_id=self.provider_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            _raw={"count": 0},
        )

    def resume(self, *, session_id: str, agent_id: str, cwd: str, model: str, runtime: str = "local", repo_url=None):
        return ProviderSession(
            session_id=session_id,
            agent_id=agent_id,
            provider_id=self.provider_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            _raw={"count": 0},
        )

    def send(self, session: ProviderSession, message: str) -> RunHandle:
        session._raw["count"] += 1
        FakeProvider._run_counter += 1
        return RunHandle(
            run_id=f"run-{session.session_id}-{FakeProvider._run_counter}",
            _provider=self,
            _session=session,
        )

    def stream(self, handle: RunHandle):
        yield StreamEvent(type="assistant", payload={"text": "ok"})

    def wait(self, handle: RunHandle):
        return "finished", "done"

    def close(self, session: ProviderSession) -> None:
        session._closed = True


@pytest.mark.asyncio
async def test_daemon_recovery_rehydrates_open_session(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    conn = connect(tmp_path / "recovery.db")
    session_store = SessionStore(conn)
    event_store = EventStore(conn)
    fake = FakeProvider()
    monkeypatch.setattr("cursor_subagent.daemon.session_manager.get_provider", lambda _id: fake)

    mgr1 = SessionManager(session_store=session_store, event_store=event_store)
    spawned = await mgr1.spawn(SpawnSessionRequest(task="first", cwd=str(tmp_path)))
    session_id = spawned["session_id"]
    mgr1._live.clear()

    mgr2 = SessionManager(session_store=session_store, event_store=event_store)
    await mgr2.recover_open_sessions()
    assert session_id in mgr2._live

    follow_up = await mgr2.send_message(session_id, "second")
    assert follow_up["result"] == "done"
