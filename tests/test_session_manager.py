from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import pytest

from cursor_subagent.daemon.session_manager import SessionManager
from cursor_subagent.models import SpawnSessionRequest
from cursor_subagent.providers.base import ProviderSession, RunHandle, StreamEvent
from cursor_subagent.store.db import connect
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore


@dataclass
class FakeProvider:
    provider_id: str = "cursor-composer"
    messages: list[str] = field(default_factory=list)

    def create_session(self, *, session_id: str, cwd: str, model: str, runtime: str = "local", repo_url=None):
        return ProviderSession(
            session_id=session_id,
            agent_id=f"agent-{session_id}",
            provider_id=self.provider_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            _raw={"messages": self.messages},
        )

    def resume(self, *, session_id: str, agent_id: str, cwd: str, model: str, runtime: str = "local", repo_url=None):
        return self.create_session(session_id=session_id, cwd=cwd, model=model, runtime=runtime)

    def send(self, session: ProviderSession, message: str) -> RunHandle:
        session._raw["messages"].append(message)
        return RunHandle(run_id=f"run-{len(session._raw['messages'])}", _provider=self, _session=session)

    def stream(self, handle: RunHandle) -> Iterator[StreamEvent]:
        yield StreamEvent(type="assistant", payload={"text": f"echo:{handle._session._raw['messages'][-1]}"})

    def wait(self, handle: RunHandle) -> tuple[str, str]:
        return "finished", f"done:{handle._session._raw['messages'][-1]}"

    def cancel(self, handle: RunHandle) -> None:
        return None

    def close(self, session: ProviderSession) -> None:
        session._closed = True


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch, tmp_path):
    conn = connect(tmp_path / "mgr.db")
    session_store = SessionStore(conn)
    event_store = EventStore(conn)
    fake = FakeProvider()
    monkeypatch.setattr("cursor_subagent.daemon.session_manager.get_provider", lambda _id: fake)
    mgr = SessionManager(session_store=session_store, event_store=event_store)
    yield mgr, fake, tmp_path
    conn.close()


@pytest.mark.asyncio
async def test_spawn_and_send_multi_turn(manager) -> None:
    mgr, fake, tmp_path = manager
    first = await mgr.spawn(
        SpawnSessionRequest(task="first task", cwd=str(tmp_path))
    )
    session_id = first["session_id"]
    second = await mgr.send_message(session_id, "second task")
    assert "done:second task" in (second.get("result") or "")
    assert len(fake.messages) == 2
    closed = await mgr.close(session_id)
    assert closed["status"] == "closed"
