from __future__ import annotations

import pytest

from fakes.http_server import FakeServer
from fakes.steam_root import FakeSteam, build_fake_steam


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never let a test read or write the real HOME / XDG dirs."""
    home = tmp_path / "home" / "deck"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def fake_steam(tmp_path) -> FakeSteam:
    """Fake Steam with runtime and games on internal storage."""
    return build_fake_steam(tmp_path)


@pytest.fixture
def fake_steam_sd(tmp_path) -> FakeSteam:
    """Fake Steam with the runtime and games on the SD card library."""
    return build_fake_steam(tmp_path, runtime_on="sdcard", games_on="sdcard")


@pytest.fixture
def http_server():
    with FakeServer() as server:
        yield server
