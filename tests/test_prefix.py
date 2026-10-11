from __future__ import annotations

import json
import os

import pytest

from fakes.fake_prefix import build_fake_prefix_zip
from wemod_deck import net, paths, prefix
from wemod_deck.prefix import PrefixError

RELEASES = [
    {
        "tag_name": f"PfxVer{v}",
        "assets": [
            {
                "name": f"GE-Proton{v}.zip",
                "browser_download_url": f"https://x/GE-Proton{v}.zip",
                "size": 10,
            }
        ],
    }
    for v in ("9.1", "8.1", "10.1", "10.4", "12.2")
]


@pytest.mark.parametrize(
    "want, tag",
    [
        ((10, 1), "PfxVer10.1"),  # exact
        ((10, 3), "PfxVer10.1"),  # same major, nearest lower minor
        ((10, 0), "PfxVer10.1"),  # same major, nearest higher minor
        ((11, 7), "PfxVer10.4"),  # lower major, newest of it (today's GE 11 case)
        ((7, 50), "PfxVer8.1"),  # only higher majors: nearest
    ],
)
def test_pick_release(want, tag):
    assert prefix.pick_release(RELEASES, want)["tag_name"] == tag


def test_pick_release_ignores_junk():
    junk = [{"tag_name": "v1"}, {"tag_name": "PfxVer9.1", "assets": []}]
    assert prefix.pick_release(junk, (9, 1)) is None


def test_releases_cache(http_server, monkeypatch):
    monkeypatch.setenv(
        "WEMOD_DECK_URL_PREFIX_RELEASES", http_server.add("/rel", RELEASES)
    )
    assert len(prefix.releases(now=1000)) == 5
    http_server.fail("/rel", 503)
    assert len(prefix.releases(now=1000 + 3600)) == 5  # fresh cache, no request
    assert http_server.requests == ["/rel"]
    assert len(prefix.releases(now=1000 + 2 * 86400)) == 5  # stale but GitHub down
    cache = json.loads((paths.cache_dir() / "prefix-releases.json").read_text())
    assert set(cache["releases"][0]) == {"tag_name", "assets"}


def test_releases_without_cache_or_network(http_server, monkeypatch):
    http_server.fail("/rel", 503)
    monkeypatch.setenv("WEMOD_DECK_URL_PREFIX_RELEASES", http_server.url("/rel"))
    with pytest.raises(net.DownloadError):
        prefix.releases()


def make_prefix(fake_steam):
    """A prefix Proton has already built and the player has used."""
    game = fake_steam.game()
    cd = game.compatdata
    user = cd / "pfx/drive_c/users/steamuser"
    (user / "Saved Games/Game").mkdir(parents=True)
    (user / "Saved Games/Game/save.dat").write_bytes(b"MY PRECIOUS SAVE\x00\x01")
    (user / "Documents").mkdir()
    (user / "Documents/notes.txt").write_text("mine")
    (cd / "pfx/drive_c/windows/system32").mkdir(parents=True)
    (cd / "pfx/drive_c/windows/system32/kernel32.dll").write_text("proton's")
    (cd / "version").write_text("1700000000 GE-Proton11-7\n")
    return cd


def snapshot(root):
    return {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def test_unpack_never_overwrites_user_files(fake_steam, tmp_path):
    cd = make_prefix(fake_steam)
    users = cd / "pfx/drive_c/users"
    before = snapshot(users)
    counts = prefix.unpack(build_fake_prefix_zip(tmp_path / "p.zip"), cd)

    after = snapshot(users)
    for rel, data in before.items():
        assert after[rel] == data, f"{rel} changed"
    # Missing user files are added, existing ones kept.
    assert (users / "steamuser/Documents/readme.txt").read_bytes() == b"prebuilt doc\n"
    assert counts["kept_user_files"] == 1
    # Non-user files are replaced, marker and version written, links made.
    assert (cd / "pfx/drive_c/windows/system32/kernel32.dll").read_bytes() == (
        b"MZ prebuilt kernel32\n"
    )
    assert prefix.has_wemod(cd)
    assert os.readlink(cd / "pfx/dosdevices/c:") == "../drive_c"
    assert os.readlink(cd / "pfx/dosdevices/z:") == "/"
    assert not list(cd.rglob("*.wemod-deck-part"))


def test_unpack_does_not_write_through_symlinks(fake_steam, tmp_path):
    cd = make_prefix(fake_steam)
    central = tmp_path / "central-login"
    central.mkdir()
    roaming = cd / "pfx/drive_c/users/steamuser/AppData/Roaming"
    roaming.mkdir(parents=True)
    (roaming / "WeMod").symlink_to(central)
    outside = tmp_path / "outside"
    zip_path = build_fake_prefix_zip(
        tmp_path / "p.zip",
        extra={"pfx/../../escape.txt": b"x", "pfx/dosdevices/z:/etc/x": b"x"},
        links={"pfx/evil": str(outside), "pfx/dosdevices/d:": "/home"},
    )
    counts = prefix.unpack(zip_path, cd)
    assert list(central.iterdir()) == []
    assert not (cd.parent.parent / "escape.txt").exists()
    assert not (cd / "pfx/evil").exists() and not (cd / "pfx/evil").is_symlink()
    assert not (cd / "pfx/dosdevices/d:").is_symlink()
    assert os.readlink(cd / "pfx/dosdevices/z:") == "/"
    assert counts["skipped"] >= 4


def test_unpack_rejects_zip_without_marker(fake_steam, tmp_path):
    cd = make_prefix(fake_steam)
    with pytest.raises(PrefixError, match="marker"):
        prefix.unpack(build_fake_prefix_zip(tmp_path / "p.zip", marker=False), cd)
    assert not prefix.has_wemod(cd)


def test_unpack_checks_disk_space(fake_steam, tmp_path, monkeypatch):
    cd = make_prefix(fake_steam)
    before = snapshot(cd)
    monkeypatch.setattr(prefix, "_SPACE_MARGIN", 1 << 62)
    with pytest.raises(PrefixError, match="not enough space"):
        prefix.unpack(build_fake_prefix_zip(tmp_path / "p.zip"), cd)
    assert snapshot(cd) == before


def test_ensure_downloads_closest_and_keeps_one_zip(
    fake_steam, http_server, monkeypatch, tmp_path
):
    cd = make_prefix(fake_steam)
    body = build_fake_prefix_zip(tmp_path / "p.zip").read_bytes()
    url = http_server.add("/dl/GE-Proton10.1.zip", body)
    rel = [
        {
            "tag_name": "PfxVer10.1",
            "assets": [
                {
                    "name": "GE-Proton10.1.zip",
                    "browser_download_url": url,
                    "size": len(body),
                }
            ],
        }
    ]
    monkeypatch.setenv("WEMOD_DECK_URL_PREFIX_RELEASES", http_server.add("/rel", rel))
    stale = paths.cache_dir() / "prefixes" / "GE-Proton9.1.zip"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    assert prefix.ensure(cd, str(fake_steam.ge_proton)) is True
    assert prefix.has_wemod(cd)
    assert [p.name for p in stale.parent.iterdir()] == ["GE-Proton10.1.zip"]
    assert prefix.ensure(cd, str(fake_steam.ge_proton)) is False  # already done


def test_reset_prefix_moves_aside(fake_steam):
    cd = make_prefix(fake_steam)
    saved = snapshot(cd)
    moved = prefix.reset_prefix(fake_steam.steam_root, fake_steam.game().appid, now=0)
    assert not cd.exists()
    ((src, dest),) = moved
    assert src == cd
    assert dest.parent.name == "compatdata-wemod-deck-old"
    assert snapshot(dest) == saved
    with pytest.raises(PrefixError):
        prefix.reset_prefix(fake_steam.steam_root, "../1")


OLD_USER_REG = """WINE REGISTRY Version 2
;; All keys relative to \\\\User\\\\S-1-5-21-0-0-0-1000

#arch=win64

[Software\\\\Wine\\\\DllOverrides] 1600000000
"mscoree"="builtin"

[Software\\\\Unity\\\\UnityEditor\\\\Studio\\\\Game] 1700000001
"Save_Slot1_h123"=hex:01,02,03
"""

NEW_USER_REG = """WINE REGISTRY Version 2
;; All keys relative to \\\\User\\\\S-1-5-21-0-0-0-1000

#arch=win64

[Software\\\\wine\\\\dlloverrides] 1650000000
"mscoree"="native"
"""


def test_merge_registry_keeps_game_keys_and_prebuilt_overrides():
    merged = prefix.merge_registry(NEW_USER_REG, OLD_USER_REG)
    assert merged.startswith(NEW_USER_REG)
    assert '"mscoree"="native"' in merged
    assert '"mscoree"="builtin"' not in merged  # same key (case-insensitive)
    assert '"Save_Slot1_h123"=hex:01,02,03' in merged
    assert prefix.merge_registry(NEW_USER_REG, NEW_USER_REG) == NEW_USER_REG


def test_unpack_backs_up_and_merges_registry(fake_steam, tmp_path):
    cd = make_prefix(fake_steam)
    (cd / "pfx/user.reg").write_text(OLD_USER_REG)
    (cd / "pfx/system.reg").write_text("WINE REGISTRY old system\n")
    zip_path = build_fake_prefix_zip(
        tmp_path / "p.zip", extra={"pfx/user.reg": NEW_USER_REG.encode()}
    )
    counts = prefix.unpack(zip_path, cd)
    assert counts["registry_backups"] == 2
    user = (cd / "pfx/user.reg").read_text()
    assert '"mscoree"="native"' in user and "Save_Slot1_h123" in user
    assert (cd / "pfx/system.reg").read_text() == "WINE REGISTRY prebuilt\n"
    (backup,) = (cd / prefix.BACKUP_DIR).iterdir()
    assert (backup / "pfx/user.reg").read_text() == OLD_USER_REG
    assert (backup / "pfx/system.reg").read_text() == "WINE REGISTRY old system\n"


@pytest.mark.parametrize(
    "sneaky",
    [
        "pfx/./drive_c/users/steamuser/Saved Games/Game/save.dat",
        "pfx//drive_c/users/steamuser/Saved Games/Game/save.dat",
    ],
)
def test_unpack_normalises_names_before_checks(fake_steam, tmp_path, sneaky):
    cd = make_prefix(fake_steam)
    save = cd / "pfx/drive_c/users/steamuser/Saved Games/Game/save.dat"
    before = save.read_bytes()
    prefix.unpack(
        build_fake_prefix_zip(tmp_path / "p.zip", extra={sneaky: b"EVIL"}), cd
    )
    assert save.read_bytes() == before
