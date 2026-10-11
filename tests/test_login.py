from __future__ import annotations

import os

from wemod_deck import login, paths


def roaming(cd, name):
    return cd / login.ROAMING / name


def test_links_both_names(tmp_path):
    cd = tmp_path / "cd"
    login.link_logins(cd, "1")
    for app, name in login.ROAMING_NAMES.items():
        assert os.readlink(roaming(cd, name)) == str(paths.login_dir(app))
    assert login.link_logins(cd, "1") == []  # idempotent


def test_first_prefix_login_becomes_shared(tmp_path):
    cd = tmp_path / "cd"
    r = roaming(cd, "Wand")
    r.mkdir(parents=True)
    (r / "session.json").write_text("token")
    login.link_logins(cd, "1")
    assert (paths.login_dir("wand") / "session.json").read_text() == "token"
    assert r.is_symlink()


def test_central_wins_and_prefix_login_is_displaced_not_deleted(tmp_path):
    paths.login_dir("wand").mkdir(parents=True)
    (paths.login_dir("wand") / "session.json").write_text("central")
    cd = tmp_path / "cd"
    r = roaming(cd, "Wand")
    r.mkdir(parents=True)
    (r / "session.json").write_text("prefix")
    actions = login.link_logins(cd, "42")
    assert (paths.login_dir("wand") / "session.json").read_text() == "central"
    moved = list(paths.displaced_login_dir().iterdir())
    assert len(moved) == 1 and moved[0].name.startswith("42-wand-")
    assert (moved[0] / "session.json").read_text() == "prefix"
    assert any("moved" in a for a in actions)


def test_old_symlink_is_repointed_without_touching_target(tmp_path):
    old = tmp_path / "wemod-launcher/wemod_data/wemod_login"
    old.mkdir(parents=True)
    (old / "keep").write_text("x")
    cd = tmp_path / "cd"
    r = roaming(cd, "WeMod")
    r.parent.mkdir(parents=True)
    r.symlink_to(old)
    login.link_logins(cd, "1")
    assert os.readlink(r) == str(paths.login_dir("wemod"))
    assert (old / "keep").read_text() == "x"


def test_stray_file_is_displaced(tmp_path):
    cd = tmp_path / "cd"
    r = roaming(cd, "Wand")
    r.parent.mkdir(parents=True)
    r.write_text("odd")
    login.link_logins(cd, "1")
    assert r.is_symlink()
    (moved,) = paths.displaced_login_dir().iterdir()
    assert moved.read_text() == "odd"


def test_migrate_legacy_copies_once(isolated_home):
    old = isolated_home / "wemod-launcher/wemod_data"
    (old / "wemod_login").mkdir(parents=True)
    (old / "wemod_login/Local Storage").mkdir()
    (old / "wemod_login/Local Storage/x").write_text("login")
    (old / "wemod_bin").mkdir()
    (old / "wemod_bin/WeMod.exe").write_text("exe")
    actions = login.migrate_legacy()
    assert len(actions) == 2
    assert (paths.login_dir("wemod") / "Local Storage/x").read_text() == "login"
    assert (paths.app_dir("wemod") / "WeMod.exe").read_text() == "exe"
    assert (old / "wemod_bin/WeMod.exe").exists()  # copied, not moved
    assert login.migrate_legacy() == []


def test_migrate_legacy_never_overwrites(isolated_home):
    old = isolated_home / "wemod-launcher/wemod_data/wemod_login"
    old.mkdir(parents=True)
    (old / "a").write_text("old")
    paths.login_dir("wemod").mkdir(parents=True)
    (paths.login_dir("wemod") / "a").write_text("new")
    assert login.migrate_legacy() == []
    assert (paths.login_dir("wemod") / "a").read_text() == "new"


def test_no_legacy_install():
    assert login.migrate_legacy() == []
