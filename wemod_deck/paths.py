"""Where wemod-deck keeps its files (XDG base directories)."""

from __future__ import annotations

import os
from pathlib import Path

NAME = "wemod-deck"


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    if value and os.path.isabs(value):
        return Path(value)
    return home() / default


def config_file() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / NAME / "config.toml"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / NAME


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / NAME


def app_dir(app: str) -> Path:
    """Unpacked Wand/WeMod binaries."""
    return data_dir() / "app" / app


def login_dir(app: str) -> Path:
    """Shared login data, symlinked into every prefix."""
    return data_dir() / "login" / app


def bat_file() -> Path:
    return data_dir() / "bin" / "wemod-deck.bat"


def log_file() -> Path:
    return data_dir() / "logs" / "launch.log"


def status_file() -> Path:
    return data_dir() / "status.json"


def displaced_login_dir() -> Path:
    return data_dir() / "displaced-login"


def old_prefixes_dir() -> Path:
    return data_dir() / "old-prefixes"
