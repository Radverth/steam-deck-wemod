"""Self-tests for the fake Steam harness, so later phases can trust it."""

from __future__ import annotations

import os
import subprocess
import time
import zipfile

from fakes.fake_nupkg import build_fake_nupkg, sha256
from fakes.steam_root import LAUNCHER_GAME_APPID, RUNTIME_APPID


def run(argv, env, **kw):
    return subprocess.run(argv, env=env, capture_output=True, text=True, **kw)


def test_layout(fake_steam):
    s = fake_steam
    assert (s.home / ".steam" / "root").resolve() == s.steam_root
    vdf = (s.steam_root / "steamapps" / "libraryfolders.vdf").read_text()
    assert f'"path"\t\t"{s.steam_root}"' in vdf
    assert f'"path"\t\t"{s.sd_card}"' in vdf
    acf = s.steam_root / "steamapps" / f"appmanifest_{RUNTIME_APPID}.acf"
    assert '"installdir"\t\t"SteamLinuxRuntime_sniper"' in acf.read_text()
    assert os.access(s.entry_point, os.X_OK)
    assert (
        '"require_tool_appid" "1628350"' in (s.ge_dir / "toolmanifest.vdf").read_text()
    )


def test_sd_card_layout(fake_steam_sd):
    s = fake_steam_sd
    assert s.entry_point.is_relative_to(s.sd_card)
    assert (s.sd_card / "steamapps" / f"appmanifest_{RUNTIME_APPID}.acf").exists()
    assert not (
        s.steam_root / "steamapps" / f"appmanifest_{RUNTIME_APPID}.acf"
    ).exists()
    assert s.game().compatdata.is_relative_to(s.sd_card)


def test_launch_options_chain_runs_and_logs(fake_steam):
    s = fake_steam
    game = s.game()
    assert not (game.compatdata / "pfx" / "drive_c").exists()

    r = run(s.launch_options_argv(game), s.env(game))
    assert r.returncode == 0, r.stderr

    calls = s.read_log()
    assert [c["stub"] for c in calls] == [
        "reaper",
        "steam-launch-wrapper",
        "_v2-entry-point",
        "proton",
    ]
    assert calls[2]["argv"][:2] == ["--verb=waitforexitandrun", "--"]
    proton = calls[3]
    assert proton["argv"] == ["waitforexitandrun", str(game.exe)]
    assert proton["env"]["SteamAppId"] == game.appid
    assert proton["env"]["STEAM_COMPAT_DATA_PATH"] == str(game.compatdata)
    # Proton creates the prefix on a launch verb.
    assert (game.compatdata / "pfx" / "drive_c").is_dir()
    assert "GE-Proton11-7" in (game.compatdata / "version").read_text()


def test_housekeeping_verb_does_not_create_prefix(fake_steam):
    s = fake_steam
    game = s.game()
    argv = s.proton_argv(game, "getcompatpath")
    r = run(argv, s.env(game))
    assert r.returncode == 0
    assert r.stdout.strip() == str(game.exe)
    assert not game.compatdata.exists()


def test_proton_exit_code_is_configurable(fake_steam):
    s = fake_steam
    game = s.game()
    env = s.env(game) | {"FAKE_PROTON_EXIT": "3"}
    assert run(s.proton_argv(game), env).returncode == 3


def test_launcher_game_spawns_child_and_exits(fake_steam, tmp_path):
    s = fake_steam
    game = s.game(LAUNCHER_GAME_APPID)
    pidfile = tmp_path / "child.pid"
    env = s.env(game) | {
        "FAKE_GAME_PIDFILE": str(pidfile),
        "FAKE_CHILD_SECONDS": "2",
    }
    start = time.monotonic()
    r = run([str(game.exe)], env, timeout=5)
    assert r.returncode == 0
    assert time.monotonic() - start < 1.5, "launcher should exit immediately"

    for _ in range(50):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    pid = int(pidfile.read_text())
    os.kill(pid, 0)  # child still alive after the launcher exited

    for _ in range(60):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("child did not exit")


def test_fake_nupkg(tmp_path):
    good = build_fake_nupkg(tmp_path / "good.exe")
    bad = build_fake_nupkg(tmp_path / "bad.exe", tamper=True)
    with zipfile.ZipFile(good) as z:
        lib_entries = [n for n in z.namelist() if n.startswith("lib/net")]
        assert lib_entries[0] == "lib/net45/"
        assert "lib/net45/WeMod.exe" in lib_entries
    assert sha256(good) != sha256(bad)
