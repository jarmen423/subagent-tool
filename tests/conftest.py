from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def disable_nats(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBAGENT_DISABLE_NATS", "1")
