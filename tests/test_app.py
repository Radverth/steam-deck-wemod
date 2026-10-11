from __future__ import annotations

import zipfile

import pytest

from fakes.fake_nupkg import build_fake_nupkg, sha256
from wemod_deck import app, net, paths


def serve_app(
    server,
    monkeypatch,
    tmp_path,
    *,
    app_name="wand",
    version="12.62.0",
    tamper=False,
    bad_hash=False,
):
    pkg = build_fake_nupkg(tmp_path / f"{app_name}-{version}.nupkg", app=app_name)
    digest = sha256(pkg)
    if tamper:
        pkg = build_fake_nupkg(pkg, app=app_name, tamper=True)
    server.add(f"/cdn/{pkg.name}", pkg.read_bytes())
    manifest = {
        "version": version,
        "architecture": {
            "64bit": {
                "url": server.url(f"/cdn/{pkg.name}"),
                "hash": "0" * 64 if bad_hash else digest,
            }
        },
    }
    monkeypatch.setenv(
        f"WEMOD_DECK_URL_SCOOP_{app_name.upper()}",
        server.add(f"/scoop/{app_name}.json", manifest),
    )
    return pkg


def test_install_wand(http_server, monkeypatch, tmp_path):
    serve_app(http_server, monkeypatch, tmp_path)
    assert not app.is_installed("wand")
    assert app.install("wand") is True
    assert app.exe_path("wand").read_bytes() == b"MZ fake Wand.exe\n"
    assert (paths.app_dir("wand") / "resources" / "app.asar").is_file()
    assert app.installed_version("wand") == "12.62.0"
    # The download went to ~/.cache and was cleaned up afterwards.
    assert not list((paths.cache_dir() / "downloads").glob("*"))


def test_install_is_skipped_when_current(http_server, monkeypatch, tmp_path):
    serve_app(http_server, monkeypatch, tmp_path)
    app.install("wand")
    http_server.requests.clear()
    assert app.install("wand") is False
    assert not any(r.startswith("/cdn/") for r in http_server.requests)
    assert app.install("wand", force=True) is True


def test_install_wemod(http_server, monkeypatch, tmp_path):
    serve_app(http_server, monkeypatch, tmp_path, app_name="wemod", version="11.6.0")
    app.install("wemod")
    assert app.exe_path("wemod").read_bytes() == b"MZ fake WeMod.exe\n"


def test_tampered_package_is_rejected_and_old_install_kept(
    http_server, monkeypatch, tmp_path
):
    serve_app(http_server, monkeypatch, tmp_path, version="1.0")
    app.install("wand")
    serve_app(http_server, monkeypatch, tmp_path, version="2.0", tamper=True)
    with pytest.raises(net.DownloadError, match="checksum"):
        app.install("wand")
    assert app.installed_version("wand") == "1.0"
    assert app.exe_path("wand").is_file()
    assert not list((paths.cache_dir() / "downloads").glob("*"))


def test_update_keeps_dwritecore(http_server, monkeypatch, tmp_path):
    serve_app(http_server, monkeypatch, tmp_path, version="1.0")
    app.install("wand")
    (paths.app_dir("wand") / "DWriteCore.dll").write_bytes(b"dll")
    serve_app(http_server, monkeypatch, tmp_path, version="2.0")
    app.install("wand")
    assert app.installed_version("wand") == "2.0"
    assert (paths.app_dir("wand") / "DWriteCore.dll").read_bytes() == b"dll"
    assert sorted(p.name for p in paths.app_dir("wand").parent.iterdir()) == ["wand"]


def test_unpack_rejects_missing_exe_and_unsafe_paths(tmp_path):
    pkg = build_fake_nupkg(tmp_path / "wemod.nupkg", app="wemod")
    with pytest.raises(app.AppError, match="Wand.exe not found"):
        app.unpack(pkg, tmp_path / "out", "wand")
    evil = tmp_path / "evil.nupkg"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("lib/net45/Wand.exe", b"x")
        z.writestr("lib/net45/../../../escape.txt", b"x")
    with pytest.raises(app.AppError, match="unsafe"):
        app.unpack(evil, tmp_path / "out2", "wand")
    assert not (tmp_path / "escape.txt").exists()


def test_manifest_without_hash(http_server, monkeypatch):
    monkeypatch.setenv(
        "WEMOD_DECK_URL_SCOOP_WAND",
        http_server.add("/scoop/wand.json", {"version": "1", "architecture": {}}),
    )
    with pytest.raises(app.AppError):
        app.install("wand")


def test_dwritecore(http_server, monkeypatch, tmp_path):
    nupkg = tmp_path / "dwrite.nupkg"
    with zipfile.ZipFile(nupkg, "w") as z:
        z.writestr(app.DWRITECORE_MEMBER, b"DWRITE")
    monkeypatch.setenv(
        "WEMOD_DECK_URL_DWRITECORE",
        http_server.url("/nuget/{version}/dwrite.nupkg"),
    )
    http_server.add(f"/nuget/{app.DWRITECORE_VERSION}/dwrite.nupkg", nupkg.read_bytes())
    paths.app_dir("wand").mkdir(parents=True)
    assert app.ensure_dwritecore("wand") is True
    assert (paths.app_dir("wand") / "DWriteCore.dll").read_bytes() == b"DWRITE"


def test_dwritecore_failure_is_not_fatal(http_server, monkeypatch):
    monkeypatch.setenv("WEMOD_DECK_URL_DWRITECORE", http_server.url("/missing"))
    paths.app_dir("wand").mkdir(parents=True)
    assert app.ensure_dwritecore("wand") is False
    assert list(paths.app_dir("wand").iterdir()) == []


def test_download_errors_leave_nothing(http_server, tmp_path):
    http_server.fail("/boom", 500)
    dest = tmp_path / "x.bin"
    with pytest.raises(net.DownloadError):
        net.download(http_server.url("/boom"), dest)
    assert not dest.exists()
    assert not (tmp_path / "x.bin.part").exists()
    with pytest.raises(net.DownloadError):
        net.get_json("http://127.0.0.1:9/nothing-listens-here", timeout=2)


def test_dwritecore_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(app, "_tmp_parent", boom)
    paths.app_dir("wand").mkdir(parents=True)
    assert app.ensure_dwritecore("wand") is False
