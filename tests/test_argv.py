"""Parser tests. The Launch Options cases reproduce what upstream 1.543
produced (pinned in Phase 0), minus custom runners (non-goal)."""

from __future__ import annotations

import pytest

from fakes.steam_root import LAUNCHER_GAME_APPID
from wemod_deck import argv as A
from wemod_deck.argv import LaunchCommand, ParseError

VERB = "waitforexitandrun"


def test_compat_tool_with_runtime(fake_steam):
    s = fake_steam
    game = s.game()
    cmd = A.parse(s.proton_argv(game) + ["-dx11", "--", "x"])
    assert cmd == LaunchCommand(
        [str(s.entry_point), f"--verb={VERB}", "--"],
        str(s.ge_proton),
        VERB,
        str(game.exe),
        ["-dx11", "--", "x"],
    )
    assert cmd.plain() == s.proton_argv(game) + ["-dx11", "--", "x"]


def test_compat_tool_without_runtime(fake_steam):
    s = fake_steam
    cmd = A.parse([str(s.ge_proton), VERB, str(s.game().exe)])
    assert cmd.prefix == []
    assert cmd.proton == str(s.ge_proton)


def test_compat_tool_sd_card(fake_steam_sd):
    s = fake_steam_sd
    game = s.game(LAUNCHER_GAME_APPID)
    cmd = A.parse(s.proton_argv(game))
    assert cmd.prefix[0] == str(s.entry_point)
    assert cmd.exe == str(game.exe)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["/x/_v2-entry-point", "--verb=run", "/p/proton", "run", "g.exe"],  # no --
        ["/x/_v2-entry-point", "--", "/p/proton", "run", "g.exe"],  # no --verb
        ["/x/_v2-entry-point", "--verb=run", "--", "/p/proton", VERB, "g.exe"],
        ["/x/_v2-entry-point", "--verb=run", "--", "/p/wine", "g.exe"],
        ["/p/proton", VERB],  # no exe
        ["/p/proton", "g.exe", "x"],  # verb looks like a file
        ["reaper", "SteamLaunch", "--", "/p/proton", VERB, "g.exe"],
    ],
)
def test_compat_tool_rejects(argv):
    with pytest.raises(ParseError):
        A.parse(argv)


def test_launch_options(fake_steam):
    """Upstream pinned result: prefix = everything before Proton."""
    s = fake_steam
    game = s.game()
    full = s.launch_options_argv(game)
    cmd = A.parse(full, legacy=True)
    at = full.index(str(s.ge_proton))
    assert cmd.prefix == full[:at]
    assert (cmd.proton, cmd.verb, cmd.exe, cmd.args) == (
        str(s.ge_proton),
        VERB,
        str(game.exe),
        [],
    )
    assert cmd.plain() == full


def test_launch_options_sd_card(fake_steam_sd):
    s = fake_steam_sd
    game = s.game(LAUNCHER_GAME_APPID)
    cmd = A.parse(s.launch_options_argv(game), legacy=True)
    assert str(s.entry_point) in cmd.prefix
    assert cmd.exe == str(game.exe)


def test_launch_options_does_not_depend_on_tool_paths(fake_steam, monkeypatch):
    """Upstream needed STEAM_COMPAT_TOOL_PATHS to match; we don't."""
    monkeypatch.setenv("STEAM_COMPAT_TOOL_PATHS", "/nonexistent/tool")
    s = fake_steam
    cmd = A.parse(s.launch_options_argv(s.game()), legacy=True)
    assert cmd.proton == str(s.ge_proton)


@pytest.mark.parametrize(
    "argv",
    [
        ["/opt/wine/bin/wine", "/games/game.exe"],  # custom runner (non-goal)
        ["--", "/opt/wine/bin/wine", "game.exe"],  # upstream crashed here
    ],
)
def test_launch_options_custom_runner_is_a_clear_error(argv):
    with pytest.raises(ParseError, match="custom wine runners"):
        A.parse(argv, legacy=True)


def test_windows_paths(fake_steam):
    game = fake_steam.game()
    assert A.windows_game_path(str(game.exe), str(game.install_dir)) == "game.exe"
    sub = game.install_dir / "bin" / "x64"
    sub.mkdir(parents=True)
    (sub / "g.exe").write_text("")
    assert (
        A.windows_game_path(str(sub / "g.exe"), str(game.install_dir))
        == "bin\\\\x64\\\\g.exe"
    )
    assert A.windows_game_path("steam://run/1", "/") == "steam://run/1"
    assert A.windows_abs_path("/home/deck/x.bat") == "Z:\\\\home\\\\deck\\\\x.bat"
