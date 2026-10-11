from __future__ import annotations

import pytest
from fakes.steam_root import FakeSteam, build_fake_steam


@pytest.fixture
def fake_steam(tmp_path) -> FakeSteam:
    """Fake Steam with runtime and games on internal storage."""
    return build_fake_steam(tmp_path)


@pytest.fixture
def fake_steam_sd(tmp_path) -> FakeSteam:
    """Fake Steam with the runtime and games on the SD card library."""
    return build_fake_steam(tmp_path, runtime_on="sdcard", games_on="sdcard")
