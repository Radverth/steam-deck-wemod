"""End to end: install with the real install.sh, then let "Steam" call the
generated compat tool for every launch scenario and check what reached the
fake runtime and fake Proton (their JSON call log)."""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fakes.installer import (
    OFFLINE_ENV,
    REPO,
    repo_zip,
    run_install,
    serve_everything,
)

VERB = "waitforexitandrun"


def install(steam, remote, tmp_path):
    zipped = repo_zip(tmp_path / "repo.zip")
    r = run_install(steam, ["--zip", str(zipped), "--no-proton"], remote.env)
    assert r.returncode == 0, r.stdout + r.stderr
    return steam.steam_root / "compatibilitytools.d" / "WeMod-GE" / "proton"


@pytest.fixture
def remote(http_server, tmp_path):
    return serve_everything(http_server, tmp_path)


@pytest.fixture
def tool(fake_steam, remote, tmp_path):
    return install(fake_steam, remote, tmp_path)


def launch(steam, tool, game, verb=VERB, env=None, path=None, remote=None):
    """What Steam does for a game whose compat tool is ours."""
    if steam.log_path.exists():
        steam.log_path.unlink()
    served = remote.env if remote else {}
    full = {**OFFLINE_ENV, **served, **steam.env(game), **(env or {})}
    full["PATH"] = path or f"{Path(sys.executable).parent}:{os.environ['PATH']}"
    full["FAKE_PYTHON"] = sys.executable
    full.setdefault("XDG_RUNTIME_DIR", str(steam.home.parent / "run"))
    Path(full["XDG_RUNTIME_DIR"]).mkdir(exist_ok=True)
    r = subprocess.run(
        [str(tool), verb, str(game.exe)],
        env=full,
        cwd=game.install_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return steam.read_log()


def status(steam):
    p = steam.home / ".local/share/wemod-deck/status.json"
    return json.loads(p.read_text())["last"]


def plain_calls(steam, game, verb=VERB):
    return [
        (
            "_v2-entry-point",
            [f"--verb={verb}", "--", str(steam.ge_proton), verb, str(game.exe)],
        ),
        ("proton", [verb, str(game.exe)]),
    ]


def calls(log):
    return [(c["stub"], c["argv"]) for c in log]


def wemod_proton_argv(steam):
    bat = steam.home / ".local/share/wemod-deck/bin/wemod-deck.bat"
    return [VERB, "start", "Z:" + str(bat).replace("/", "\\\\"), "game.exe"]


def test_housekeeping_verb_skips_wemod(fake_steam, tool):
    game = fake_steam.game()
    log = launch(fake_steam, tool, game, verb="getcompatpath")
    assert calls(log) == plain_calls(fake_steam, game, "getcompatpath")
    assert not game.compatdata.exists()


def test_first_then_normal_launch_then_offline(fake_steam, tool, remote):
    s, game = fake_steam, fake_steam.game()

    # 1. First launch: plain Proton builds the prefix.
    log = launch(s, tool, game)
    assert calls(log) == plain_calls(s, game)
    assert (game.compatdata / "pfx/drive_c").is_dir()

    # 2. Next launch: prebuilt prefix fetched, WeMod used.
    log = launch(s, tool, game, remote=remote)
    assert [c["stub"] for c in log] == ["_v2-entry-point", "proton"]
    assert log[1]["argv"] == wemod_proton_argv(s)
    assert log[1]["env"]["WEMOD_DECK_EXE"].endswith("\\Wand.exe")
    assert (game.compatdata / "pfx/.wemod_installer").exists()
    assert status(s)["state"] == "ok"

    # 3. Offline: everything is local now.
    remote.server.requests.clear()
    log = launch(s, tool, game)  # OFFLINE_ENV only
    assert log[1]["argv"] == wemod_proton_argv(s)
    assert remote.server.requests == []


def ready_prefix(game):
    (game.compatdata / "pfx/drive_c").mkdir(parents=True)
    (game.compatdata / "pfx/.wemod_installer").write_text("")


def test_opted_out_game(fake_steam, tool):
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    cfg = s.home / ".config/wemod-deck/config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(f'[apps."{game.appid}"]\nenabled = false\n')
    assert calls(launch(s, tool, game)) == plain_calls(s, game)
    assert status(s)["state"] == "plain"


def test_broken_config_still_uses_wemod(fake_steam, tool):
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    cfg = s.home / ".config/wemod-deck/config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("this is [not toml")
    log = launch(s, tool, game)
    assert log[1]["argv"] == wemod_proton_argv(s)
    assert (
        "using defaults"
        in (s.home / ".local/share/wemod-deck/logs/launch.log").read_text()
    )


def test_launcher_missing(fake_steam, tool):
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    shutil.rmtree(s.home / "wemod-deck")
    assert calls(launch(s, tool, game)) == plain_calls(s, game)


def test_broken_launcher_falls_back(fake_steam, tool):
    """A wemod-deck that dies before handing over (here: a syntax error)
    must not stop the game."""
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    (s.home / "wemod-deck/wemod_deck/launch.py").write_text("this is not python(\n")
    assert calls(launch(s, tool, game)) == plain_calls(s, game)


def test_ready_file_cleaned_up(fake_steam, tool):
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    log = launch(s, tool, game)
    assert log[1]["argv"] == wemod_proton_argv(s)
    assert list((s.home.parent / "run").iterdir()) == []


def test_python_missing(fake_steam, tool, tmp_path):
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    bindir = tmp_path / "nopython"
    bindir.mkdir()
    for tool_name in ("bash", "env", "sed", "head", "dirname", "mkdir", "cat"):
        os.symlink(shutil.which(tool_name), bindir / tool_name)
    assert calls(launch(s, tool, game, path=str(bindir))) == plain_calls(s, game)


def test_runtime_missing(fake_steam, tool):
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    s.entry_point.unlink()
    log = launch(s, tool, game)
    assert [c["stub"] for c in log] == ["proton"]
    assert log[0]["argv"] == wemod_proton_argv(s)


def test_runtime_on_sd_card(fake_steam_sd, remote, tmp_path):
    s, game = fake_steam_sd, fake_steam_sd.game()
    tool = install(s, remote, tmp_path)
    ready_prefix(game)
    log = launch(s, tool, game)
    assert log[0]["path"] == str(s.entry_point)
    assert str(s.sd_card) in log[0]["path"]
    assert log[1]["argv"] == wemod_proton_argv(s)


def test_download_failure_starts_game_plain(fake_steam, tool):
    s, game = fake_steam, fake_steam.game()
    (game.compatdata / "pfx/drive_c").mkdir(parents=True)  # no WeMod marker
    log = launch(s, tool, game)  # prefix list unreachable
    assert calls(log) == plain_calls(s, game)
    assert status(s)["state"] == "error"


def test_launch_options_mode(fake_steam, tool):
    """~/wemod-deck/wemod %command% still works."""
    s, game = fake_steam, fake_steam.game()
    ready_prefix(game)
    env = {
        **s.env(game),
        "FAKE_PYTHON": sys.executable,
        "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
    }
    r = subprocess.run(
        [str(s.home / "wemod-deck/wemod"), *s.launch_options_argv(game)],
        env=env,
        cwd=game.install_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    log = s.read_log()
    assert [c["stub"] for c in log] == [
        "reaper",
        "steam-launch-wrapper",
        "_v2-entry-point",
        "proton",
    ]
    assert log[-1]["argv"] == wemod_proton_argv(s)


def test_no_tk_anywhere():
    """No Tk/FreeSimpleGUI in wemod_deck, statically and at import time."""
    for py in (REPO / "wemod_deck").rglob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in ("tkinter", "FreeSimpleGUI"), py
    code = (
        "import sys\n"
        "sys.modules['tkinter'] = sys.modules['FreeSimpleGUI'] = None\n"
        "import pkgutil, importlib, wemod_deck\n"
        "for m in pkgutil.iter_modules(wemod_deck.__path__):\n"
        "    if m.name != '__main__':\n"
        "        importlib.import_module('wemod_deck.' + m.name)\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def test_every_url_has_an_offline_default():
    """A new download URL must be added to OFFLINE_ENV, or tests could
    reach the internet (it happened once: a real 0.9 GB prefix)."""
    from wemod_deck import net

    for key in net.URLS:
        assert f"WEMOD_DECK_URL_{key}" in OFFLINE_ENV, key
    for var in ("WEMOD_DECK_GE_LATEST", "WEMOD_DECK_GE_DL", "WEMOD_DECK_REPO"):
        assert var in (REPO / "install.sh").read_text()
        assert var in OFFLINE_ENV
