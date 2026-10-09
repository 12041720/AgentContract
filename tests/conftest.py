"""Global pytest fixtures and test configuration."""

import hashlib
import os
from pathlib import Path
from typing import Generator
import pytest

# Prevent local repository .env from polluting offline unit test environments
os.environ["AGENTCONTRACT_DISABLE_ENV_FILE"] = "1"


def _hash_file(p: Path) -> str | None:
    if p.is_file():
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            return None
    return None


@pytest.fixture(autouse=True, scope="session")
def guard_user_codex_home_isolation() -> Generator[None, None, None]:
    """Safeguard: verify that test execution NEVER pollutes or mutates user's real ~/.codex."""
    real_codex = Path.home() / ".codex"
    pre_exists = real_codex.exists()

    tracked_files = ["config.toml", "hooks.json", "auth.json"]
    pre_hashes = {f: _hash_file(real_codex / f) for f in tracked_files} if pre_exists else {}
    pre_entries = set(real_codex.iterdir()) if pre_exists else set()

    yield

    if pre_exists:
        # 1. Assert in-place mutations did not occur on tracked files
        for f, pre_h in pre_hashes.items():
            if pre_h is not None:
                post_h = _hash_file(real_codex / f)
                assert post_h == pre_h, f"Test suite mutated user's real ~/.codex/{f} in-place!"

        # 2. Assert no new artifacts leaked
        post_entries = set(real_codex.iterdir())
        diff = post_entries - pre_entries
        polluting = [
            p.name for p in diff
            if "agentcontract" in p.name.lower() or "test_market" in p.name.lower() or p.name.endswith(".bak")
        ]
        assert not polluting, f"Test suite leaked artifacts into real user ~/.codex: {polluting}"
