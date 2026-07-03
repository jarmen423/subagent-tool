from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from cursor_subagent.daemon.app import create_app
from cursor_subagent.providers.base import ProviderSession, RunHandle, StreamEvent


@dataclass
class FakeProvider:
    provider_id: str = "cursor-composer"
    count: int = 0

    def create_session(self, *, session_id: str, cwd: str, model: str, runtime: str = "local", repo_url=None):
        return ProviderSession(
            session_id=session_id,
            agent_id=f"agent-{session_id}",
            provider_id=self.provider_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            _raw={},
        )

    def resume(self, *, session_id: str, agent_id: str, cwd: str, model: str, runtime: str = "local", repo_url=None):
        return self.create_session(session_id=session_id, cwd=cwd, model=model, runtime=runtime)

    def send(self, session: ProviderSession, message: str) -> RunHandle:
        self.count += 1
        return RunHandle(run_id=f"run-{session.session_id}-{self.count}", _provider=self, _session=session)

    def stream(self, handle: RunHandle):
        yield StreamEvent(type="assistant", payload={"text": "ok"})

    def wait(self, handle: RunHandle):
        return "finished", "Done\n\nAutomation Memory Update\nAPI run completed."

    def cancel(self, handle: RunHandle) -> None:
        return None

    def close(self, session: ProviderSession) -> None:
        session._closed = True


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr("cursor_subagent.daemon.session_manager.get_provider", lambda _id: FakeProvider())
    monkeypatch.setenv("SUBAGENT_DB_PATH", str(tmp_path))
    monkeypatch.setenv("SUBAGENT_DISABLE_NATS", "1")
    monkeypatch.setenv("SUBAGENT_DISABLE_AUTOMATION_SCHEDULER", "1")
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_automation_crud_trigger_and_history(client: TestClient) -> None:
    created = client.post(
        "/automations",
        json={
            "name": "API automation",
            "task": "Run API task",
            "cwd": ".",
            "webhook_enabled": True,
        },
    )
    assert created.status_code == 200
    body = created.json()
    automation_id = body["id"]
    assert body["webhook_url"].endswith(f"/automations/{automation_id}/webhook")
    assert "webhook_secret" in body

    listed = client.get("/automations")
    assert listed.status_code == 200
    assert any(item["id"] == automation_id for item in listed.json())

    triggered = client.post(
        f"/automations/{automation_id}/trigger",
        json={"payload": {"reason": "manual-test"}},
    )
    assert triggered.status_code == 200
    run = triggered.json()
    assert run["status"] == "finished"
    assert run["session_id"].startswith("ses_")

    history = client.get(f"/automations/{automation_id}/history", params={"full": True})
    assert history.status_code == 200
    assert "API run completed" in history.json()["memory_summary"]
    assert len(history.json()["runs"]) == 1

    paused = client.patch(f"/automations/{automation_id}", json={"status": "paused"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    deleted = client.delete(f"/automations/{automation_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"


def test_webhook_requires_bearer_secret(client: TestClient) -> None:
    created = client.post(
        "/automations",
        json={
            "name": "Webhook automation",
            "task": "Run webhook task",
            "cwd": ".",
            "webhook_enabled": True,
        },
    ).json()
    automation_id = created["id"]
    secret = created["webhook_secret"]

    missing = client.post(f"/automations/{automation_id}/webhook", json={"payload": {"ok": True}})
    wrong = client.post(
        f"/automations/{automation_id}/webhook",
        headers={"Authorization": "Bearer wrong"},
        json={"payload": {"ok": True}},
    )
    accepted = client.post(
        f"/automations/{automation_id}/webhook",
        headers={"Authorization": f"Bearer {secret}"},
        json={"payload": {"ok": True}},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["trigger_type"] == "webhook"
