from __future__ import annotations

import pytest

from fakes.steam_root import PLAIN_GAME_APPID, RUNTIME_APPID
from wemod_deck import steam
from wemod_deck.steam import VdfError, parse_vdf


def test_parse_vdf_nested_and_comments():
    text = """
    // comment
    "root"
    {
        "a"   "1"
        "b"   "with \\"quote\\""
        bare  value
        "sub" { "x" "y" }
    }
    """
    assert parse_vdf(text) == {
        "root": {"a": "1", "b": 'with "quote"', "bare": "value", "sub": {"x": "y"}}
    }


@pytest.mark.parametrize("text", ['"a" {', '"a" }', '"a"', "}"])
def test_parse_vdf_errors(text):
    with pytest.raises(VdfError):
        parse_vdf(text)


def test_find_steam_root(fake_steam, monkeypatch):
    monkeypatch.delenv("STEAM_COMPAT_CLIENT_INSTALL_PATH", raising=False)
    assert steam.find_steam_root() == fake_steam.steam_root
    monkeypatch.setenv("STEAM_COMPAT_CLIENT_INSTALL_PATH", "/nonexistent")
    assert steam.find_steam_root() == fake_steam.steam_root


def test_no_steam(monkeypatch):
    monkeypatch.delenv("STEAM_COMPAT_CLIENT_INSTALL_PATH", raising=False)
    assert steam.find_steam_root() is None


def test_libraries_include_sd_card(fake_steam):
    libs = steam.library_paths(fake_steam.steam_root)
    assert libs == [fake_steam.steam_root, fake_steam.sd_card]


def test_libraries_survive_broken_vdf(fake_steam):
    (fake_steam.steam_root / "steamapps" / "libraryfolders.vdf").write_text("{{{")
    assert steam.library_paths(fake_steam.steam_root) == [fake_steam.steam_root]


@pytest.mark.parametrize("which", ["fake_steam", "fake_steam_sd"])
def test_runtime_entry_point_any_library(which, request):
    s = request.getfixturevalue(which)
    assert steam.find_runtime_entry_point(s.steam_root, RUNTIME_APPID) == s.entry_point


def test_runtime_entry_point_missing(fake_steam):
    fake_steam.entry_point.unlink()
    assert steam.find_runtime_entry_point(fake_steam.steam_root, RUNTIME_APPID) is None
    assert steam.find_runtime_entry_point(fake_steam.steam_root, "999") is None


def test_find_app_install_and_compatdata(fake_steam_sd):
    s = fake_steam_sd
    game = s.game(PLAIN_GAME_APPID)
    assert steam.find_app_install(s.steam_root, game.appid) == game.install_dir
    assert steam.find_compatdata(s.steam_root, game.appid) == []
    game.compatdata.mkdir(parents=True)
    assert steam.find_compatdata(s.steam_root, game.appid) == [game.compatdata]


def test_required_runtime_appid(fake_steam, tmp_path):
    assert steam.required_runtime_appid(fake_steam.ge_dir / "toolmanifest.vdf") == (
        RUNTIME_APPID
    )
    assert steam.required_runtime_appid(tmp_path / "missing.vdf") is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1700000000 GE-Proton11-7\n", (11, 7)),
        ("GE-Proton9-20", (9, 20)),
        ("1690000000 proton-9.0-4", (9, 0)),
        ("GE-Proton10", (10, 0)),
        ("", None),
        ("nothing", None),
    ],
)
def test_parse_proton_version(text, expected):
    assert steam.parse_proton_version(text) == expected
