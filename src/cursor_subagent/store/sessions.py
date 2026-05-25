from __future__ import annotations

import sqlite3
import uuid

from cursor_subagent.models import RunRecord, RunStatus, SessionRecord, SessionStatus, utc_now_iso


class SessionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_session(self, record: SessionRecord) -> SessionRecord:
        self._conn.execute(
            """
            INSERT INTO sessions (
              id, provider, agent_id, cwd, model, runtime, status,
              wave_id, task_id, task_summary, persist, repo_url,
              created_at, updated_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.provider,
                record.agent_id,
                record.cwd,
                record.model,
                record.runtime,
                record.status.value,
                record.wave_id,
                record.task_id,
                record.task_summary,
                int(record.persist),
                record.repo_url,
                record.created_at,
                record.updated_at,
                record.closed_at,
            ),
        )
        self._conn.commit()
        return record

    def update_session(self, session_id: str, **fields: object) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [session_id]
        self._conn.execute(f"UPDATE sessions SET {cols} WHERE id = ?", values)
        self._conn.commit()

    def get_session(self, session_id: str) -> SessionRecord | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def list_sessions(
        self,
        *,
        cwd: str | None = None,
        wave_id: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[SessionRecord]:
        query = "SELECT * FROM sessions WHERE 1=1"
        params: list[object] = []
        if cwd:
            query += " AND cwd = ?"
            params.append(cwd)
        if wave_id:
            query += " AND wave_id = ?"
            params.append(wave_id)
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_session(r) for r in rows]

    def list_open_sessions(self) -> list[SessionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE status IN ('open', 'running', 'idle')"
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def close_session(self, session_id: str, *, purge: bool) -> None:
        if purge:
            self._conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        else:
            self._conn.execute(
                "UPDATE sessions SET status = ?, closed_at = ?, updated_at = ? WHERE id = ?",
                (SessionStatus.CLOSED.value, utc_now_iso(), utc_now_iso(), session_id),
            )
        self._conn.commit()

    def create_run(self, run: RunRecord) -> RunRecord:
        self._conn.execute(
            """
            INSERT INTO runs (id, session_id, status, result, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.session_id,
                run.status.value,
                run.result,
                run.started_at,
                run.finished_at,
            ),
        )
        self._conn.commit()
        return run

    def update_run(self, run_id: str, *, status: RunStatus, result: str | None = None) -> None:
        self._conn.execute(
            "UPDATE runs SET status = ?, result = ?, finished_at = ? WHERE id = ?",
            (status.value, result, utc_now_iso(), run_id),
        )
        self._conn.commit()

    def get_latest_run(self, session_id: str) -> RunRecord | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return RunRecord(
            id=row["id"],
            session_id=row["session_id"],
            status=RunStatus(row["status"]),
            result=row["result"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def new_session_id() -> str:
        return f"ses_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            provider=row["provider"],
            agent_id=row["agent_id"],
            cwd=row["cwd"],
            model=row["model"],
            runtime=row["runtime"],
            status=SessionStatus(row["status"]),
            wave_id=row["wave_id"],
            task_id=row["task_id"],
            task_summary=row["task_summary"],
            persist=bool(row["persist"]),
            repo_url=row["repo_url"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            closed_at=row["closed_at"],
        )
