"""Build a Squirrel-style WeMod installer stand-in.

WeMod's setup .exe is a Squirrel package that can be opened as a zip; the app
lives under ``lib/net<ver>/``. Upstream's ``unpack_wemod`` moves the *first*
``lib/net*`` entry, so the directory entry is written first, as in real
packages. No real WeMod bytes are used.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

APP_FILES = {
    "WeMod.exe": b"MZ fake WeMod.exe\n",
    "WeMod.dll": b"MZ fake WeMod.dll\n",
    "resources/app.asar": b"fake asar\n",
}


def build_fake_nupkg(
    path: Path, *, framework: str = "net45", tamper: bool = False
) -> Path:
    """Write the fake installer to ``path``. With ``tamper=True`` the
    WeMod.exe payload differs, so its hash won't match :func:`sha256`
    of an untampered build."""
    lib = f"lib/{framework}/"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(lib, b"")
        for name, data in APP_FILES.items():
            if tamper and name == "WeMod.exe":
                data = b"MZ tampered WeMod.exe\n"
            z.writestr(lib + name, data)
        z.writestr(
            "WeMod.nuspec", b"<package><metadata><id>WeMod</id></metadata></package>"
        )
        z.writestr("[Content_Types].xml", b"<Types/>")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
