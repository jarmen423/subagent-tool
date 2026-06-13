from __future__ import annotations

import json
import os
from typing import Any, Iterator

import httpx

from cursor_subagent.providers.base import AgentProvider, ProviderSession, RunHandle, StreamEvent


class ZaiCodingPlanProvider:
    """Direct OpenAI-compatible provider for the Z.AI GLM Coding Plan API.

    The caller maintains the full conversation history; each request includes
    the accumulated ``messages`` array. Responses are streamed and parsed from
    server-sent events.
    """

    provider_id = "zai-coding-plan"
    default_model = "glm-5.1"
    endpoint = "https://api.z.ai/api/coding/paas/v4/chat/completions"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    def _require_api_key(self) -> str:
        """Return the Z.AI API key after per-command env loading."""
        self._api_key = self._api_key or os.environ.get("ZAI_API_KEY")
        if not self._api_key:
            raise RuntimeError("ZAI_API_KEY is not set")
        return self._api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._require_api_key()}",
            "Content-Type": "application/json",
            "Accept-Language": "en-US,en",
        }

    def create_session(
        self,
        *,
        session_id: str,
        cwd: str,
        model: str,
        runtime: str = "local",
        repo_url: str | None = None,
    ) -> ProviderSession:
        return ProviderSession(
            session_id=session_id,
            agent_id=None,
            provider_id=self.provider_id,
            cwd=cwd,
            model=model or self.default_model,
            runtime=runtime,
            _raw={"messages": []},
        )

    def resume(
        self,
        *,
        session_id: str,
        agent_id: str,
        cwd: str,
        model: str,
        runtime: str = "local",
        repo_url: str | None = None,
    ) -> ProviderSession:
        # Z.AI does not expose durable agent/session IDs. Resume creates a fresh
        # local session; prior history is not restored from the API side.
        return self.create_session(
            session_id=session_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            repo_url=repo_url,
        )

    def send(self, session: ProviderSession, message: str) -> RunHandle:
        messages: list[dict[str, str]] = session._raw["messages"]
        messages.append({"role": "user", "content": message})
        return RunHandle(
            run_id=f"zai-{session.session_id}-{len(messages)}",
            _provider=self,
            _session=session,
            _raw={
                "request_body": {
                    "model": session.model,
                    "messages": list(messages),
                    "stream": True,
                },
            },
        )

    def _parse_sse(self, line: str) -> str | None:
        if not line.startswith("data: "):
            return ""
        data = line[6:]
        if data == "[DONE]":
            return None
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return ""
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if not choices:
            return ""
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else {}
        if not isinstance(delta, dict):
            return ""
        content = delta.get("content")
        return content if isinstance(content, str) else ""

    def stream(self, handle: RunHandle) -> Iterator[StreamEvent]:
        raw = handle._raw
        request_body = raw["request_body"]
        client = httpx.Client(timeout=600.0)
        raw["client"] = client
        buffer_parts: list[str] = []
        try:
            with client.stream(
                "POST",
                self.endpoint,
                headers=self._headers(),
                json=request_body,
            ) as response:
                raw["response"] = response
                response.raise_for_status()
                for line in response.iter_lines():
                    text = self._parse_sse(line)
                    if text is None:
                        break
                    if text:
                        buffer_parts.append(text)
                        yield StreamEvent(type="assistant", payload={"text": text})
        finally:
            client.close()
        raw["buffer"] = "".join(buffer_parts)

    def wait(self, handle: RunHandle) -> tuple[str, str]:
        raw = handle._raw
        result = raw.get("buffer", "")
        messages: list[dict[str, str]] = handle._session._raw["messages"]
        messages.append({"role": "assistant", "content": result})
        return "finished", result

    def cancel(self, handle: RunHandle) -> None:
        raw = handle._raw
        response = raw.get("response")
        if response is not None:
            response.close()
        client = raw.get("client")
        if client is not None:
            client.close()

    def close(self, session: ProviderSession) -> None:
        session._closed = True
