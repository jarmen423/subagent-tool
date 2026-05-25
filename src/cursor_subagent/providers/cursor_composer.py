from __future__ import annotations

import json
import os
from typing import Any, Iterator

from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, CloudRepository, LocalAgentOptions
from cursor_sdk import CursorAgentError

from cursor_subagent.providers.base import AgentProvider, ProviderSession, RunHandle, StreamEvent


def _serialize_message(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        return message.model_dump()
    if hasattr(message, "to_dict"):
        return message.to_dict()
    return {"type": getattr(message, "type", "unknown"), "raw": str(message)}


class CursorComposerProvider:
    provider_id = "cursor-composer"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("CURSOR_API_KEY")

    def _require_api_key(self) -> str:
        if not self._api_key:
            raise CursorAgentError("CURSOR_API_KEY is not set")
        return self._api_key

    def _create_agent(
        self,
        *,
        cwd: str,
        model: str,
        runtime: str,
        repo_url: str | None,
    ) -> Any:
        api_key = self._require_api_key()
        if runtime == "cloud":
            if not repo_url:
                raise ValueError("repo_url is required for cloud runtime")
            return Agent.create(
                model=model,
                api_key=api_key,
                cloud=CloudAgentOptions(
                    repos=[CloudRepository(url=repo_url)],
                    skip_reviewer_request=True,
                ),
            )
        return Agent.create(
            model=model,
            api_key=api_key,
            local=LocalAgentOptions(cwd=cwd),
        )

    def create_session(
        self,
        *,
        session_id: str,
        cwd: str,
        model: str,
        runtime: str = "local",
        repo_url: str | None = None,
    ) -> ProviderSession:
        agent_cm = self._create_agent(cwd=cwd, model=model, runtime=runtime, repo_url=repo_url)
        agent = agent_cm.__enter__()
        agent_id = getattr(agent, "agent_id", None) or getattr(agent, "agentId", None)
        return ProviderSession(
            session_id=session_id,
            agent_id=agent_id,
            provider_id=self.provider_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            _raw={"agent": agent, "cm": agent_cm},
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
        api_key = self._require_api_key()
        opts = AgentOptions(api_key=api_key, model=model)
        if runtime == "cloud":
            if not repo_url:
                raise ValueError("repo_url is required for cloud runtime")
            opts.cloud = CloudAgentOptions(
                repos=[CloudRepository(url=repo_url)],
                skip_reviewer_request=True,
            )
        else:
            opts.local = LocalAgentOptions(cwd=cwd)
        agent_cm = Agent.resume(agent_id, opts)
        agent = agent_cm.__enter__()
        return ProviderSession(
            session_id=session_id,
            agent_id=agent_id,
            provider_id=self.provider_id,
            cwd=cwd,
            model=model,
            runtime=runtime,
            _raw={"agent": agent, "cm": agent_cm},
        )

    def _agent(self, session: ProviderSession) -> Any:
        if session._closed:
            raise RuntimeError("Session is closed")
        return session._raw["agent"]

    def send(self, session: ProviderSession, message: str) -> RunHandle:
        agent = self._agent(session)
        run = agent.send(message)
        run_id = getattr(run, "id", None) or getattr(run, "run_id", "unknown")
        return RunHandle(run_id=run_id, _provider=self, _session=session, _raw=run)

    def stream(self, handle: RunHandle) -> Iterator[StreamEvent]:
        run = handle._raw
        messages_fn = getattr(run, "messages", None) or getattr(run, "stream", None)
        if messages_fn is None:
            return iter(())
        for message in messages_fn():
            payload = _serialize_message(message)
            yield StreamEvent(type=str(payload.get("type", "message")), payload=payload)

    def wait(self, handle: RunHandle) -> tuple[str, str]:
        run = handle._raw
        result = run.wait()
        status = getattr(result, "status", "finished")
        text = getattr(result, "result", None) or getattr(result, "text", None) or ""
        if callable(text):
            text = text()
        return str(status), str(text or "")

    def cancel(self, handle: RunHandle) -> None:
        run = handle._raw
        if hasattr(run, "supports") and run.supports("cancel"):
            run.cancel()

    def close(self, session: ProviderSession) -> None:
        if session._closed:
            return
        raw = session._raw or {}
        cm = raw.get("cm")
        if cm is not None:
            cm.__exit__(None, None, None)
        session._closed = True
