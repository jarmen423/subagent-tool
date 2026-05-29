from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

import pytest

from cursor_subagent.daemon.session_manager import SessionManager
from cursor_subagent.models import ResumeSessionRequest, SpawnSessionRequest
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
        count = len(session._raw["messages"])
        return RunHandle(
            run_id=f"run-{session.session_id}-{count}",
            _provider=self,
            _session=session,
        )

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


@pytest.mark.asyncio
async def test_persist_session_not_purged_on_close(manager) -> None:
    mgr, fake, tmp_path = manager
    first = await mgr.spawn(
        SpawnSessionRequest(task="persist me", cwd=str(tmp_path), persist=True)
    )
    session_id = first["session_id"]
    closed = await mgr.close(session_id)
    assert closed["purged"] is False
    assert mgr.session_store.get_session(session_id) is not None


@pytest.mark.asyncio
async def test_non_persist_session_purged_on_close(manager) -> None:
    mgr, fake, tmp_path = manager
    first = await mgr.spawn(
        SpawnSessionRequest(task="temp task", cwd=str(tmp_path), persist=False)
    )
    session_id = first["session_id"]
    closed = await mgr.close(session_id)
    assert closed["purged"] is True
    assert mgr.session_store.get_session(session_id) is None


@pytest.mark.asyncio
async def test_resume_registers_new_session(manager) -> None:
    mgr, fake, tmp_path = manager
    result = await mgr.resume(
        ResumeSessionRequest(
            agent_id="agent-manual-1",
            cwd=str(tmp_path),
            task="resume task",
        )
    )
    assert result["agent_id"] == "agent-manual-1"
    assert result["session_id"].startswith("ses_")


@pytest.mark.asyncio
async def test_spawn_from_template(manager) -> None:
    mgr, fake, tmp_path = manager
    first = await mgr.spawn(
        SpawnSessionRequest(task="template task", cwd=str(tmp_path), persist=True)
    )
    template_id = first["session_id"]
    await mgr.close(template_id)

    second = await mgr.spawn(
        SpawnSessionRequest(
            task="rerun",
            cwd=str(tmp_path),
            from_template=template_id,
        )
    )
    assert second["session_id"] != template_id
    assert len(fake.messages) == 2
