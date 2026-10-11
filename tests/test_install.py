"""Run the real install.sh offline (fake HOME, fake Steam, fake server)."""

from __future__ import annotations

import pytest

from fakes.installer import repo_zip, run_install, serve_everything


@pytest.fixture
def remote(http_server, tmp_path):
    return serve_everything(http_server, tmp_path)


@pytest.fixture
def zipped(tmp_path):
    return repo_zip(tmp_path / "steam-deck-wemod-main.zip")


def test_full_install(fake_steam, remote, zipped):
    s = fake_steam
    r = run_install(s, ["--zip", str(zipped)], remote.env)
    assert r.returncode == 0, r.stdout + r.stderr

    install = s.home / "wemod-deck"
    assert (install / "wemod_deck" / "__main__.py").is_file()
    # Wand downloaded, checksum-verified, with DWriteCore
    data = s.home / ".local/share/wemod-deck"
    assert (data / "app/wand/Wand.exe").is_file()
    assert (data / "app/wand/DWriteCore.dll").read_bytes() == b"DWRITE"
    # GE-Proton: suffixed asset, folder name read from the archive
    ge = s.steam_root / "compatibilitytools.d/GE-Proton11-8-x86_64"
    assert (ge / "proton").is_file()
    assert "/ge/dl/GE-Proton11-8/GE-Proton11-8-x86_64.tar.gz" in remote.server.requests

    tool = s.steam_root / "compatibilitytools.d/WeMod-GE"
    manifest = (tool / "toolmanifest.vdf").read_text()
    assert "require_tool_appid" not in manifest
    assert "/proton %verb%" in manifest
    assert (
        '"display_name" "WeMod + GE-Proton11-8"'
        in (tool / "compatibilitytool.vdf").read_text()
    )
    conf = (tool / "tool.conf").read_text()
    assert f"GE_PROTON={ge}/proton" in conf
    assert "RUNTIME_APPID=1628350" in conf
    assert f"WEMOD_DECK_DIR={install}" in conf
    assert (tool / "proton").stat().st_mode & 0o111
    assert "WeMod + GE-Proton11-8" in r.stdout
    assert not list((s.home / ".cache").glob("ge-proton.*"))


def test_rerun_is_idempotent(fake_steam, remote, zipped):
    assert run_install(fake_steam, ["--zip", str(zipped)], remote.env).returncode == 0
    remote.server.requests.clear()
    r = run_install(fake_steam, ["--zip", str(zipped)], remote.env)
    assert r.returncode == 0, r.stderr
    assert "already installed" in r.stdout
    assert not any(p.endswith(".tar.gz") for p in remote.server.requests)
    assert not any(p.startswith("/cdn/") for p in remote.server.requests)


def test_unsuffixed_ge_asset_fallback(fake_steam, http_server, tmp_path, zipped):
    remote = serve_everything(
        http_server, tmp_path, ge_tag="GE-Proton9-27", suffixed=False
    )
    r = run_install(fake_steam, ["--zip", str(zipped), "--no-wemod"], remote.env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (
        fake_steam.steam_root / "compatibilitytools.d/GE-Proton9-27/proton"
    ).is_file()
    assert "WeMod + GE-Proton9-27" in r.stdout


def test_ge_checksum_mismatch_aborts(fake_steam, http_server, tmp_path, zipped):
    remote = serve_everything(http_server, tmp_path, bad_sum=True)
    r = run_install(fake_steam, ["--zip", str(zipped), "--no-wemod"], remote.env)
    assert r.returncode != 0
    assert "checksum mismatch" in r.stderr
    assert not (
        fake_steam.steam_root / "compatibilitytools.d/GE-Proton11-8-x86_64"
    ).exists()


def test_no_proton_uses_installed_ge(fake_steam, zipped):
    r = run_install(fake_steam, ["--zip", str(zipped), "--no-proton", "--no-wemod"])
    assert r.returncode == 0, r.stdout + r.stderr
    conf = (
        fake_steam.steam_root / "compatibilitytools.d/WeMod-GE/tool.conf"
    ).read_text()
    assert f"GE_PROTON={fake_steam.ge_proton}" in conf


def test_wand_download_failure_is_only_a_warning(fake_steam, zipped):
    env = {"WEMOD_DECK_URL_SCOOP_WAND": "http://127.0.0.1:9/none"}
    r = run_install(fake_steam, ["--zip", str(zipped), "--no-proton"], env)
    assert r.returncode == 0, r.stderr
    assert "retried on the first game launch" in r.stdout


def test_refuses_foreign_dir(fake_steam, zipped):
    other = fake_steam.home / "wemod-launcher"
    other.mkdir()
    (other / "wemod").write_text("upstream")
    r = run_install(fake_steam, ["--zip", str(zipped), "--dir", str(other)])
    assert r.returncode != 0
    assert "is not wemod-deck" in r.stderr
    assert (other / "wemod").read_text() == "upstream"


def test_migrates_upstream_install(fake_steam, remote, zipped):
    old = fake_steam.home / "wemod-launcher/wemod_data/wemod_login"
    old.mkdir(parents=True)
    (old / "Local Storage").write_text("login")
    r = run_install(fake_steam, ["--zip", str(zipped), "--no-proton"], remote.env)
    assert r.returncode == 0, r.stderr
    login = fake_steam.home / ".local/share/wemod-deck/login/wemod/Local Storage"
    assert login.read_text() == "login"
    assert (old / "Local Storage").exists()


def test_uninstall_keeps_data_unless_confirmed(fake_steam, remote, zipped):
    s = fake_steam
    assert (
        run_install(s, ["--zip", str(zipped), "--no-proton"], remote.env).returncode
        == 0
    )
    data = s.home / ".local/share/wemod-deck"
    r = run_install(s, ["--uninstall"], stdin="YES\nno\n")
    assert r.returncode == 0, r.stderr
    assert not (s.home / "wemod-deck").exists()
    assert not (s.steam_root / "compatibilitytools.d/WeMod-GE").exists()
    assert (s.steam_root / "compatibilitytools.d" / s.ge_dir.name).exists()
    assert data.exists()

    assert (
        run_install(s, ["--zip", str(zipped), "--no-proton"], remote.env).returncode
        == 0
    )
    r = run_install(s, ["--uninstall"], stdin="YES\nYES\n")
    assert r.returncode == 0
    assert not data.exists()


def test_uninstall_cancel(fake_steam, zipped):
    assert (
        run_install(
            fake_steam, ["--zip", str(zipped), "--no-proton", "--no-wemod"]
        ).returncode
        == 0
    )
    r = run_install(fake_steam, ["--uninstall"], stdin="no\n")
    assert "Cancelled" in r.stdout
    assert (fake_steam.home / "wemod-deck").exists()


def test_steam_only_under_dot_steam(fake_steam, zipped, tmp_path):
    """The last candidate (~/.local/share/Steam) missing must not trip pipefail."""
    s = fake_steam
    real = tmp_path / "SteamElsewhere"
    s.steam_root.rename(real)
    for link in ("root", "steam"):
        (s.home / ".steam" / link).unlink()
        (s.home / ".steam" / link).symlink_to(real)
    r = run_install(s, ["--zip", str(zipped), "--no-proton", "--no-wemod"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert (real / "compatibilitytools.d/WeMod-GE/proton").is_file()
