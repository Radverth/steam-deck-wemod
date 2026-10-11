"""Fake prebuilt WeMod prefix zip (layout of DeckCheatz/BuiltPrefixes-dev)."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

FILES = {
    "version": b"1700000000 GE-Proton10-1\n",
    "pfx/system.reg": b"WINE REGISTRY prebuilt\n",
    "pfx/drive_c/windows/Microsoft.NET/Framework64/v4.0.30319/clr.dll": b"MZ clr\n",
    "pfx/drive_c/windows/system32/kernel32.dll": b"MZ prebuilt kernel32\n",
    "pfx/drive_c/users/steamuser/Documents/readme.txt": b"prebuilt doc\n",
    "pfx/drive_c/users/steamuser/Saved Games/Game/save.dat": b"PREBUILT SAVE\n",
    "pfx/drive_c/users/steamuser/AppData/Roaming/WeMod/prebuilt-login": b"x\n",
    "pfx/.wemod_installer": b"",
}
LINKS = {
    "pfx/dosdevices/c:": "../drive_c",
    "pfx/dosdevices/z:": "/",
}


def _link(z: zipfile.ZipFile, name: str, target: str) -> None:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    z.writestr(info, target)


def build_fake_prefix_zip(
    path: Path,
    *,
    extra: dict | None = None,
    links: dict | None = None,
    marker: bool = True,
) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pfx/", b"")
        for name, data in {**FILES, **(extra or {})}.items():
            if name == "pfx/.wemod_installer" and not marker:
                continue
            z.writestr(name, data)
        for name, target in {**LINKS, **(links or {})}.items():
            _link(z, name, target)
    return path
