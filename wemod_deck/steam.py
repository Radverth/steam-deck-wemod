"""Read Steam's own files: KeyValues (VDF/ACF), libraries, installed apps.

Native Steam on SteamOS only (no Flatpak paths, see scope non-goals).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import paths

RUNTIME_ENTRY_POINT = "_v2-entry-point"

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|([^\s{}"]+)')


class VdfError(ValueError):
    pass


def parse_vdf(text: str) -> dict:
    """Parse Valve KeyValues text into nested dicts. Keys are kept as
    written; later duplicates win. Conditionals like ``[$WIN32]`` are not
    used by the files we read and are rejected."""
    tokens: list[tuple[str, str]] = []
    for m in _TOKEN.finditer(text):
        quoted, brace, bare = m.groups()
        if quoted is not None:
            tokens.append(("s", quoted.replace('\\"', '"').replace("\\\\", "\\")))
        elif brace:
            tokens.append((brace, brace))
        elif bare is not None:
            tokens.append(("s", bare))

    def parse_block(i: int, nested: bool) -> tuple[dict, int]:
        out: dict = {}
        while i < len(tokens):
            kind, value = tokens[i]
            if kind == "}":
                if not nested:
                    raise VdfError("unexpected '}'")
                return out, i + 1
            if kind != "s":
                raise VdfError("expected a key")
            if i + 1 >= len(tokens):
                raise VdfError(f"key {value!r} has no value")
            nkind, nvalue = tokens[i + 1]
            if nkind == "{":
                out[value], i = parse_block(i + 2, True)
            elif nkind == "s":
                out[value] = nvalue
                i += 2
            else:
                raise VdfError(f"unexpected '}}' after {value!r}")
        if nested:
            raise VdfError("missing '}'")
        return out, i

    return parse_block(0, False)[0]


def read_vdf(path: Path) -> dict:
    return parse_vdf(path.read_text(encoding="utf-8", errors="replace"))


def find_steam_root() -> Path | None:
    """Steam's install dir: Steam's own env var first, then the usual
    SteamOS locations."""
    candidates = []
    env = os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH")
    if env:
        candidates.append(Path(env))
    home = paths.home()
    candidates += [
        home / ".steam" / "root",
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
    ]
    for c in candidates:
        if (c / "steamapps").is_dir():
            return c.resolve()
    return None


def library_paths(steam_root: Path) -> list[Path]:
    """Every Steam library (internal storage, SD card, ...), Steam root first.
    Unreadable ``libraryfolders.vdf`` just means "root only"."""
    libs = [steam_root]
    try:
        data = read_vdf(steam_root / "steamapps" / "libraryfolders.vdf")
    except (OSError, VdfError):
        data = {}
    folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
    for entry in folders.values():
        path = entry.get("path") if isinstance(entry, dict) else entry
        if isinstance(path, str) and path:
            libs.append(Path(path))
    seen, out = set(), []
    for lib in libs:
        key = os.path.realpath(lib)
        if key not in seen and (lib / "steamapps").is_dir():
            seen.add(key)
            out.append(lib)
    return out


def find_app_install(steam_root: Path, appid: str) -> Path | None:
    """Install dir of ``appid`` from ``appmanifest_<appid>.acf`` in any library."""
    for lib in library_paths(steam_root):
        acf = lib / "steamapps" / f"appmanifest_{appid}.acf"
        try:
            installdir = read_vdf(acf).get("AppState", {}).get("installdir")
        except (OSError, VdfError):
            continue
        if installdir:
            path = lib / "steamapps" / "common" / installdir
            if path.is_dir():
                return path
    return None


def find_runtime_entry_point(steam_root: Path, appid: str) -> Path | None:
    """``_v2-entry-point`` of a Steam Linux Runtime (e.g. 1628350 = sniper)."""
    install = find_app_install(steam_root, appid)
    if install is None:
        return None
    ep = install / RUNTIME_ENTRY_POINT
    return ep if os.access(ep, os.X_OK) else None


def find_compatdata(steam_root: Path, appid: str) -> list[Path]:
    """Existing ``compatdata/<appid>`` dirs (normally exactly one)."""
    return [
        lib / "steamapps" / "compatdata" / appid
        for lib in library_paths(steam_root)
        if (lib / "steamapps" / "compatdata" / appid).is_dir()
    ]


def required_runtime_appid(toolmanifest: Path) -> str | None:
    """``require_tool_appid`` from a compat tool's ``toolmanifest.vdf``."""
    try:
        value = read_vdf(toolmanifest).get("manifest", {}).get("require_tool_appid")
    except (OSError, VdfError):
        return None
    return value if isinstance(value, str) and value.isdigit() else None


def prefix_proton_version(compatdata: Path) -> tuple[int, int] | None:
    """Proton version that built a prefix, from ``compatdata/<id>/version``
    (e.g. ``1700000000 GE-Proton11-7`` → ``(11, 7)``)."""
    try:
        text = (compatdata / "version").read_text(errors="replace")
    except OSError:
        return None
    return parse_proton_version(text)


def parse_proton_version(text: str) -> tuple[int, int] | None:
    """``GE-Proton11-7`` → (11, 7); ``GE-Proton9-20`` → (9, 20);
    ``proton-9.0-4`` → (9, 0). A leading timestamp is ignored."""
    words = text.split()
    name = words[-1] if words else ""
    m = re.search(r"(\d+)[.-](\d+)", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)", name)
    return (int(m.group(1)), 0) if m else None
