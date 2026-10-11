"""Share one Wand/WeMod login between all prefixes.

Each prefix's ``AppData/Roaming/<Wand|WeMod>`` becomes a symlink to
``~/.local/share/wemod-deck/login/<app>/``. Both names are linked so Wand
can find an old WeMod login if it migrates one.

No prompts and no deletion: if a prefix holds its own login and the
central one is already in use, the central one wins and the prefix copy
is **moved** to ``displaced-login/``.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from . import paths
from .status import log

ROAMING_NAMES = {"wand": "Wand", "wemod": "WeMod"}
ROAMING = Path("pfx/drive_c/users/steamuser/AppData/Roaming")
LEGACY_DIR = Path("wemod-launcher") / "wemod_data"  # upstream, under HOME


def _has_content(path: Path) -> bool:
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _displace(path: Path, appid: str, app: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = paths.displaced_login_dir() / f"{appid}-{app}-{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def link_logins(compatdata: Path, appid: str) -> list[str]:
    """Point the prefix's roaming dirs at the central login dirs. Returns
    a list of human-readable actions for the log."""
    actions = []
    for app, name in ROAMING_NAMES.items():
        central = paths.login_dir(app)
        central.mkdir(parents=True, exist_ok=True)
        roaming = compatdata / ROAMING / name
        target = str(central)

        if roaming.is_symlink():
            if os.readlink(roaming) == target:
                continue
            roaming.unlink()  # only the link; whatever it pointed to stays
            actions.append(f"{name}: re-pointed old link")
        elif roaming.is_dir() and _has_content(roaming):
            if _has_content(central):
                dest = _displace(roaming, appid, app)
                actions.append(f"{name}: prefix login moved to {dest}")
            else:
                for child in roaming.iterdir():
                    shutil.move(str(child), str(central / child.name))
                roaming.rmdir()
                actions.append(f"{name}: prefix login became the shared login")
        elif roaming.is_dir():
            roaming.rmdir()
        elif roaming.exists():
            dest = _displace(roaming, appid, app)
            actions.append(f"{name}: unexpected file moved to {dest}")

        roaming.parent.mkdir(parents=True, exist_ok=True)
        roaming.symlink_to(target)
        actions.append(f"{name}: linked")
    return actions


def migrate_legacy() -> list[str]:
    """Copy (never move) login and binaries from an upstream
    ``~/wemod-launcher`` install, once. The old folder is left as is."""
    old = paths.home() / LEGACY_DIR
    marker = paths.data_dir() / ".migrated-from-wemod-launcher"
    if marker.exists() or not old.is_dir():
        return []
    actions = []
    pairs = [
        (old / "wemod_login", paths.login_dir("wemod")),
        (old / "wemod_bin", paths.app_dir("wemod")),
    ]
    for src, dest in pairs:
        if _has_content(src) and not _has_content(dest):
            if dest.is_dir():
                dest.rmdir()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dest, symlinks=True)
            actions.append(f"copied {src} to {dest}")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(time.strftime("%Y-%m-%dT%H:%M:%S\n"))
    for a in actions:
        log.info("migration: %s", a)
    return actions
