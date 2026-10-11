"""``wemod-deck launch``: start a game with Wand/WeMod, headless, fail-open.

Every decision has a default and nothing asks the player anything. If
anything goes wrong before the game starts, the error is logged and
recorded in ``status.json`` and the game is started exactly as Steam asked
(plain Proton). The process is replaced (``exec``) by the final command.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import app, backup, login, net, paths, prefix, status
from . import argv as argv_mod
from .config import Config
from .status import log
from .steam import RUNTIME_ENTRY_POINT

LAUNCH_VERB = "waitforexitandrun"


@dataclass
class Decision:
    command: list[str]
    state: str  # "ok" | "plain" | "error", see status.py
    message: str
    env: dict[str, str] = field(default_factory=dict)


def _plain(cmd: argv_mod.LaunchCommand, state: str, message: str) -> Decision:
    return Decision(cmd.plain(), state, message)


def install_bat() -> Path:
    """Copy the batch file into the data dir (CRLF line endings for cmd)."""
    data = (Path(__file__).parent / "data" / "wemod-deck.bat").read_bytes()
    data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    target = paths.bat_file()
    if not target.is_file() or target.read_bytes() != data:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        os.replace(part, target)
    return target


def decide(
    cmd: argv_mod.LaunchCommand,
    cfg: Config,
    appid: str | None,
    env: dict[str, str],
    cwd: str,
) -> Decision:
    """Work out what to run. May download the app or a prefix the first
    time; raises on unexpected errors (the caller falls back to plain)."""
    if cmd.verb != LAUNCH_VERB:
        return _plain(cmd, "plain", f"verb {cmd.verb} goes straight to Proton")

    compat = env.get("STEAM_COMPAT_DATA_PATH")
    if not compat:
        return _plain(cmd, "error", "STEAM_COMPAT_DATA_PATH is not set")
    compatdata = Path(compat)

    notes = []
    pend = backup.pending(appid)
    if pend:  # saves waiting after reset-prefix: before anything else
        restored = _restore_pending(cmd, appid, compatdata, pend, env)
        if isinstance(restored, Decision):
            return restored
        notes.append(restored)

    if not cfg.enabled_for(appid):
        return _plain(
            cmd, "plain", _join(notes, "disabled for this game in config.toml")
        )
    if not (compatdata / "pfx" / "drive_c").is_dir():
        return _plain(cmd, "plain", "first launch: Proton is creating the prefix")

    try:
        if not app.is_installed(cfg.app):
            log.info("%s is not installed yet, downloading it", cfg.app)
            app.install(cfg.app)
        prefix.ensure(compatdata, cmd.proton, appid or compatdata.name)
    except backup.BackupError as e:
        return _plain(cmd, "error", f"no save backup possible, prefix left alone: {e}")
    except (app.AppError, prefix.PrefixError, net.DownloadError, OSError) as e:
        return _plain(cmd, "error", f"{type(e).__name__}: {e}")

    login.migrate_legacy()  # once; keeps an upstream login before re-linking
    for action in login.link_logins(compatdata, appid or compatdata.name):
        log.info("login: %s", action)
    app.ensure_dwritecore(cfg.app)  # never raises; no-op when present

    bat = install_bat()
    command = [
        *cmd.prefix,
        cmd.proton,
        cmd.verb,
        "start",
        argv_mod.windows_abs_path(str(bat)),
        argv_mod.windows_game_path(cmd.exe, cwd),
        *cmd.args,
    ]
    exe = "Z:" + str(app.exe_path(cfg.app)).replace(os.sep, "\\")
    message = _join(notes, f"started with {cfg.app}")
    return Decision(command, "ok", message, {"WEMOD_DECK_EXE": exe})


def _join(notes: list[str], message: str) -> str:
    return "; ".join([*notes, message])


def build_prefix(cmd: argv_mod.LaunchCommand, env: dict[str, str]) -> bool:
    """Have Proton create the prefix without starting the game: the runtime
    part of the command with ``--verb=run``, then ``proton run cmd.exe /c
    exit``. Returns True if ``pfx/drive_c`` exists afterwards."""
    runtime: list[str] = []
    for i, arg in enumerate(cmd.prefix):
        if os.path.basename(arg) == RUNTIME_ENTRY_POINT:
            runtime = [
                "--verb=run" if a.startswith("--verb=") else a for a in cmd.prefix[i:]
            ]
            break
    command = [*runtime, cmd.proton, "run", "cmd.exe", "/c", "exit"]
    log.info("building the prefix first: %s", command)
    try:
        r = subprocess.run(
            command, env=env, capture_output=True, text=True, timeout=600
        )
        if r.returncode:
            log.warning("prefix build exited %s: %s", r.returncode, r.stderr[-2000:])
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("prefix build failed: %s", e)
    compat = Path(env["STEAM_COMPAT_DATA_PATH"])
    return (compat / "pfx" / "drive_c").is_dir()


def _restore_pending(cmd, appid, compatdata: Path, pend: dict, env) -> str | Decision:
    """Put saves back after reset-prefix. Returns a note for the status, or
    a plain-launch Decision if it can't be done yet (it is retried on the
    next launch; the marker stays)."""
    archive = Path(pend["archive"])
    if not (compatdata / "pfx" / "drive_c").is_dir() and not build_prefix(cmd, env):
        return _plain(
            cmd,
            "error",
            "could not build the prefix before restoring your saves; "
            "starting without them, they are restored on the next launch",
        )
    try:
        counts = backup.restore(archive, compatdata, mode="full")
    except backup.BackupError as e:
        return _plain(
            cmd, "error", f"saves not restored yet ({e}); retried next launch"
        )
    backup.clear_pending(appid)
    return f"saves restored from {archive.name} ({counts['restored']} entries)"


def _handover(execute, command: list[str], extra_env: dict[str, str]) -> None:
    """Tell the compat tool we got this far (it falls back to plain Proton
    otherwise), then replace this process with ``command``."""
    env = {**os.environ, **extra_env}
    ready = env.pop("WEMOD_DECK_READY_FILE", None)
    if ready:
        try:
            Path(ready).touch()
        except OSError as e:
            log.warning("could not create ready file %s: %s", ready, e)
    for h in log.handlers:
        h.flush()
    execute(command[0], command, env)


def main(
    argv: list[str],
    cfg: Config,
    warnings: list[str],
    *,
    legacy: bool = False,
    execute=os.execvpe,
) -> int:
    status.setup_logging(cfg.log_level, stderr=True)
    for w in warnings:
        log.warning("config: %s", w)
    appid = os.environ.get("SteamAppId") or os.environ.get("STEAM_COMPAT_APP_ID")
    log.info("launch appid=%s legacy=%s argv=%s", appid, legacy, argv)

    try:
        cmd = argv_mod.parse(argv, legacy=legacy)
    except argv_mod.ParseError as e:
        # We can't tell the parts apart; run what Steam gave us untouched.
        log.error("cannot parse the launch command (%s); running it unchanged", e)
        status.write_status(appid, "error", f"cannot parse launch command: {e}")
        if not argv:
            return 1
        _handover(execute, argv, {})
        return 1  # only reached when execute is a test double

    try:
        decision = decide(cmd, cfg, appid, dict(os.environ), os.getcwd())
    except Exception as e:  # noqa: BLE001 - fail open: the game must start
        log.exception("unexpected error, starting the game without %s", cfg.app)
        decision = _plain(cmd, "error", f"unexpected {type(e).__name__}: {e}")

    level = log.error if decision.state == "error" else log.info
    level("%s: %s", decision.state, decision.message)
    log.info("exec %s", decision.command)
    status.write_status(appid, decision.state, decision.message)
    _handover(execute, decision.command, decision.env)
    return 0  # only reached when execute is a test double
