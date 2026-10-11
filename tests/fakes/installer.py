"""Helpers to run the real install.sh offline against the fake Steam root
and a local fake HTTP server (GE-Proton releases, Scoop, NuGet, prefixes)."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fakes.fake_nupkg import build_fake_nupkg, sha256
from fakes.fake_prefix import build_fake_prefix_zip
from fakes.http_server import FakeServer
from fakes.steam_root import GE_TOOLMANIFEST, STUBS, FakeSteam

REPO = Path(__file__).resolve().parents[2]

# Every URL wemod-deck or install.sh can fetch, pointed at a closed port.
# Subprocess environments start from this, so a test that forgets to serve
# something fails instead of downloading from the internet.
DEAD_URL = "http://127.0.0.1:9/offline"
OFFLINE_ENV = {
    "WEMOD_DECK_URL_SCOOP_WAND": DEAD_URL,
    "WEMOD_DECK_URL_SCOOP_WEMOD": DEAD_URL,
    "WEMOD_DECK_URL_DWRITECORE": DEAD_URL,
    "WEMOD_DECK_URL_PREFIX_RELEASES": DEAD_URL,
    "WEMOD_DECK_GE_LATEST": DEAD_URL,
    "WEMOD_DECK_GE_DL": DEAD_URL,
    "WEMOD_DECK_REPO": DEAD_URL,
}
SHIPPED = ["wemod_deck", "compat", "wemod-deck", "wemod", "install.sh", "LICENSE"]


def repo_zip(dest: Path) -> Path:
    """Zip of the working tree as GitHub's "Download ZIP" lays it out."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for top in SHIPPED:
            src = REPO / top
            files = [src] if not src.is_dir() else sorted(src.rglob("*"))
            for f in files:
                if "__pycache__" in f.parts or f.is_dir() or not os.path.lexists(f):
                    continue
                info = zipfile.ZipInfo(
                    "steam-deck-wemod-main/" + str(f.relative_to(REPO))
                )
                info.external_attr = (f.lstat().st_mode & 0xFFFF) << 16
                if f.is_symlink():
                    z.writestr(info, os.readlink(f))
                else:
                    z.writestr(info, f.read_bytes())
    return dest


def ge_tarball(folder: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        files = {
            f"{folder}/proton": ((STUBS / "proton").read_bytes(), 0o755),
            f"{folder}/toolmanifest.vdf": (GE_TOOLMANIFEST.encode(), 0o644),
            f"{folder}/version": (f"1700000000 {folder}\n".encode(), 0o644),
        }
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@dataclass
class Remote:
    server: FakeServer
    env: dict[str, str]


def serve_everything(
    server: FakeServer,
    tmp: Path,
    *,
    ge_tag: str = "GE-Proton11-8",
    suffixed: bool = True,
    bad_sum: bool = False,
) -> Remote:
    asset = f"{ge_tag}-x86_64" if suffixed else ge_tag
    tar = ge_tarball(asset)
    server.redirect("/ge/latest", server.url(f"/ge/tag/{ge_tag}"))
    server.add(f"/ge/tag/{ge_tag}", "release page")
    server.add(f"/ge/dl/{ge_tag}/{asset}.tar.gz", tar)
    digest = "0" * 128 if bad_sum else hashlib.sha512(tar).hexdigest()
    server.add(f"/ge/dl/{ge_tag}/{asset}.sha512sum", f"{digest}  {asset}.tar.gz\n")

    pkg = build_fake_nupkg(tmp / "Wand-12.62.0-full.nupkg", app="wand")
    server.add("/cdn/Wand-12.62.0-full.nupkg", pkg.read_bytes())
    server.add(
        "/scoop/wand.json",
        {
            "version": "12.62.0",
            "architecture": {
                "64bit": {
                    "url": server.url("/cdn/Wand-12.62.0-full.nupkg"),
                    "hash": sha256(pkg),
                }
            },
        },
    )
    nuget = io.BytesIO()
    with zipfile.ZipFile(nuget, "w") as z:
        z.writestr("runtimes-framework/win-x64/native/DWriteCore.dll", b"DWRITE")
    server.add("/nuget/dwrite.nupkg", nuget.getvalue())

    prefix = build_fake_prefix_zip(tmp / "GE-Proton10.1.zip").read_bytes()
    server.add("/pfx/GE-Proton10.1.zip", prefix)
    server.add(
        "/pfx/releases",
        [
            {
                "tag_name": "PfxVer10.1",
                "assets": [
                    {
                        "name": "GE-Proton10.1.zip",
                        "browser_download_url": server.url("/pfx/GE-Proton10.1.zip"),
                        "size": len(prefix),
                    }
                ],
            }
        ],
    )
    env = {
        "WEMOD_DECK_GE_LATEST": server.url("/ge/latest"),
        "WEMOD_DECK_GE_DL": server.url("/ge/dl"),
        "WEMOD_DECK_URL_SCOOP_WAND": server.url("/scoop/wand.json"),
        "WEMOD_DECK_URL_DWRITECORE": server.url("/nuget/dwrite.nupkg"),
        "WEMOD_DECK_URL_PREFIX_RELEASES": server.url("/pfx/releases"),
    }
    return Remote(server, env)


def run_install(
    steam: FakeSteam,
    args: list[str],
    env: dict[str, str] | None = None,
    stdin: str = "",
) -> subprocess.CompletedProcess:
    full_env = {
        **OFFLINE_ENV,
        "HOME": str(steam.home),
        "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(REPO / "install.sh"), *args],
        env=full_env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
    )
