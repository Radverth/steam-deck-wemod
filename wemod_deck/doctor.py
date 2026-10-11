"""``wemod-deck doctor``: check the installation, say what's wrong."""

from __future__ import annotations

import shlex
import shutil
import sys
from pathlib import Path

from . import app, backup, config, paths, status, steam
from .config import Config

TOOL_NAME = "WeMod-GE"
OK, WARN, FAIL = "OK", "WARN", "FAIL"


def read_tool_conf(path: Path) -> dict[str, str]:
    """``KEY=value`` lines written by install.sh with ``printf %q``."""
    out = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.isidentifier():
            parts = shlex.split(value) if value else [""]
            out[key] = parts[0] if parts else ""
    return out


def checks(cfg: Config) -> list[tuple[str, str, str]]:
    res: list[tuple[str, str, str]] = []

    def add(level: str, label: str, detail: str) -> None:
        res.append((level, label, detail))

    py = "{}.{}".format(*sys.version_info[:2])
    add(OK if sys.version_info >= (3, 9) else FAIL, "Python", py)

    _, warnings = config.load(paths.config_file())
    if warnings:
        for w in warnings:
            add(WARN, "Config", w)
    else:
        add(OK, "Config", f"app = {cfg.app}, enabled = {cfg.enabled}")

    root = steam.find_steam_root()
    if root is None:
        add(FAIL, "Steam", "Steam folder not found")
    else:
        libs = steam.library_paths(root)
        add(OK, "Steam", f"{root} ({len(libs)} libraries)")
        res.extend(_tool_checks(root))

    exe = app.exe_path(cfg.app)
    if exe.is_file():
        add(OK, cfg.app, f"{app.installed_version(cfg.app) or '?'} at {exe}")
    else:
        add(WARN, cfg.app, "not downloaded yet (run: wemod-deck setup)")
    if exe.is_file():
        dll = exe.parent / "DWriteCore.dll"
        add(
            OK if dll.is_file() else WARN,
            "DWriteCore.dll",
            "present" if dll.is_file() else "missing (Map panel may stay blank)",
        )

    last = status.read_status().get("last")
    if last:
        level = WARN if last.get("state") == "error" else OK
        add(
            level,
            "Last launch",
            f"AppID {last.get('appid')} {last.get('state')}: {last.get('message')}"
            f" ({last.get('time')})",
        )
    else:
        add(OK, "Last launch", "none yet")

    backups = backup.list_backups()
    on_disk = sum(b.archive.stat().st_size for b in backups if b.archive.exists())
    add(OK, "Save backups", f"{len(backups)}, {on_disk / 2**20:.0f} MB on disk")
    method = backup.compression()
    add(
        OK if method != "gzip" else WARN,
        "Compression",
        method if method != "gzip" else "zstd not found, using gzip (bigger backups)",
    )
    for appid in backup.all_pending():
        add(WARN, "Pending restore", f"AppID {appid}: saves go back on its next launch")

    free = shutil.disk_usage(paths.home()).free
    add(OK if free > 2 * 2**30 else WARN, "Free space", f"{free // 2**30} GB in home")
    return res


def _tool_checks(root: Path) -> list[tuple[str, str, str]]:
    res = []
    tool = root / "compatibilitytools.d" / TOOL_NAME
    if not (tool / "proton").is_file() or not (tool / "tool.conf").is_file():
        return [(FAIL, "Compat tool", f"not installed in {tool} (run install.sh)")]
    res.append((OK, "Compat tool", str(tool)))

    if steam.required_runtime_appid(tool / "toolmanifest.vdf"):
        res.append(
            (
                FAIL,
                "Tool manifest",
                "requires a runtime: Steam would run wemod-deck inside the "
                "container. Re-run install.sh.",
            )
        )

    conf = read_tool_conf(tool / "tool.conf")
    ge = Path(conf.get("GE_PROTON", ""))
    if ge.is_file():
        res.append((OK, "GE-Proton", str(ge.parent.name)))
    else:
        res.append((FAIL, "GE-Proton", f"{ge} is missing (re-run install.sh)"))

    launcher = Path(conf.get("WEMOD_DECK_DIR", "")) / "wemod-deck"
    if not launcher.is_file():
        res.append((FAIL, "Launcher", f"{launcher} is missing (re-run install.sh)"))

    rt_appid = conf.get("RUNTIME_APPID", "")
    if rt_appid:
        ep = steam.find_runtime_entry_point(root, rt_appid)
        if ep:
            res.append((OK, "Steam Linux Runtime", str(ep)))
        else:
            res.append(
                (
                    WARN,
                    "Steam Linux Runtime",
                    f"AppID {rt_appid} not installed; games run outside the "
                    "container (launch any Proton game once to install it)",
                )
            )
    return res


def main(cfg: Config) -> int:
    results = checks(cfg)
    width = max(len(label) for _, label, _ in results)
    for level, label, detail in results:
        print(f"{level:<4}  {label:<{width}}  {detail}")
    failed = any(level == FAIL for level, _, _ in results)
    print("\nProblems found." if failed else "\nAll good.")
    return 1 if failed else 0
