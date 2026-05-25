from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable


@dataclass
class StreamEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunHandle:
    run_id: str
    _provider: "AgentProvider"
    _session: "ProviderSession"
    _raw: Any = None


@dataclass
class ProviderSession:
    session_id: str
    agent_id: str | None
    provider_id: str
    cwd: str
    model: str
    runtime: str = "local"
    _raw: Any = None
    _closed: bool = False


@runtime_checkable
class AgentProvider(Protocol):
    provider_id: str

    def create_session(
        self,
        *,
        session_id: str,
        cwd: str,
        model: str,
        runtime: str = "local",
        repo_url: str | None = None,
    ) -> ProviderSession: ...

    def send(self, session: ProviderSession, message: str) -> RunHandle: ...

    def stream(self, handle: RunHandle) -> Iterator[StreamEvent]: ...

    def wait(self, handle: RunHandle) -> tuple[str, str]:
        """Return (status, result_text)."""

    def cancel(self, handle: RunHandle) -> None: ...

    def close(self, session: ProviderSession) -> None: ...

    def resume(
        self,
        *,
        session_id: str,
        agent_id: str,
        cwd: str,
        model: str,
        runtime: str = "local",
        repo_url: str | None = None,
    ) -> ProviderSession: ...
