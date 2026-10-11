"""Unit tests for launch decisions (no subprocesses; see test_e2e.py)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fakes.fake_prefix import build_fake_prefix_zip
from wemod_deck import app, backup, launch, login, paths, status
from wemod_deck import argv as A
from wemod_deck.config import Config

VERB = "waitforexitandrun"


@pytest.fixture
def ready(fake_steam, monkeypatch):
    """Game with a Proton-built prefix that already has WeMod, app installed,
    DWriteCore present: a launch needs no network at all."""
    game = fake_steam.game()
    cd = game.compatdata
    (cd / "pfx/drive_c").mkdir(parents=True)
    (cd / "pfx/.wemod_installer").write_text("")
    exe = app.exe_path("wand")
    exe.parent.mkdir(parents=True)
    exe.write_text("MZ")
    (exe.parent / "DWriteCore.dll").write_text("dll")
    for k, v in fake_steam.env(game).items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(game.install_dir)
    return fake_steam


def decide(steam, argv=None, cfg=None, appid=None):
    game = steam.game()
    cmd = A.parse(argv or steam.proton_argv(game))
    return launch.decide(
        cmd,
        cfg or Config(),
        appid or game.appid,
        dict(os.environ),
        str(game.install_dir),
    )


def test_normal_launch(ready):
    d = decide(ready)
    assert d.state == "ok"
    assert d.command == [
        str(ready.entry_point),
        f"--verb={VERB}",
        "--",
        str(ready.ge_proton),
        VERB,
        "start",
        A.windows_abs_path(str(paths.bat_file())),
        "game.exe",
    ]
    assert d.env["WEMOD_DECK_EXE"].startswith("Z:\\")
    assert d.env["WEMOD_DECK_EXE"].endswith("\\Wand.exe")
    bat = paths.bat_file().read_bytes()
    assert b"\r\n" in bat and b"\r\r" not in bat
    roaming = ready.game().compatdata / login.ROAMING / "Wand"
    assert roaming.is_symlink()


def test_other_verbs_are_plain(ready):
    d = decide(ready, ready.proton_argv(ready.game(), "run"))
    assert d.state == "plain"
    assert d.command == ready.proton_argv(ready.game(), "run")


def test_opted_out(ready):
    cfg = Config(apps={ready.game().appid: {"enabled": False}})
    d = decide(ready, cfg=cfg)
    assert (d.state, d.command) == ("plain", ready.proton_argv(ready.game()))


def test_first_launch_is_plain(fake_steam, monkeypatch):
    for k, v in fake_steam.env(fake_steam.game()).items():
        monkeypatch.setenv(k, v)
    d = decide(fake_steam)
    assert d.state == "plain" and "first launch" in d.message


def test_missing_app_and_no_network_is_plain_error(ready, monkeypatch):
    app.exe_path("wand").unlink()
    monkeypatch.setenv("WEMOD_DECK_URL_SCOOP_WAND", "http://127.0.0.1:9/none")
    d = decide(ready)
    assert d.state == "error"
    assert d.command == ready.proton_argv(ready.game())


def test_prefix_download_failure_is_plain_error(ready, monkeypatch):
    (ready.game().compatdata / "pfx/.wemod_installer").unlink()
    (ready.game().compatdata / "version").write_text("x GE-Proton11-7\n")
    monkeypatch.setenv("WEMOD_DECK_URL_PREFIX_RELEASES", "http://127.0.0.1:9/none")
    d = decide(ready)
    assert d.state == "error"


def test_prefix_gets_installed(ready, http_server, monkeypatch, tmp_path):
    cd = ready.game().compatdata
    (cd / "pfx/.wemod_installer").unlink()
    (cd / "version").write_text("x GE-Proton11-7\n")
    body = build_fake_prefix_zip(tmp_path / "p.zip").read_bytes()
    url = http_server.add("/p.zip", body)
    rel = [
        {
            "tag_name": "PfxVer10.1",
            "assets": [{"name": "p.zip", "browser_download_url": url, "size": 1}],
        }
    ]
    monkeypatch.setenv("WEMOD_DECK_URL_PREFIX_RELEASES", http_server.add("/rel", rel))
    assert decide(ready).state == "ok"
    assert (cd / "pfx/.wemod_installer").exists()


class Exec:
    def __init__(self):
        self.calls = []

    def __call__(self, file, argv, env):
        self.calls.append((file, argv, env))


def test_main_execs_and_records_status(ready):
    ex = Exec()
    launch.main(ready.proton_argv(ready.game()), Config(), [], execute=ex)
    ((file, argv, env),) = ex.calls
    assert file == str(ready.entry_point) and "start" in argv
    assert env["WEMOD_DECK_EXE"].endswith("Wand.exe")
    assert status.read_status()["apps"][ready.game().appid]["state"] == "ok"


def test_main_unparseable_argv_runs_unchanged(ready):
    ex = Exec()
    weird = ["/usr/bin/env", "true"]
    launch.main(weird, Config(), [], execute=ex)
    assert ex.calls[0][1] == weird
    assert status.read_status()["last"]["state"] == "error"


def test_main_unexpected_error_falls_back(ready, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(launch.login, "link_logins", boom)
    ex = Exec()
    launch.main(ready.proton_argv(ready.game()), Config(), [], execute=ex)
    assert ex.calls[0][1] == ready.proton_argv(ready.game())
    assert "bug" in status.read_status()["last"]["message"]


def test_main_legacy(ready):
    ex = Exec()
    launch.main(
        ready.launch_options_argv(ready.game()), Config(), [], legacy=True, execute=ex
    )
    argv = ex.calls[0][1]
    assert argv[0] == str(ready.reaper) and "start" in argv


def test_bat_is_headless():
    text = (Path(launch.__file__).parent / "data" / "wemod-deck.bat").read_text()
    lowered = text.lower()
    assert "pause" not in lowered
    assert "waituser" not in lowered
    assert "%wemod_deck_exe%" in lowered
    assert "start /wait" in lowered
    code = [ln for ln in lowered.splitlines() if not ln.strip().startswith("rem")]
    assert not any("%time%" in ln for ln in code)  # locale-dependent in Wine
    assert ":wemod-deck-timer" in lowered


def test_ready_file_is_created_and_not_passed_on(ready, tmp_path, monkeypatch):
    flag = tmp_path / "ready"
    monkeypatch.setenv("WEMOD_DECK_READY_FILE", str(flag))
    ex = Exec()
    launch.main(ready.proton_argv(ready.game()), Config(), [], execute=ex)
    assert flag.exists()
    assert "WEMOD_DECK_READY_FILE" not in ex.calls[0][2]


def test_no_space_for_backup_leaves_prefix_alone(
    ready, http_server, monkeypatch, tmp_path
):
    cd = ready.game().compatdata
    (cd / "pfx/.wemod_installer").unlink()
    (cd / "version").write_text("x GE-Proton11-7\n")
    body = build_fake_prefix_zip(tmp_path / "p.zip").read_bytes()
    url = http_server.add("/p.zip", body)
    rel = [
        {
            "tag_name": "PfxVer10.1",
            "assets": [{"name": "p.zip", "browser_download_url": url, "size": 1}],
        }
    ]
    monkeypatch.setenv("WEMOD_DECK_URL_PREFIX_RELEASES", http_server.add("/rel", rel))
    monkeypatch.setattr(backup, "SPACE_MARGIN", 1 << 62)
    d = decide(ready)
    assert d.state == "error" and "no save backup" in d.message
    assert d.command == ready.proton_argv(ready.game())
    assert not (cd / "pfx/.wemod_installer").exists()
    assert not (cd / "pfx/system.reg").exists()  # nothing unpacked
