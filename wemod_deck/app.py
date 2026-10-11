"""Download and unpack Wand (formerly WeMod) from WeMod's own CDN.

The download URL and SHA-256 come from the Scoop manifest
(``wand.json`` / ``wemod.json``). The package is a Squirrel nupkg (a zip);
the app lives in ``lib/net*/``. Nothing is redistributed by this project.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from . import net, paths
from .config import Config
from .status import log

EXE_NAMES = {"wand": "Wand.exe", "wemod": "WeMod.exe"}
# Chromium (Electron) loads a DWriteCore.dll next to the exe in preference to
# Wine's dwrite.dll, which crashes the renderer (blank Map panel). Ported from
# upstream setup.ensure_dwritecore.
DWRITECORE_VERSION = "2.1.0"
DWRITECORE_MEMBER = "runtimes-framework/win-x64/native/DWriteCore.dll"
VERSION_FILE = ".wemod-deck-version"


class AppError(RuntimeError):
    pass


def exe_path(app: str) -> Path:
    return paths.app_dir(app) / EXE_NAMES[app]


def is_installed(app: str) -> bool:
    return exe_path(app).is_file()


def installed_version(app: str) -> str | None:
    try:
        return (paths.app_dir(app) / VERSION_FILE).read_text().strip() or None
    except OSError:
        return None


def manifest(app: str) -> tuple[str, str, str]:
    """``(version, url, sha256)`` from the Scoop manifest."""
    data = net.get_json(net.url(f"SCOOP_{app.upper()}"))
    try:
        arch = data["architecture"]["64bit"]
        return str(data["version"]), arch["url"], arch["hash"]
    except (KeyError, TypeError) as e:
        raise AppError(f"Scoop manifest for {app} has no 64-bit url/hash") from e


def unpack(package: Path, dest: Path, app: str) -> None:
    """Extract the ``lib/net*/`` folder that holds the app exe into ``dest``."""
    exe = EXE_NAMES[app]
    try:
        with zipfile.ZipFile(package) as z:
            names = z.namelist()
            hits = [
                n for n in names if n.startswith("lib/net") and n.endswith("/" + exe)
            ]
            if not hits:
                raise AppError(f"{exe} not found in {package.name}")
            lib = hits[0].rsplit("/", 1)[0] + "/"
            root = dest.resolve()
            for info in z.infolist():
                if not info.filename.startswith(lib) or info.is_dir():
                    continue
                target = (dest / info.filename[len(lib) :]).resolve()
                if root not in target.parents:
                    raise AppError(f"unsafe path in package: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    except (zipfile.BadZipFile, OSError) as e:
        raise AppError(f"cannot unpack {package.name}: {e}") from e


def install(app: str, *, force: bool = False) -> bool:
    """Install or update the app. Returns True if something changed.
    The old install is only replaced once the new one is fully unpacked."""
    version, address, sha256 = manifest(app)
    if not force and is_installed(app) and installed_version(app) == version:
        log.info("%s %s already installed", app, version)
        return False

    cache = paths.cache_dir() / "downloads"
    package = cache / os.path.basename(address)
    log.info("downloading %s %s from %s", app, version, address)
    net.download(address, package, sha256=sha256, timeout=60)

    final = paths.app_dir(app)
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{app}-new-", dir=final.parent))
    try:
        unpack(package, staging, app)
        (staging / VERSION_FILE).write_text(version + "\n")
        dwrite = final / "DWriteCore.dll"
        if dwrite.is_file():
            shutil.copy2(dwrite, staging / "DWriteCore.dll")
        old = final.with_name(f".{app}-old")
        shutil.rmtree(old, ignore_errors=True)
        if final.exists():
            final.rename(old)
        staging.rename(final)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        package.unlink(missing_ok=True)
    log.info("installed %s %s to %s", app, version, final)
    return True


def ensure_dwritecore(app: str) -> bool:
    """Put DWriteCore.dll next to the exe. Never raises: without it the app
    still runs, only the Map panel stays blank."""
    target = paths.app_dir(app) / "DWriteCore.dll"
    if target.is_file():
        return True
    try:
        address = net.url("DWRITECORE", version=DWRITECORE_VERSION)
        with tempfile.TemporaryDirectory(dir=_tmp_parent()) as tmp:
            package = net.download(address, Path(tmp) / "dwrite.nupkg", timeout=30)
            with zipfile.ZipFile(package) as z:
                data = z.read(DWRITECORE_MEMBER)
            part = target.with_name(target.name + ".part")
            part.write_bytes(data)
            os.replace(part, target)
    except Exception as e:  # noqa: BLE001 - optional component
        log.warning("could not install DWriteCore.dll: %s", e)
        return False
    log.info("installed DWriteCore.dll (%d bytes)", len(data))
    return True


def _tmp_parent() -> Path:
    """Large temporary files go under ~/.cache, not /tmp (tmpfs on SteamOS)."""
    p = paths.cache_dir() / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def setup_cli(cfg: Config, *, force: bool = False) -> int:
    from . import login

    login.migrate_legacy()
    try:
        install(cfg.app, force=force)
    except (AppError, net.DownloadError) as e:
        log.error("%s", e)
        return 1
    ensure_dwritecore(cfg.app)
    print(f"{cfg.app} {installed_version(cfg.app)} ready at {exe_path(cfg.app)}")
    return 0
