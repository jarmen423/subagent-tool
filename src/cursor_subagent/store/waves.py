from __future__ import annotations

import json
import sqlite3

from cursor_subagent.models import WaveRecord, WaveStatus, WaveTask, utc_now_iso


class WaveStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_wave(self, wave: WaveRecord) -> WaveRecord:
        self._conn.execute(
            "INSERT INTO waves (id, goal, tasks_json, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                wave.id,
                wave.goal,
                json.dumps([t.model_dump() for t in wave.tasks]),
                wave.status.value,
                wave.created_at,
            ),
        )
        self._conn.commit()
        return wave

    def get_wave(self, wave_id: str) -> WaveRecord | None:
        row = self._conn.execute("SELECT * FROM waves WHERE id = ?", (wave_id,)).fetchone()
        if not row:
            return None
        tasks = [WaveTask.model_validate(t) for t in json.loads(row["tasks_json"] or "[]")]
        return WaveRecord(
            id=row["id"],
            goal=row["goal"],
            tasks=tasks,
            status=WaveStatus(row["status"]),
            created_at=row["created_at"],
        )

    def update_status(self, wave_id: str, status: WaveStatus) -> None:
        self._conn.execute("UPDATE waves SET status = ? WHERE id = ?", (status.value, wave_id))
        self._conn.commit()
