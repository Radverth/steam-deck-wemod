"""Small HTTP helpers (urllib only). Every URL can be overridden with an
environment variable ``WEMOD_DECK_URL_<KEY>``; tests point them at a local
fake server."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import urllib.request
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

URLS = {
    "SCOOP_WAND": "https://raw.githubusercontent.com/Calinou/scoop-games/"
    "refs/heads/master/bucket/wand.json",
    "SCOOP_WEMOD": "https://raw.githubusercontent.com/Calinou/scoop-games/"
    "refs/heads/master/bucket/wemod.json",
    "DWRITECORE": "https://api.nuget.org/v3-flatcontainer/"
    "microsoft.windowsappsdk.dwrite/{version}/"
    "microsoft.windowsappsdk.dwrite.{version}.nupkg",
    "PREFIX_RELEASES": "https://api.github.com/repos/DeckCheatz/"
    "BuiltPrefixes-dev/releases",
}


class DownloadError(OSError):
    pass


def url(key: str, **fmt: str) -> str:
    return os.environ.get(f"WEMOD_DECK_URL_{key}", URLS[key]).format(**fmt)


def _open(address: str, timeout: float):
    req = urllib.request.Request(address, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(address: str, timeout: float = 15):
    try:
        with _open(address, timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise DownloadError(f"{address}: {e}") from e


def download(
    address: str,
    dest: Path,
    *,
    sha256: str | None = None,
    timeout: float = 30,
) -> Path:
    """Stream ``address`` to ``dest`` via ``dest.part``; verify ``sha256`` if
    given. On any failure the partial file is removed and nothing is left
    at ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    try:
        with _open(address, timeout) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
                f.write(chunk)
        if sha256 and digest.hexdigest().lower() != sha256.lower():
            raise DownloadError(f"{address}: checksum mismatch")
        os.replace(part, dest)
        return dest
    except (OSError, http.client.HTTPException) as e:
        part.unlink(missing_ok=True)
        if isinstance(e, DownloadError):
            raise
        raise DownloadError(f"{address}: {e}") from e
