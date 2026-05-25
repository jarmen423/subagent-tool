from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cursor_subagent.models import SessionRecord, SessionStatus, WaveRecord, WaveStatus, WaveTask
from cursor_subagent.store.db import connect
from cursor_subagent.store.events import EventStore
from cursor_subagent.store.sessions import SessionStore
from cursor_subagent.store.waves import WaveStore


@pytest.fixture
def db_conn(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    yield conn
    conn.close()


def test_session_store_roundtrip(db_conn) -> None:
    store = SessionStore(db_conn)
    record = SessionRecord(
        id="ses_test123",
        cwd=str(Path.cwd()),
        model="composer-2.5",
        runtime="local",
        status=SessionStatus.OPEN,
        task_summary="Do something",
    )
    store.create_session(record)
    loaded = store.get_session("ses_test123")
    assert loaded is not None
    assert loaded.task_summary == "Do something"
    store.close_session("ses_test123", purge=True)
    assert store.get_session("ses_test123") is None


def test_event_store_append_and_list(db_conn) -> None:
    from cursor_subagent.models import EventRecord

    events = EventStore(db_conn)
    events.append(
        EventRecord(session_id="ses_1", run_id="run_1", type="assistant", payload={"text": "hi"})
    )
    rows = events.list_events("ses_1")
    assert len(rows) == 1
    assert rows[0].payload["text"] == "hi"


def test_wave_store_create_and_get(db_conn) -> None:
    waves = WaveStore(db_conn)
    wave = WaveRecord(
        id="wave-1",
        goal="Refactor auth",
        tasks=[WaveTask(task_id="T1", goal="Refactor middleware", owned_paths=["src/auth/"])],
        status=WaveStatus.OPEN,
    )
    waves.create_wave(wave)
    loaded = waves.get_wave("wave-1")
    assert loaded is not None
    assert loaded.tasks[0].task_id == "T1"
