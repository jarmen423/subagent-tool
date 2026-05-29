import os

import pytest


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("CURSOR_API_KEY"), reason="CURSOR_API_KEY not set")
def test_live_spawn_requires_api_key() -> None:
    """Smoke marker for live Cursor integration; run manually with API key."""
    assert os.environ["CURSOR_API_KEY"].startswith("cursor_")
