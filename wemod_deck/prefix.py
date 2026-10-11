"""Prebuilt WeMod prefixes: pick, download, unpack without touching saves.

A prebuilt prefix is a zip laid out relative to ``compatdata/<appid>/``
(``version``, ``pfx/...``) from DeckCheatz/BuiltPrefixes-dev (tags
``PfxVer<major>.<minor>``). It already contains .NET; the WeMod marker is
``pfx/.wemod_installer``.

Save protection until Phase 2's backups:
* under ``pfx/drive_c/users/`` existing files are **never** overwritten,
  only missing files are added;
* nothing is written through a symlink to outside the prefix (the shared
  login symlink, ``dosdevices/z:``), and only the expected ``dosdevices``
  links are created;
* the registry hives are backed up to ``compatdata/wemod-deck-backup/``
  before being replaced, and ``user.reg`` keeps every key the prebuilt hive
  lacks (game settings and some saves live there);
* nothing is ever deleted; the marker is written last, so an interrupted
  unpack is simply retried on the next launch.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import net, paths, steam
from .status import log

MARKER = "pfx/.wemod_installer"
BACKUP_DIR = "wemod-deck-backup"
# Wine registry hives. They are replaced (the prebuilt ones carry .NET's
# registration and DLL overrides) but backed up first, and user.reg (HKCU,
# where games keep settings and sometimes saves) gets every key back that
# the prebuilt hive doesn't have.
REGISTRY_FILES = ("pfx/system.reg", "pfx/user.reg", "pfx/userdef.reg")
MERGED_REGISTRY_FILES = ("pfx/user.reg",)
RELEASES_TTL = 24 * 3600
_SAFE_LINKS = {"pfx/dosdevices/c:": "../drive_c", "pfx/dosdevices/z:": "/"}
_SPACE_MARGIN = 256 * 1024 * 1024


class PrefixError(RuntimeError):
    pass


def has_wemod(compatdata: Path) -> bool:
    return (compatdata / MARKER).is_file()


# ----------------------------------------------------------------- releases --


def _release_version(tag: str) -> tuple[int, int] | None:
    if not tag.startswith("PfxVer"):
        return None
    return steam.parse_proton_version(tag[len("PfxVer") :])


def pick_release(releases: list[dict], want: tuple[int, int]) -> dict | None:
    """Closest prebuilt prefix, in upstream's priority order: exact; same
    major, nearest lower minor; same major, nearest higher minor; nearest
    lower major; nearest higher major."""
    best, best_key = None, None
    for rel in releases:
        version = _release_version(str(rel.get("tag_name", "")))
        assets = rel.get("assets") or []
        if not version or not assets or not assets[0].get("browser_download_url"):
            continue
        major, minor = version
        if version == want:
            key = (0, 0)
        elif major == want[0] and minor < want[1]:
            key = (1, want[1] - minor)
        elif major == want[0]:
            key = (2, minor - want[1])
        elif major < want[0]:
            key = (3, (want[0] - major) * 1000 - minor)
        else:
            key = (4, (major - want[0]) * 1000 + minor)
        if best_key is None or key < best_key:
            best, best_key = {**rel, "_version": version}, key
    return best


def releases(*, now: float | None = None) -> list[dict]:
    """Release list, cached for 24 h (GitHub API rate limits). A stale cache
    is used if GitHub can't be reached."""
    now = time.time() if now is None else now
    cache = paths.cache_dir() / "prefix-releases.json"
    cached = None
    try:
        cached = json.loads(cache.read_text())
        if now - float(cached["fetched"]) < RELEASES_TTL:
            return cached["releases"]
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    try:
        data = net.get_json(net.url("PREFIX_RELEASES"), timeout=10)
        if not isinstance(data, list):
            raise net.DownloadError("unexpected GitHub API response")
    except net.DownloadError as e:
        if cached:
            log.warning("using cached prefix list: %s", e)
            return cached["releases"]
        raise
    slim = [
        {
            "tag_name": r.get("tag_name"),
            "assets": [
                {
                    "name": a.get("name"),
                    "browser_download_url": a.get("browser_download_url"),
                    "size": a.get("size", 0),
                }
                for a in (r.get("assets") or [])[:1]
            ],
        }
        for r in data
        if isinstance(r, dict)
    ]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"fetched": now, "releases": slim}))
    return slim


# ------------------------------------------------------------------- unpack --


def _check_space(where: Path, needed: int, what: str) -> None:
    free = shutil.disk_usage(where).free
    if free < needed + _SPACE_MARGIN:
        raise PrefixError(
            f"not enough space for {what}: need {needed // 2**20} MB, "
            f"{free // 2**20} MB free"
        )


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def unpack(zip_path: Path, compatdata: Path) -> dict:
    """Unpack a prebuilt prefix over ``compatdata`` following the rules in
    the module docstring. Returns counts for the log."""
    root = compatdata.resolve()
    counts = {"written": 0, "kept_user_files": 0, "skipped": 0, "links": 0}
    try:
        z = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as e:
        raise PrefixError(f"bad prefix archive {zip_path.name}: {e}") from e
    with z:
        infos = z.infolist()
        names = {i.filename.rstrip("/") for i in infos}
        if MARKER not in names:
            raise PrefixError(f"{zip_path.name} is not a WeMod prefix (no marker)")
        _check_space(root, sum(i.file_size for i in infos), "the prefix")

        marker_info = None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for info in infos:
            raw = info.filename.rstrip("/")
            rel = PurePosixPath(raw)
            # Normalised ("pfx/./a//b" -> "pfx/a/b") so every check below sees
            # the path that is actually written.
            name = "/".join(rel.parts)
            through_link = any(name.startswith(link + "/") for link in _SAFE_LINKS)
            if rel.is_absolute() or ".." in rel.parts or not name or through_link:
                counts["skipped"] += 1
                continue
            if name == MARKER:
                marker_info = info
                continue
            target = compatdata / name
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                _make_link(z, info, name, target, counts)
                continue
            if not _inside(root, target.parent):
                counts["skipped"] += 1
                continue
            if info.is_dir():
                if not target.is_symlink():
                    target.mkdir(parents=True, exist_ok=True)
                continue
            user_file = name.startswith("pfx/drive_c/users/")
            if target.is_symlink() or target.exists():
                if user_file or target.is_dir():
                    counts["kept_user_files" if user_file else "skipped"] += 1
                    continue
            old_registry = None
            if name in REGISTRY_FILES and target.is_file() and not target.is_symlink():
                old_registry = _backup(compatdata, name, stamp)
                counts["registry_backups"] = counts.get("registry_backups", 0) + 1
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".wemod-deck-part")
            with z.open(info) as src, open(part, "wb") as out:
                shutil.copyfileobj(src, out)
            if old_registry is not None and name in MERGED_REGISTRY_FILES:
                merged = merge_registry(
                    part.read_text("utf-8", "surrogateescape"),
                    old_registry.read_text("utf-8", "surrogateescape"),
                )
                part.write_text(merged, "utf-8", "surrogateescape")
            os.replace(part, target)
            counts["written"] += 1

        _fix_dosdevices(compatdata)
        (compatdata / MARKER).parent.mkdir(parents=True, exist_ok=True)
        (compatdata / MARKER).write_bytes(z.read(marker_info) if marker_info else b"")
    return counts


def _backup(compatdata: Path, name: str, stamp: str) -> Path:
    """Copy ``compatdata/name`` to ``compatdata/wemod-deck-backup/<stamp>/name``."""
    dest = compatdata / BACKUP_DIR / stamp / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(compatdata / name, dest)
    return dest


def _registry_sections(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Split a Wine ``.reg`` file into its preamble and ``[key] stamp``
    sections. Section names compare case-insensitively, like the registry."""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("[") and "]" in line:
            key = line[1 : line.rindex("]")].lower()
            sections.append((key, [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)
    return preamble, sections


def merge_registry(new: str, old: str) -> str:
    """``new`` plus every section of ``old`` that ``new`` lacks. Keys that
    exist in both keep the prebuilt (``new``) values."""
    _, new_sections = _registry_sections(new)
    _, old_sections = _registry_sections(old)
    have = {key for key, _ in new_sections}
    extra = [lines for key, lines in old_sections if key not in have]
    if not extra:
        return new
    out = new if new.endswith("\n") else new + "\n"
    for lines in extra:
        block = "".join(lines)
        out += block if block.endswith("\n") else block + "\n"
    return out


def _make_link(z, info, name: str, target: Path, counts: dict) -> None:
    link_to = z.read(info).decode("utf-8", "replace")
    if _SAFE_LINKS.get(name) != link_to:
        counts["skipped"] += 1
        return
    if target.is_symlink() and os.readlink(target) == link_to:
        return
    if target.exists() or target.is_symlink():
        counts["skipped"] += 1  # never replace something that is there
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(link_to, target)
    counts["links"] += 1


def _fix_dosdevices(compatdata: Path) -> None:
    """Make sure c: and z: exist (upstream PR #252); never replace anything."""
    for name, link_to in _SAFE_LINKS.items():
        target = compatdata / name
        if not target.exists() and not target.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(link_to, target)


# ------------------------------------------------------------------ install --


def ensure(compatdata: Path, proton: str) -> bool:
    """Make sure the prefix has WeMod's prerequisites. Returns True if a
    prebuilt prefix was unpacked. Raises PrefixError/DownloadError."""
    if has_wemod(compatdata):
        return False
    want = steam.prefix_proton_version(compatdata) or steam.parse_proton_version(
        os.path.basename(os.path.dirname(proton))
    )
    if not want:
        raise PrefixError("cannot tell which Proton version built this prefix")
    rel = pick_release(releases(), want)
    if not rel:
        raise PrefixError("no prebuilt prefix available")
    asset = rel["assets"][0]
    zips = paths.cache_dir() / "prefixes"
    zips.mkdir(parents=True, exist_ok=True)
    zip_path = zips / os.path.basename(asset.get("name") or "prefix.zip")
    if not zip_path.is_file():
        _check_space(zips, int(asset.get("size") or 0), "the prefix download")
        log.info(
            "downloading prebuilt prefix %s for Proton %d.%d",
            rel["tag_name"],
            *want,
        )
        net.download(asset["browser_download_url"], zip_path, timeout=60)
    counts = unpack(zip_path, compatdata)
    log.info("unpacked %s into %s: %s", zip_path.name, compatdata, counts)
    # Keep only the zip just used: one ~0.9 GB file instead of one per version.
    for other in zips.glob("*.zip"):
        if other != zip_path:
            other.unlink(missing_ok=True)
    return True


# -------------------------------------------------------------- reset (CLI) --


def reset_prefix(steam_root: Path, appid: str, *, now: float | None = None) -> list:
    """Move ``compatdata/<appid>`` aside (same library, so a cheap rename)
    so Steam builds a fresh prefix next launch. Nothing is deleted."""
    if not appid.isdigit():
        raise PrefixError("AppID must be a number")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    moved = []
    for cd in steam.find_compatdata(steam_root, appid):
        dest = cd.parent.parent / "compatdata-wemod-deck-old" / f"{appid}-{stamp}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        cd.rename(dest)
        moved.append((cd, dest))
    return moved


def reset_prefix_cli(appid: str) -> int:
    root = steam.find_steam_root()
    if root is None:
        log.error("Steam not found")
        return 1
    try:
        moved = reset_prefix(root, appid)
    except (PrefixError, OSError) as e:
        log.error("%s", e)
        return 1
    if not moved:
        print(f"No prefix found for AppID {appid}.")
        return 1
    for src, dest in moved:
        print(f"Moved {src}\n   to {dest}")
        print(f"To undo: mv '{dest}' '{src}'")
    print(
        "Steam creates a fresh prefix on the next launch "
        "(that first launch runs without WeMod)."
    )
    return 0
