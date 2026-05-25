from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cursor_subagent.daemon.app import create_app
from cursor_subagent.daemon.session_manager import SessionManager
from cursor_subagent.providers.base import ProviderSession, RunHandle, StreamEvent
from cursor_subagent.store.db import connect
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore


class FakeProvider:
    provider_id = "cursor-composer"

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
        return self.create_session(session_id=session_id, cwd=cwd, model=model, runtime=runtime)

    def send(self, session: ProviderSession, message: str) -> RunHandle:
        session._raw["count"] += 1
        return RunHandle(
            run_id=f"run-{session.session_id}-{session._raw['count']}",
            _provider=self,
            _session=session,
        )

    def stream(self, handle: RunHandle):
        yield StreamEvent(type="assistant", payload={"text": "ok"})

    def wait(self, handle: RunHandle):
        return "finished", "done"

    def close(self, session: ProviderSession) -> None:
        session._closed = True


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    fake = FakeProvider()
    monkeypatch.setattr("cursor_subagent.daemon.session_manager.get_provider", lambda _id: fake)
    monkeypatch.setenv("SUBAGENT_DB_PATH", str(tmp_path))
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_wave_create_spawn_and_close(client: TestClient) -> None:
    wave_payload = {
        "wave_id": "wave-auth",
        "goal": "Refactor auth",
        "tasks": [
            {
                "taskId": "T1",
                "goal": "Refactor middleware",
                "ownedPaths": ["src/auth/"],
                "provider": "cursor-composer",
            },
            {
                "taskId": "T2",
                "goal": "Add tests",
                "ownedPaths": ["tests/auth/"],
                "provider": "cursor-composer",
            },
        ],
    }
    resp = client.post("/waves", json=wave_payload)
    assert resp.status_code == 200

    spawn = client.post("/waves/wave-auth/spawn", json={"cwd": "."})
    assert spawn.status_code == 200
    sessions = spawn.json()
    assert len(sessions) == 2

    status = client.get("/waves/wave-auth")
    assert status.status_code == 200
    assert len(status.json()["sessions"]) == 2

    close = client.post("/waves/wave-auth/close")
    assert close.status_code == 200
    assert len(close.json()["closed_sessions"]) == 2
