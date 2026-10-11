"""Command line: ``python3 -m wemod_deck <command>``."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, config, paths, status


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wemod-deck",
        description="Run Wand (formerly WeMod) with Steam games on the Steam Deck.",
    )
    p.add_argument("--version", action="version", version=f"wemod-deck {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    launch = sub.add_parser(
        "launch",
        help="start a game through Proton with the app (used by the compat tool)",
    )
    launch.add_argument(
        "--legacy-args",
        action="store_true",
        help="argv is a Launch Options %%command%% line, not compat-tool argv",
    )
    launch.add_argument("argv", nargs=argparse.REMAINDER)

    sub.add_parser("doctor", help="check the installation and print what's wrong")

    reset = sub.add_parser(
        "reset-prefix",
        help="move a game's Proton prefix aside so Steam builds a fresh one",
    )
    reset.add_argument("appid")
    reset.add_argument(
        "--keep-old",
        action="store_true",
        help="move the old prefix aside instead of deleting it",
    )

    setup = sub.add_parser("setup", help="download or update the app")
    setup.add_argument("--force", action="store_true", help="re-download")

    use = sub.add_parser(
        "use",
        help="switch between Wand (12.x) and WeMod (11.x) and download it",
    )
    use.add_argument("app", choices=config.APPS)

    bk = sub.add_parser("backups", help="list, create or restore save backups")
    bsub = bk.add_subparsers(dest="backups_command", required=True)
    bl = bsub.add_parser("list", help="list backups (newest first)")
    bl.add_argument("appid", nargs="?")
    bc = bsub.add_parser("create", help="back up a game's saves now")
    bc.add_argument("appid")
    br = bsub.add_parser(
        "restore",
        help="put a backup back (the current state is backed up first)",
    )
    br.add_argument("appid")
    br.add_argument(
        "name", nargs="?", help="backup name or its start (default: newest)"
    )
    br.add_argument(
        "--dry-run", action="store_true", help="only show what would change"
    )

    st = sub.add_parser("status", help="show the last launch result")
    st.add_argument("appid", nargs="?")
    return p


def _use(app_name: str) -> int:
    from . import app

    try:
        config.set_app(paths.config_file(), app_name)
    except config.ConfigError as e:
        status.log.error("%s; fix config.toml first", e)
        return 1
    cfg, _ = config.load(paths.config_file())
    print(f"Now using {app_name} (saved in {paths.config_file()}).")
    code = app.setup_cli(cfg)
    if code == 0:
        print(
            f"Games launched with the compatibility tool now start {app_name}. "
            "Its login is separate: log in once more."
        )
    return code


def split_launch_args(argv: list[str]) -> tuple[bool, list[str]]:
    """``launch [--legacy-args] [--] <argv...>``, parsed by hand so the
    game's own arguments are never mistaken for our options."""
    legacy = argv[:1] == ["--legacy-args"]
    if legacy:
        argv = argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    return legacy, argv


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["launch"] and argv[1:2] not in (["-h"], ["--help"]):
        from . import launch

        try:
            cfg, warnings = config.load(paths.config_file())
        except Exception as e:  # noqa: BLE001 - never block a launch on config
            cfg, warnings = config.Config(), [f"config ignored: {e}"]
        legacy, rest = split_launch_args(argv[1:])
        return launch.main(rest, cfg, warnings, legacy=legacy)

    args = build_parser().parse_args(argv)
    cfg, warnings = config.load(paths.config_file())

    status.setup_logging(cfg.log_level, stderr=True)
    for w in warnings:
        status.log.warning("config: %s", w)

    if args.command == "doctor":
        from . import doctor

        return doctor.main(cfg)
    if args.command == "reset-prefix":
        from . import prefix

        return prefix.reset_prefix_cli(
            args.appid, keep_old=args.keep_old, keep=cfg.backups_keep
        )
    if args.command == "setup":
        from . import app

        return app.setup_cli(cfg, force=args.force)
    if args.command == "use":
        return _use(args.app)
    if args.command == "backups":
        from . import backup

        return backup.cli(args, cfg)
    if args.command == "status":
        data = status.read_status()
        if args.appid:
            data = data.get("apps", {}).get(args.appid, {})
        print(json.dumps(data, indent=2) if data else "no launches recorded yet")
        return 0
    return 2  # pragma: no cover - argparse enforces the choices


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
