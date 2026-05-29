from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

DEFAULT_NATS_URL = os.environ.get("SUBAGENT_NATS_URL", "nats://127.0.0.1:4222")


def session_subject(session_id: str, suffix: str) -> str:
    return f"subagent.v1.session.{session_id}.{suffix}"


def wave_subject(wave_id: str) -> str:
    return f"subagent.v1.wave.{wave_id}.events"


@runtime_checkable
class EventPublisher(Protocol):
    async def publish_session_event(self, session_id: str, event: dict[str, Any]) -> None: ...

    async def publish_wave_event(self, wave_id: str, event: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


class NoOpPublisher:
    async def publish_session_event(self, session_id: str, event: dict[str, Any]) -> None:
        return None

    async def publish_wave_event(self, wave_id: str, event: dict[str, Any]) -> None:
        return None

    async def close(self) -> None:
        return None


class NatsPublisher:
    def __init__(self, nats_url: str = DEFAULT_NATS_URL) -> None:
        self._nats_url = nats_url
        self._nc: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> Any:
        if self._nc is not None and not self._nc.is_closed:
            return self._nc
        async with self._lock:
            if self._nc is not None and not self._nc.is_closed:
                return self._nc
            import nats

            self._nc = await nats.connect(self._nats_url)
            return self._nc

    async def publish_session_event(self, session_id: str, event: dict[str, Any]) -> None:
        try:
            nc = await self._ensure_connected()
            kind = event.get("event", "stream")
            suffix = "lifecycle" if kind in {"run_complete", "session_closed"} else "events"
            subject = session_subject(session_id, suffix)
            await nc.publish(subject, json.dumps(event, default=str).encode("utf-8"))
        except Exception as exc:
            logger.warning("NATS publish failed for session %s: %s", session_id, exc)

    async def publish_wave_event(self, wave_id: str, event: dict[str, Any]) -> None:
        try:
            nc = await self._ensure_connected()
            await nc.publish(
                wave_subject(wave_id),
                json.dumps(event, default=str).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning("NATS publish failed for wave %s: %s", wave_id, exc)

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            await self._nc.close()
            self._nc = None


async def create_publisher() -> EventPublisher:
    if os.environ.get("SUBAGENT_DISABLE_NATS", "").lower() in {"1", "true", "yes"}:
        return NoOpPublisher()
    publisher = NatsPublisher()
    try:
        await asyncio.wait_for(publisher._ensure_connected(), timeout=2.0)
        return publisher
    except Exception as exc:
        logger.warning("NATS unavailable (%s); using NoOpPublisher", exc)
        return NoOpPublisher()
