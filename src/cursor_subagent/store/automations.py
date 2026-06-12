"""SQLite persistence for project-local automations.

The automation store owns long-lived automation state, not live Cursor handles.
Each automation run still creates a normal ``sessions`` row through
``SessionManager``; this store keeps the cross-run ledger and memory summary
that make fresh sessions aware of prior work.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from cursor_subagent.models import (
    AutomationRecord,
    AutomationRunRecord,
    AutomationRunStatus,
    AutomationStatus,
    AutomationTriggerType,
    utc_now_iso,
)


class AutomationStore:
    """Read and write durable automation definitions and run history."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_automation(self, record: AutomationRecord) -> AutomationRecord:
        """Persist a new automation definition."""
        self._conn.execute(
            """
            INSERT INTO automations (
              id, name, task, cwd, provider, model, runtime, repo_url,
              cron_expression, webhook_enabled, webhook_secret_hash, status,
              memory_summary, recent_run_count, next_run_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._automation_values(record),
        )
        self._conn.commit()
        return record

    def update_automation(self, automation_id: str, **fields: Any) -> None:
        """Update selected automation fields and refresh ``updated_at``."""
        if not fields:
            return
        fields["updated_at"] = utc_now_iso()
        cols = ", ".join(f"{key} = ?" for key in fields)
        values = [self._db_value(value) for value in fields.values()]
        values.append(automation_id)
        self._conn.execute(f"UPDATE automations SET {cols} WHERE id = ?", values)
        self._conn.commit()

    def delete_automation(self, automation_id: str) -> None:
        """Delete an automation and its local run ledger."""
        self._conn.execute("DELETE FROM automation_runs WHERE automation_id = ?", (automation_id,))
        self._conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
        self._conn.commit()

    def get_automation(self, automation_id: str) -> AutomationRecord | None:
        row = self._conn.execute(
            "SELECT * FROM automations WHERE id = ?",
            (automation_id,),
        ).fetchone()
        return self._row_to_automation(row) if row else None

    def list_automations(self, *, status: AutomationStatus | None = None) -> list[AutomationRecord]:
        query = "SELECT * FROM automations WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_automation(row) for row in rows]

    def list_due_cron_automations(self, now_iso: str) -> list[AutomationRecord]:
        """Return enabled cron automations due at or before ``now_iso``."""
        rows = self._conn.execute(
            """
            SELECT * FROM automations
            WHERE status = ?
              AND cron_expression IS NOT NULL
              AND next_run_at IS NOT NULL
            ORDER BY next_run_at ASC
            """,
            (AutomationStatus.ENABLED.value,),
        ).fetchall()
        now = iso_to_datetime(now_iso)
        records = [self._row_to_automation(row) for row in rows]
        return [
            record
            for record in records
            if record.next_run_at and iso_to_datetime(record.next_run_at) <= now
        ]

    def create_run(self, record: AutomationRunRecord) -> AutomationRunRecord:
        """Insert a run ledger row before the Cursor session is spawned."""
        self._conn.execute(
            """
            INSERT INTO automation_runs (
              id, automation_id, trigger_type, trigger_payload_json,
              rendered_prompt, session_id, status, result, error,
              memory_update, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._run_values(record),
        )
        self._conn.commit()
        return record

    def update_run(self, run_id: str, **fields: Any) -> None:
        """Update a run ledger row as the backing session progresses."""
        if not fields:
            return
        cols = ", ".join(f"{key} = ?" for key in fields)
        values = [self._db_value(value) for value in fields.values()]
        values.append(run_id)
        self._conn.execute(f"UPDATE automation_runs SET {cols} WHERE id = ?", values)
        self._conn.commit()

    def get_run(self, run_id: str) -> AutomationRunRecord | None:
        row = self._conn.execute(
            "SELECT * FROM automation_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return self._row_to_run(row) if row else None

    def list_runs(self, automation_id: str, *, limit: int = 50) -> list[AutomationRunRecord]:
        rows = self._conn.execute(
            """
            SELECT * FROM automation_runs
            WHERE automation_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (automation_id, limit),
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def has_running_run(self, automation_id: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM automation_runs
            WHERE automation_id = ? AND status = ?
            LIMIT 1
            """,
            (automation_id, AutomationRunStatus.RUNNING.value),
        ).fetchone()
        return row is not None

    @staticmethod
    def new_automation_id() -> str:
        return f"aut_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_run_id() -> str:
        return f"arun_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _db_value(value: Any) -> Any:
        if isinstance(value, bool):
            return int(value)
        if hasattr(value, "value"):
            return value.value
        if isinstance(value, dict):
            return json.dumps(value, default=str)
        return value

    @staticmethod
    def _automation_values(record: AutomationRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.name,
            record.task,
            record.cwd,
            record.provider,
            record.model,
            record.runtime,
            record.repo_url,
            record.cron_expression,
            int(record.webhook_enabled),
            record.webhook_secret_hash,
            record.status.value,
            record.memory_summary,
            record.recent_run_count,
            record.next_run_at,
            record.created_at,
            record.updated_at,
        )

    @staticmethod
    def _run_values(record: AutomationRunRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.automation_id,
            record.trigger_type.value,
            json.dumps(record.trigger_payload, default=str),
            record.rendered_prompt,
            record.session_id,
            record.status.value,
            record.result,
            record.error,
            record.memory_update,
            record.started_at,
            record.finished_at,
        )

    @staticmethod
    def _row_to_automation(row: sqlite3.Row) -> AutomationRecord:
        return AutomationRecord(
            id=row["id"],
            name=row["name"],
            task=row["task"],
            cwd=row["cwd"],
            provider=row["provider"],
            model=row["model"],
            runtime=row["runtime"],
            repo_url=row["repo_url"],
            cron_expression=row["cron_expression"],
            webhook_enabled=bool(row["webhook_enabled"]),
            webhook_secret_hash=row["webhook_secret_hash"],
            status=AutomationStatus(row["status"]),
            memory_summary=row["memory_summary"],
            recent_run_count=row["recent_run_count"],
            next_run_at=row["next_run_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> AutomationRunRecord:
        payload = json.loads(row["trigger_payload_json"] or "{}")
        return AutomationRunRecord(
            id=row["id"],
            automation_id=row["automation_id"],
            trigger_type=AutomationTriggerType(row["trigger_type"]),
            trigger_payload=payload,
            rendered_prompt=row["rendered_prompt"],
            session_id=row["session_id"],
            status=AutomationRunStatus(row["status"]),
            result=row["result"],
            error=row["error"],
            memory_update=row["memory_update"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


def iso_to_datetime(value: str) -> datetime:
    """Parse an ISO timestamp stored by the automation scheduler."""
    return datetime.fromisoformat(value)
