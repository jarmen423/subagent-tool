"""Project-local automation orchestration.

The manager turns cron, manual, and webhook triggers into ordinary
``SessionManager.spawn`` calls. It deliberately creates a fresh persisted
Cursor session per run, then injects automation-owned memory into the prompt so
the fresh session can understand prior work without inheriting hidden agent
conversation state.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

from cursor_subagent.models import (
    AutomationRecord,
    AutomationRunRecord,
    AutomationRunStatus,
    AutomationStatus,
    AutomationTriggerType,
    AutomationTriggerRequest,
    CreateAutomationRequest,
    SpawnSessionRequest,
    UpdateAutomationRequest,
    utc_now_iso,
)
from cursor_subagent.store.automations import AutomationStore
from cursor_subagent.daemon.session_manager import SessionManager

MEMORY_SECTION_RE = re.compile(
    r"Automation Memory Update\s*:?\s*(?P<body>.*?)(?:\n#{1,6}\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class AutomationManager:
    """Coordinate automation definitions, triggers, and run history."""

    store: AutomationStore
    session_manager: SessionManager
    ticker_interval_seconds: float = 30.0

    def create(self, req: CreateAutomationRequest, *, base_url: str) -> dict[str, Any]:
        """Create an automation and return a one-time webhook secret if needed."""
        secret = self._new_secret() if req.webhook_enabled else None
        next_run_at = self._next_run_at(req.cron_expression) if req.cron_expression else None
        cwd = str(Path(req.cwd).resolve())
        record = AutomationRecord(
            id=self.store.new_automation_id(),
            name=req.name,
            task=req.task,
            cwd=cwd,
            provider=req.provider,
            model=req.model,
            runtime=req.runtime,
            repo_url=req.repo_url,
            cron_expression=req.cron_expression,
            webhook_enabled=req.webhook_enabled,
            webhook_secret_hash=self._hash_secret(secret) if secret else None,
            recent_run_count=req.recent_run_count,
            next_run_at=next_run_at,
        )
        self.store.create_automation(record)
        return self._automation_response(record, base_url=base_url, webhook_secret=secret)

    def list(self, *, status: AutomationStatus | None = None, base_url: str) -> list[dict[str, Any]]:
        return [
            self._automation_response(record, base_url=base_url)
            for record in self.store.list_automations(status=status)
        ]

    def get(self, automation_id: str, *, base_url: str) -> dict[str, Any]:
        record = self._require_automation(automation_id)
        return self._automation_response(record, base_url=base_url)

    def update(self, automation_id: str, req: UpdateAutomationRequest, *, base_url: str) -> dict[str, Any]:
        """Patch an automation definition and recalculate schedule state."""
        record = self._require_automation(automation_id)
        fields = req.model_dump(exclude_unset=True)
        webhook_secret: str | None = None
        if "cwd" in fields and fields["cwd"] is not None:
            fields["cwd"] = str(Path(fields["cwd"]).resolve())
        if "cron_expression" in fields:
            fields["next_run_at"] = (
                self._next_run_at(fields["cron_expression"]) if fields["cron_expression"] else None
            )
        elif fields.get("status") in (AutomationStatus.ENABLED, AutomationStatus.ENABLED.value) and record.cron_expression:
            fields["next_run_at"] = self._next_run_at(record.cron_expression)
        if "webhook_enabled" in fields and fields["webhook_enabled"] is False:
            fields["webhook_secret_hash"] = None
        if (
            "webhook_enabled" in fields
            and fields["webhook_enabled"] is True
            and not record.webhook_secret_hash
        ):
            webhook_secret = self._new_secret()
            fields["webhook_secret_hash"] = self._hash_secret(webhook_secret)
        if "recent_run_count" in fields and fields["recent_run_count"] is not None:
            fields["recent_run_count"] = max(1, int(fields["recent_run_count"]))
        self.store.update_automation(record.id, **fields)
        updated = self._require_automation(automation_id)
        return self._automation_response(updated, base_url=base_url, webhook_secret=webhook_secret)

    def delete(self, automation_id: str) -> dict[str, str]:
        self._require_automation(automation_id)
        self.store.delete_automation(automation_id)
        return {"automation_id": automation_id, "status": "deleted"}

    def rotate_secret(self, automation_id: str, *, base_url: str) -> dict[str, Any]:
        record = self._require_automation(automation_id)
        secret = self._new_secret()
        self.store.update_automation(
            record.id,
            webhook_enabled=True,
            webhook_secret_hash=self._hash_secret(secret),
        )
        updated = self._require_automation(record.id)
        return self._automation_response(updated, base_url=base_url, webhook_secret=secret)

    async def trigger(
        self,
        automation_id: str,
        *,
        trigger_type: AutomationTriggerType,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an automation by creating a fresh persisted Cursor session."""
        record = self._require_automation(automation_id)
        if record.status != AutomationStatus.ENABLED:
            raise ValueError(f"Automation is {record.status.value}: {automation_id}")
        trigger_payload = payload or {}
        rendered_prompt = self.render_prompt(record, trigger_type=trigger_type, payload=trigger_payload)
        run = AutomationRunRecord(
            id=self.store.new_run_id(),
            automation_id=record.id,
            trigger_type=trigger_type,
            trigger_payload=trigger_payload,
            rendered_prompt=rendered_prompt,
        )
        self.store.create_run(run)
        try:
            result = await self.session_manager.spawn(
                SpawnSessionRequest(
                    task=rendered_prompt,
                    cwd=record.cwd,
                    provider=record.provider,
                    model=record.model,
                    runtime=record.runtime,
                    repo_url=record.repo_url,
                    persist=True,
                )
            )
            session_id = result.get("session_id")
            output = result.get("result") or ""
            memory_update = self._extract_memory_update(output) or self._fallback_memory_update(
                record,
                run,
                output,
            )
            new_summary = self._merge_memory(record.memory_summary, memory_update)
            finished_at = utc_now_iso()
            self.store.update_run(
                run.id,
                session_id=session_id,
                status=AutomationRunStatus.FINISHED,
                result=output,
                memory_update=memory_update,
                finished_at=finished_at,
            )
            self.store.update_automation(
                record.id,
                memory_summary=new_summary,
                next_run_at=self._next_run_at(record.cron_expression) if record.cron_expression else None,
            )
        except Exception as exc:
            self.store.update_run(
                run.id,
                status=AutomationRunStatus.ERROR,
                error=str(exc),
                finished_at=utc_now_iso(),
            )
            if record.cron_expression:
                self.store.update_automation(record.id, next_run_at=self._next_run_at(record.cron_expression))
            raise
        stored = self.store.get_run(run.id)
        return stored.model_dump() if stored else run.model_dump()

    async def trigger_webhook(
        self,
        automation_id: str,
        *,
        bearer_token: str | None,
        req: AutomationTriggerRequest,
    ) -> dict[str, Any]:
        """Authenticate and execute a webhook-triggered automation run."""
        record = self._require_automation(automation_id)
        if not record.webhook_enabled or not record.webhook_secret_hash:
            raise PermissionError("Webhook trigger is not enabled")
        if not bearer_token or not self._verify_secret(bearer_token, record.webhook_secret_hash):
            raise PermissionError("Invalid webhook bearer token")
        return await self.trigger(
            automation_id,
            trigger_type=AutomationTriggerType.WEBHOOK,
            payload=req.payload,
        )

    def list_runs(self, automation_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_automation(automation_id)
        return [run.model_dump() for run in self.store.list_runs(automation_id, limit=limit)]

    def history(self, automation_id: str, *, full: bool = False, limit: int = 50) -> dict[str, Any]:
        record = self._require_automation(automation_id)
        data: dict[str, Any] = {
            "automation_id": record.id,
            "memory_summary": record.memory_summary or "",
        }
        if full:
            data["runs"] = self.list_runs(automation_id, limit=limit)
        return data

    async def fire_due_once(self) -> list[dict[str, Any]]:
        """Fire each currently due cron automation at most once."""
        now = datetime.now().astimezone()
        fired: list[dict[str, Any]] = []
        for record in self.store.list_due_cron_automations(now.isoformat()):
            if self.store.has_running_run(record.id):
                continue
            fired.append(
                await self.trigger(
                    record.id,
                    trigger_type=AutomationTriggerType.CRON,
                    payload={"scheduled_for": record.next_run_at},
                )
            )
        return fired

    async def run_scheduler(self, stop: asyncio.Event) -> None:
        """Run the daemon-local cron ticker until ``stop`` is set."""
        while not stop.is_set():
            try:
                await self.fire_due_once()
            except Exception:
                # Individual run errors are already persisted. The scheduler
                # loop keeps going so one bad automation does not stop all jobs.
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.ticker_interval_seconds)
            except asyncio.TimeoutError:
                continue

    def render_prompt(
        self,
        record: AutomationRecord,
        *,
        trigger_type: AutomationTriggerType,
        payload: dict[str, Any],
    ) -> str:
        """Render the task prompt with automation memory injected."""
        recent = self.store.list_runs(record.id, limit=record.recent_run_count)
        recent_lines = []
        for run in recent:
            summary = run.memory_update or run.result or run.error or ""
            recent_lines.append(
                f"- {run.started_at} [{run.trigger_type.value}/{run.status.value}] "
                f"session={run.session_id or 'none'}: {summary[:500]}"
            )
        recent_block = "\n".join(recent_lines) if recent_lines else "- No prior runs recorded."
        payload_block = payload if payload else {}
        return f"""You are running project-local automation `{record.name}`.

Automation Task:
{record.task}

Automation History:
Rolling memory summary:
{record.memory_summary or "No durable memory yet."}

Recent runs:
{recent_block}

Full automation history is stored in the local cursor-subagent automation run ledger. If this run needs more detail, ask the operator to inspect `cursor-subagent automation history {record.id} --full`.

Trigger:
- type: {trigger_type.value}
- payload: {payload_block}

At the end of your response, include a concise section named `Automation Memory Update` that states what changed, what was completed, what remains, and any facts future fresh automation sessions must know.
"""

    def _automation_response(
        self,
        record: AutomationRecord,
        *,
        base_url: str,
        webhook_secret: str | None = None,
    ) -> dict[str, Any]:
        data = record.model_dump()
        if record.webhook_enabled:
            data["webhook_url"] = f"{base_url.rstrip('/')}/automations/{record.id}/webhook"
        if webhook_secret:
            data["webhook_secret"] = webhook_secret
        return data

    def _require_automation(self, automation_id: str) -> AutomationRecord:
        record = self.store.get_automation(automation_id)
        if not record:
            raise KeyError(automation_id)
        return record

    def _next_run_at(self, cron_expression: str | None) -> str | None:
        if not cron_expression:
            return None
        if not croniter.is_valid(cron_expression, strict=True):
            raise ValueError(f"Invalid cron expression: {cron_expression}")
        now = datetime.now().astimezone()
        return croniter(cron_expression, now).get_next(datetime).isoformat()

    @staticmethod
    def _new_secret() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _hash_secret(secret: str | None) -> str | None:
        if secret is None:
            return None
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @classmethod
    def _verify_secret(cls, secret: str, expected_hash: str) -> bool:
        return hmac.compare_digest(cls._hash_secret(secret) or "", expected_hash)

    @staticmethod
    def _extract_memory_update(result: str) -> str | None:
        match = MEMORY_SECTION_RE.search(result or "")
        if not match:
            return None
        body = match.group("body").strip()
        return body[:4000] if body else None

    @staticmethod
    def _fallback_memory_update(
        record: AutomationRecord,
        run: AutomationRunRecord,
        result: str,
    ) -> str:
        text = (result or "").strip().replace("\n", " ")
        if len(text) > 800:
            text = text[:797] + "..."
        return (
            f"Run {run.id} for automation {record.name} completed without an explicit "
            f"Automation Memory Update section. Result excerpt: {text or 'no result text'}"
        )

    @staticmethod
    def _merge_memory(previous: str | None, update: str) -> str:
        if not previous:
            return update[:6000]
        merged = f"{previous.strip()}\n\nLatest update:\n{update.strip()}"
        return merged[-6000:]


def next_future_from(now: datetime, cron_expression: str) -> str:
    """Test helper and utility for computing a future cron fire time."""
    if not croniter.is_valid(cron_expression, strict=True):
        raise ValueError(f"Invalid cron expression: {cron_expression}")
    return croniter(cron_expression, now).get_next(datetime).isoformat()
