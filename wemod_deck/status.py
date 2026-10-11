"""Logging and the status file other tools (``doctor``, the Decky plugin) read.

``status.json``::

    {"updated": "...", "last": {...}, "apps": {"<appid>": {...}}}

where each entry is ``{"time", "appid", "state", "message"}``. ``state`` is
``"ok"`` (launched with the app), ``"plain"`` (launched without it, on
purpose) or ``"error"`` (launched without it because something failed).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import tempfile
import time
from pathlib import Path

from . import paths

log = logging.getLogger("wemod_deck")


def setup_logging(level: str = "info", *, stderr: bool = True) -> None:
    """Log to the rotating launch log (and stderr). Safe to call twice.
    If the log file can't be opened, logging continues on stderr only."""
    log.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        path = paths.log_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError as e:
        stderr = True
        print(f"wemod-deck: cannot open log file: {e}", file=sys.stderr)
    if stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("wemod-deck: %(levelname)s %(message)s"))
        log.addHandler(sh)


def read_status(path: Path | None = None) -> dict:
    path = path or paths.status_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def write_status(appid: str | None, state: str, message: str) -> None:
    """Record the outcome of a launch. Never raises."""
    try:
        path = paths.status_file()
        data = read_status(path)
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "appid": appid,
            "state": state,
            "message": message,
        }
        data["updated"] = entry["time"]
        data["last"] = entry
        apps = data.get("apps") if isinstance(data.get("apps"), dict) else {}
        if appid:
            apps[str(appid)] = entry
        data["apps"] = apps
        atomic_write(path, json.dumps(data, indent=2) + "\n")
    except Exception as e:  # noqa: BLE001 - status must never break a launch
        log.warning("could not write status file: %s", e)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
