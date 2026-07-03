"""Provider registry."""

from __future__ import annotations

from cursor_subagent.providers.base import AgentProvider
from cursor_subagent.providers.cursor_composer import CursorComposerProvider
from cursor_subagent.providers.zai_coding_plan import ZaiCodingPlanProvider

_PROVIDERS: dict[str, AgentProvider] = {
    "cursor-composer": CursorComposerProvider(),
    "zai-coding-plan": ZaiCodingPlanProvider(),
}


def get_provider(provider_id: str) -> AgentProvider:
    provider = _PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Unknown provider: {provider_id}")
    return provider


def list_providers() -> list[str]:
    return list(_PROVIDERS.keys())


def default_model(provider_id: str) -> str:
    provider = get_provider(provider_id)
    return getattr(provider, "default_model", "composer-2.5")
