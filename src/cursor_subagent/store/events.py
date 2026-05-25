from __future__ import annotations

import json
import sqlite3

from cursor_subagent.models import EventRecord, utc_now_iso


class EventStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, event: EventRecord) -> EventRecord:
        cur = self._conn.execute(
            """
            INSERT INTO events (session_id, run_id, type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.run_id,
                event.type,
                json.dumps(event.payload, default=str),
                event.created_at,
            ),
        )
        self._conn.commit()
        event.id = cur.lastrowid
        return event

    def list_events(
        self,
        session_id: str,
        *,
        since_run_id: str | None = None,
        limit: int = 500,
    ) -> list[EventRecord]:
        query = "SELECT * FROM events WHERE session_id = ?"
        params: list[object] = [session_id]
        if since_run_id:
            query += " AND run_id >= ?"
            params.append(since_run_id)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            id=row["id"],
            session_id=row["session_id"],
            run_id=row["run_id"],
            type=row["type"],
            payload=json.loads(row["payload_json"] or "{}"),
            created_at=row["created_at"],
        )
