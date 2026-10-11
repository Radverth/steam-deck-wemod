"""Characterisation tests: how upstream 1.543 turns Steam's argv into the
command it runs. These pin *current* behaviour (bugs included) so Phase 1's
rewrite can be compared against it. Upstream ``src/`` is not modified."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fakes.steam_root import LAUNCHER_GAME_APPID

REPO = Path(__file__).resolve().parent.parent
DRIVER = Path(__file__).resolve().parent / "upstream_driver.py"
VERB = "waitforexitandrun"


@pytest.fixture
def upstream_src(tmp_path) -> Path:
    dest = tmp_path / "launcher" / "src"
    shutil.copytree(
        REPO / "src",
        dest,
        ignore=shutil.ignore_patterns(
            "wemod.conf", "wemod.log", ".cache", "wemod_venv", "__pycache__"
        ),
    )
    return dest


def run_upstream(src: Path, argv: list[str], env: dict, cwd: Path) -> dict:
    out = src.parent / "result.json"
    r = subprocess.run(
        [sys.executable, str(DRIVER), str(src), str(out), *argv],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.exists(), f"driver crashed:\n{r.stdout}\n{r.stderr}"
    return json.loads(out.read_text())


def bat(src: Path) -> list[str]:
    return ["start", "Z:" + str(src / "wemod.bat").replace(os.sep, "\\\\")]


def popups(result: dict) -> list:
    return [b for b in result["blocked"] if b[0] != "subprocess.run"]


def test_launch_options_mode(fake_steam, upstream_src):
    """``~/wemod-launcher/wemod %command%`` with GE-Proton selected."""
    s = fake_steam
    game = s.game()
    argv = s.launch_options_argv(game)
    res = run_upstream(upstream_src, argv, s.env(game), game.install_dir)

    assert res["error"] is None
    assert popups(res) == []
    proton_at = argv.index(str(s.ge_proton))
    assert res["init"] == [str(s.ge_proton), False]
    assert res["final"] == [
        *argv[:proton_at],  # reaper ... entry-point --verb=... --
        str(s.ge_proton),
        VERB,
        *bat(upstream_src),
        "game.exe",
    ]


def test_compat_tool_mode(fake_steam, upstream_src):
    """argv the reference compat-tool wrapper passes:
    ``wemod <entry-point> --verb=V -- <GE proton> V <exe>``, with the GE dir
    prepended to STEAM_COMPAT_TOOL_PATHS."""
    s = fake_steam
    game = s.game()
    argv = s.proton_argv(game)
    env = s.env(game)
    env["STEAM_COMPAT_TOOL_PATHS"] = f"{s.ge_dir}:{env['STEAM_COMPAT_TOOL_PATHS']}"
    res = run_upstream(upstream_src, argv, env, game.install_dir)

    assert res["error"] is None
    assert popups(res) == []
    assert res["final"] == [
        str(s.entry_point),
        f"--verb={VERB}",
        "--",
        str(s.ge_proton),
        VERB,
        *bat(upstream_src),
        "game.exe",
    ]


def test_sd_card_library(fake_steam_sd, upstream_src):
    """Runtime, game and compatdata all on the SD card."""
    s = fake_steam_sd
    game = s.game(LAUNCHER_GAME_APPID)
    argv = s.launch_options_argv(game)
    res = run_upstream(upstream_src, argv, s.env(game), game.install_dir)

    assert res["error"] is None
    assert popups(res) == []
    assert str(s.entry_point) in res["final"]  # entry point found on the SD card
    assert res["final"][-5:] == [
        str(s.ge_proton),
        VERB,
        *bat(upstream_src),
        "Launcher.exe",
    ]


def test_custom_runner(fake_steam, upstream_src, tmp_path):
    """Non-Proton runner: ``wemod /opt/wine/bin/wine game.exe`` with
    WINEPREFIX and WINE set and no Steam compat vars. No verb is used."""
    s = fake_steam
    game = s.game()
    wine = tmp_path / "opt" / "wine" / "bin" / "wine"
    wine.parent.mkdir(parents=True)
    wine.write_text("#!/bin/sh\n")
    env = {
        "HOME": str(s.home),
        "PATH": os.environ["PATH"],
        "WINEPREFIX": str(tmp_path / "wineprefix"),
        "WINE": str(wine),
    }
    res = run_upstream(upstream_src, [str(wine), str(game.exe)], env, game.install_dir)

    assert res["error"] is None
    assert popups(res) == []
    assert res["init"] == [str(wine), True]
    assert res["final"] == [str(wine), *bat(upstream_src), "game.exe"]


def test_tool_path_mismatch_falls_back_to_delimiter_split(fake_steam, upstream_src):
    """If STEAM_COMPAT_TOOL_PATHS doesn't name Proton's dir exactly (e.g. a
    symlinked path), upstream falls back to splitting on the last ``--``."""
    s = fake_steam
    game = s.game()
    argv = s.launch_options_argv(game)
    env = s.env(game) | {"STEAM_COMPAT_TOOL_PATHS": "/nonexistent/tool"}
    res = run_upstream(upstream_src, argv, env, game.install_dir)

    assert res["error"] is None
    assert res["final"] == [
        *argv[: argv.index(str(s.ge_proton))],
        str(s.ge_proton),
        VERB,
        *bat(upstream_src),
        "game.exe",
    ]


def test_known_bug_delimiter_branch_custom_runner_crashes(fake_steam, upstream_src):
    """Known bug: the delimiter branch checks ``PROTON[1]`` (a character of
    the path) instead of the next argument for a ".", so a custom runner after
    ``--`` keeps the Proton verb and indexes past the end of argv."""
    s = fake_steam
    game = s.game()
    wine = "/opt/wine/bin/wine"
    env = s.env(game) | {"STEAM_COMPAT_TOOL_PATHS": "/nonexistent/tool"}
    res = run_upstream(upstream_src, ["--", wine, "game.exe"], env, game.install_dir)
    assert res["error"] is not None
    assert res["error"].startswith("IndexError")


@pytest.mark.xfail(strict=True, reason="upstream bug, fixed by Phase 1 parser")
def test_desired_delimiter_branch_custom_runner(fake_steam, upstream_src):
    s = fake_steam
    game = s.game()
    wine = "/opt/wine/bin/wine"
    env = s.env(game) | {"STEAM_COMPAT_TOOL_PATHS": "/nonexistent/tool"}
    res = run_upstream(upstream_src, ["--", wine, "game.exe"], env, game.install_dir)
    assert res["error"] is None
    assert res["final"] == ["--", wine, *bat(upstream_src), "game.exe"]


def test_upstream_unpacks_fake_nupkg(upstream_src, tmp_path):
    """The fake installer is close enough for upstream's ``unpack_wemod``."""
    from fakes.fake_nupkg import build_fake_nupkg

    setup_exe = build_fake_nupkg(tmp_path / "wemod_setup.exe")
    dest = tmp_path / "wemod_bin"
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); from setup import unpack_wemod;"
        "sys.exit(0 if unpack_wemod(sys.argv[2], sys.argv[3], sys.argv[4]) else 1)"
    )
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(upstream_src),
            str(setup_exe),
            str(tmp_path / "scratch"),
            str(dest),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert (dest / "WeMod.exe").read_bytes() == b"MZ fake WeMod.exe\n"
    assert (dest / "resources" / "app.asar").exists()
