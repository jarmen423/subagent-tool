"""Provider registry."""

from __future__ import annotations

from cursor_subagent.providers.base import AgentProvider
from cursor_subagent.providers.cursor_composer import CursorComposerProvider

_PROVIDERS: dict[str, AgentProvider] = {
    "cursor-composer": CursorComposerProvider(),
}


def get_provider(provider_id: str) -> AgentProvider:
    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_id}")
    return provider


def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())
