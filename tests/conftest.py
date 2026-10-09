"""Global pytest fixtures and test configuration."""

import os
from pathlib import Path
from typing import Generator
import pytest

# Prevent local repository .env from polluting offline unit test environments
os.environ["AGENTCONTRACT_DISABLE_ENV_FILE"] = "1"


@pytest.fixture(autouse=True, scope="session")
def guard_user_codex_home_isolation() -> Generator[None, None, None]:
    """Safeguard: verify that test execution NEVER pollutes user's real ~/.codex."""
    real_codex = Path.home() / ".codex"
    pre_exists = real_codex.exists()
    pre_entries = set(real_codex.iterdir()) if pre_exists else set()

    yield

    if pre_exists:
        post_entries = set(real_codex.iterdir())
        diff = post_entries - pre_entries
        # Ensure no test marketplaces or AgentContract artifacts leaked into user's real ~/.codex
        polluting = [
            p.name for p in diff
            if "agentcontract" in p.name.lower() or "test_market" in p.name.lower() or p.name.endswith(".bak")
        ]
        assert not polluting, f"Test suite leaked artifacts into real user ~/.codex: {polluting}"
