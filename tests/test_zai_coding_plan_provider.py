from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cursor_subagent.models import CreateAutomationRequest, ResumeSessionRequest, SpawnSessionRequest, WaveTask
from cursor_subagent.providers import default_model, get_provider, list_providers
from cursor_subagent.providers.base import StreamEvent
from cursor_subagent.providers.zai_coding_plan import ZaiCodingPlanProvider


def test_registry_includes_zai() -> None:
    assert "zai-coding-plan" in list_providers()
    provider = get_provider("zai-coding-plan")
    assert isinstance(provider, ZaiCodingPlanProvider)


def test_default_model_lookup() -> None:
    assert default_model("cursor-composer") == "composer-2.5"
    assert default_model("zai-coding-plan") == "glm-5.1"


def test_request_models_resolve_provider_default_model() -> None:
    assert SpawnSessionRequest(task="t", provider="zai-coding-plan").model == "glm-5.1"
    assert ResumeSessionRequest(agent_id="a", provider="zai-coding-plan").model == "glm-5.1"
    assert CreateAutomationRequest(name="n", task="t", provider="zai-coding-plan").model == "glm-5.1"
    assert WaveTask(taskId="x", goal="g", provider="zai-coding-plan").model == "glm-5.1"
    assert SpawnSessionRequest(task="t").model == "composer-2.5"


def test_create_session_starts_empty_history() -> None:
    provider = ZaiCodingPlanProvider(api_key="test-key")
    session = provider.create_session(session_id="ses-1", cwd="/tmp", model="glm-5.1")
    assert session.provider_id == "zai-coding-plan"
    assert session.model == "glm-5.1"
    assert session.agent_id is None
    assert session._raw["messages"] == []


def test_send_appends_user_message() -> None:
    provider = ZaiCodingPlanProvider(api_key="test-key")
    session = provider.create_session(session_id="ses-1", cwd="/tmp", model="glm-5.1")
    handle = provider.send(session, "hello")
    assert handle.run_id.startswith("zai-ses-1-")
    assert session._raw["messages"] == [{"role": "user", "content": "hello"}]


def test_stream_and_wait() -> None:
    provider = ZaiCodingPlanProvider(api_key="test-key")
    session = provider.create_session(session_id="ses-1", cwd="/tmp", model="glm-5.1")
    handle = provider.send(session, "hello")

    mock_response = MagicMock()
    mock_response.iter_lines.return_value = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Hi"}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": " there"}}]}),
        "data: [DONE]",
    ]

    mock_client = MagicMock()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_response
    mock_cm.__exit__.return_value = False
    mock_client.stream.return_value = mock_cm

    with patch("cursor_subagent.providers.zai_coding_plan.httpx.Client", return_value=mock_client):
        events = list(provider.stream(handle))

    assert events == [
        StreamEvent(type="assistant", payload={"text": "Hi"}),
        StreamEvent(type="assistant", payload={"text": " there"}),
    ]

    status, result = provider.wait(handle)
    assert status == "finished"
    assert result == "Hi there"
    assert session._raw["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there"},
    ]

    # Verify request shape.
    call_args = mock_client.stream.call_args
    assert call_args.args[0] == "POST"
    assert call_args.args[1] == ZaiCodingPlanProvider.endpoint
    assert call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    body = call_args.kwargs["json"]
    assert body["model"] == "glm-5.1"
    assert body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": "hello"}]


def test_multi_turn_history() -> None:
    provider = ZaiCodingPlanProvider(api_key="test-key")
    session = provider.create_session(session_id="ses-2", cwd="/tmp", model="glm-5.1")

    def _run_turn(message: str, reply: str) -> None:
        handle = provider.send(session, message)
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            "data: " + json.dumps({"choices": [{"delta": {"content": reply}}]}),
            "data: [DONE]",
        ]
        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_response
        mock_cm.__exit__.return_value = False
        mock_client.stream.return_value = mock_cm
        with patch("cursor_subagent.providers.zai_coding_plan.httpx.Client", return_value=mock_client):
            list(provider.stream(handle))
        provider.wait(handle)

    _run_turn("first", "reply-one")
    _run_turn("second", "reply-two")

    assert session._raw["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply-one"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "reply-two"},
    ]


def test_missing_api_key_raises() -> None:
    provider = ZaiCodingPlanProvider(api_key=None)
    with pytest.raises(RuntimeError, match="ZAI_API_KEY is not set"):
        provider._require_api_key()


def test_api_key_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "env-key")
    provider = ZaiCodingPlanProvider()
    assert provider._require_api_key() == "env-key"
