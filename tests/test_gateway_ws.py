from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from cursor_subagent.bus.nats_publisher import NatsPublisher
from cursor_subagent.bus.startup import gateway_ws_url, is_gateway_running, is_nats_running


@pytest.mark.asyncio
@pytest.mark.integration
async def test_gateway_forwards_nats_events() -> None:
    if not is_nats_running() or not is_gateway_running():
        pytest.skip("nats-server and subagent-gateway must be running")

    session_id = "ses_gateway_test"
    ws_url = f"{gateway_ws_url().rstrip('/')}/sessions/{session_id}/stream"
    publisher = NatsPublisher()

    async def listen_once() -> dict:
        async with websockets.connect(ws_url) as ws:
            await publisher.publish_session_event(
                session_id,
                {"event": "stream", "run_id": "run-gw-1", "type": "assistant", "payload": {"text": "hello"}},
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            return json.loads(raw)

    payload = await listen_once()
    assert payload["run_id"] == "run-gw-1"
    await publisher.close()
