from __future__ import annotations

import json

import pytest

from cursor_subagent.bus.nats_publisher import NatsPublisher, session_subject
from cursor_subagent.bus.startup import is_nats_running


@pytest.mark.asyncio
@pytest.mark.integration
async def test_nats_publish_and_subscribe() -> None:
    if not is_nats_running():
        pytest.skip("nats-server not running")

    import nats

    publisher = NatsPublisher()
    nc = await nats.connect()
    sub = await nc.subscribe(session_subject("ses_test", "events"))

    await publisher.publish_session_event(
        "ses_test",
        {"event": "stream", "run_id": "run-1", "type": "assistant", "payload": {"text": "hi"}},
    )

    msg = await sub.next_msg(timeout=2)
    payload = json.loads(msg.data.decode("utf-8"))
    assert payload["run_id"] == "run-1"

    await publisher.close()
    await nc.drain()
