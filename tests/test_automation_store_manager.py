from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest

from cursor_subagent.daemon.automation_manager import AutomationManager, next_future_from
from cursor_subagent.daemon.session_manager import SessionManager
from cursor_subagent.models import (
    AutomationStatus,
    AutomationTriggerType,
    CreateAutomationRequest,
)
from cursor_subagent.providers.base import ProviderSession, RunHandle, StreamEvent
from cursor_subagent.store.automations import AutomationStore
from cursor_subagent.store.db import connect
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore


@dataclass
class FakeProvider:
    """Provider double that records prompts and returns an automation memory section."""

    provider_id: str = "cursor-composer"
    prompts: list[str] = field(default_factory=list)
    result_text: str = (
        "Finished work.\n\nAutomation Memory Update\n"
        "Remember that the first run completed the setup step."
    )

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
        self.prompts.append(message)
        return RunHandle(
            run_id=f"run-{session.session_id}-{session._raw['count']}",
            _provider=self,
            _session=session,
        )

    def stream(self, handle: RunHandle) -> Iterator[StreamEvent]:
        yield StreamEvent(type="assistant", payload={"text": "ok"})

    def wait(self, handle: RunHandle) -> tuple[str, str]:
        return "finished", self.result_text

    def cancel(self, handle: RunHandle) -> None:
        return None

    def close(self, session: ProviderSession) -> None:
        session._closed = True


@pytest.fixture
def automation_manager(monkeypatch: pytest.MonkeyPatch, tmp_path):
    conn = connect(tmp_path / "automations.db")
    fake = FakeProvider()
    monkeypatch.setattr("cursor_subagent.daemon.session_manager.get_provider", lambda _id: fake)
    session_manager = SessionManager(
        session_store=SessionStore(conn),
        event_store=EventStore(conn),
    )
    manager = AutomationManager(
        store=AutomationStore(conn),
        session_manager=session_manager,
        ticker_interval_seconds=0.01,
    )
    yield manager, fake, tmp_path
    conn.close()


def test_automation_store_create_and_secret_hash(automation_manager) -> None:
    manager, _fake, tmp_path = automation_manager
    created = manager.create(
        CreateAutomationRequest(
            name="Nightly digest",
            task="Summarize changes",
            cwd=str(tmp_path),
            cron_expression="0 9 * * *",
            webhook_enabled=True,
        ),
        base_url="http://127.0.0.1:17340",
    )
    assert created["id"].startswith("aut_")
    assert created["webhook_url"].endswith(f"/automations/{created['id']}/webhook")
    assert "webhook_secret" in created
    stored = manager.store.get_automation(created["id"])
    assert stored is not None
    assert stored.webhook_secret_hash != created["webhook_secret"]
    assert stored.next_run_at is not None


@pytest.mark.asyncio
async def test_trigger_creates_fresh_persisted_sessions_with_history(automation_manager) -> None:
    manager, fake, tmp_path = automation_manager
    created = manager.create(
        CreateAutomationRequest(name="Digest", task="Do the recurring task", cwd=str(tmp_path)),
        base_url="http://daemon",
    )

    first = await manager.trigger(
        created["id"],
        trigger_type=AutomationTriggerType.MANUAL,
        payload={"source": "test"},
    )
    second = await manager.trigger(
        created["id"],
        trigger_type=AutomationTriggerType.MANUAL,
        payload={"source": "test-again"},
    )

    assert first["session_id"] != second["session_id"]
    assert "Automation History" in fake.prompts[0]
    assert "No prior runs recorded" in fake.prompts[0]
    assert "Remember that the first run completed" in fake.prompts[1]
    assert "session=" in fake.prompts[1]
    stored = manager.store.get_automation(created["id"])
    assert stored is not None
    assert "Remember that the first run completed" in (stored.memory_summary or "")
    assert len(manager.store.list_runs(created["id"])) == 2
    assert manager.session_manager.session_store.get_session(first["session_id"]) is not None


@pytest.mark.asyncio
async def test_summary_fallback_keeps_run_record_when_memory_section_missing(automation_manager) -> None:
    manager, fake, tmp_path = automation_manager
    fake.result_text = "Completed without the requested section."
    created = manager.create(
        CreateAutomationRequest(name="No summary", task="Run once", cwd=str(tmp_path)),
        base_url="http://daemon",
    )

    run = await manager.trigger(created["id"], trigger_type=AutomationTriggerType.MANUAL)

    assert run["status"] == "finished"
    assert "without an explicit Automation Memory Update" in (run["memory_update"] or "")
    assert manager.store.get_run(run["id"]) is not None


@pytest.mark.asyncio
async def test_due_cron_fires_once_and_skips_paused(automation_manager) -> None:
    manager, _fake, tmp_path = automation_manager
    created = manager.create(
        CreateAutomationRequest(
            name="Frequent",
            task="Run cron task",
            cwd=str(tmp_path),
            cron_expression="* * * * *",
        ),
        base_url="http://daemon",
    )
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    manager.store.update_automation(created["id"], next_run_at=due)

    fired = await manager.fire_due_once()
    manager.store.update_automation(created["id"], status=AutomationStatus.PAUSED)
    manager.store.update_automation(created["id"], next_run_at=due)
    skipped = await manager.fire_due_once()

    assert len(fired) == 1
    assert skipped == []


def test_next_future_from_validates_cron() -> None:
    base = datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc)
    assert next_future_from(base, "0 9 * * *").endswith("09:00:00+00:00")
    with pytest.raises(ValueError):
        next_future_from(base, "0 wrong * * *")
