"""Turn the argv Steam gives us into a structured launch command.

Two inputs are supported:

* **Compat tool** (default): the wrapper passes exactly
  ``[<runtime>/_v2-entry-point --verb=V --] <tool>/proton V <exe> [args...]``.
  The runtime part is missing when no Steam Linux Runtime was found.
  Anything else is a :class:`ParseError`; nothing is guessed.
* **Launch Options** (``--legacy-args``): ``wemod %command%``, where Steam
  expands ``%command%`` to ``reaper ... -- steam-launch-wrapper -- <runtime>
  --verb=V -- <proton> V <exe> [args...]``. The Proton argument is the last
  one named ``proton``. Custom wine runners are not supported (scope
  non-goal) and give a :class:`ParseError`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .steam import RUNTIME_ENTRY_POINT


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class LaunchCommand:
    prefix: list[str]  # everything before Proton (runtime, reaper, ...)
    proton: str
    verb: str
    exe: str
    args: list[str] = field(default_factory=list)

    def plain(self) -> list[str]:
        """The command exactly as Steam meant it: no WeMod."""
        return [*self.prefix, self.proton, self.verb, self.exe, *self.args]


def _is_proton(arg: str) -> bool:
    return os.path.basename(arg) == "proton"


def _after_proton(prefix: list[str], rest: list[str]) -> LaunchCommand:
    proton, *tail = rest
    if len(tail) < 2:
        raise ParseError("expected '<proton> <verb> <exe>'")
    verb, exe, *args = tail
    if verb.startswith("-") or "." in verb:
        raise ParseError(f"{verb!r} is not a Proton verb")
    return LaunchCommand(list(prefix), proton, verb, exe, list(args))


def parse_compat_tool(argv: list[str]) -> LaunchCommand:
    if not argv:
        raise ParseError("no arguments")
    prefix: list[str] = []
    rest = argv
    if os.path.basename(argv[0]) == RUNTIME_ENTRY_POINT:
        if "--" not in argv:
            raise ParseError("runtime entry point without '--'")
        cut = argv.index("--") + 1
        prefix, rest = argv[:cut], argv[cut:]
        if not any(a.startswith("--verb=") for a in prefix[1:-1]):
            raise ParseError("runtime entry point without --verb=")
    if not rest or not _is_proton(rest[0]):
        raise ParseError(f"expected Proton, got {rest[:1]}")
    cmd = _after_proton(prefix, rest)
    if prefix:
        runtime_verb = next(a for a in prefix if a.startswith("--verb="))[7:]
        if runtime_verb != cmd.verb:
            raise ParseError(f"runtime verb {runtime_verb!r} != Proton verb")
    return cmd


def parse_launch_options(argv: list[str]) -> LaunchCommand:
    """``wemod %command%``: Proton is the last argument named ``proton``
    (Steam always calls its compat tool script that)."""
    indexes = [i for i, a in enumerate(argv) if _is_proton(a)]
    if not indexes:
        raise ParseError(
            "no Proton in the Launch Options command; select a Proton version "
            "in the game's Compatibility settings (custom wine runners are "
            "not supported)"
        )
    at = indexes[-1]
    return _after_proton(argv[:at], argv[at:])


def parse(argv: list[str], *, legacy: bool = False) -> LaunchCommand:
    return parse_launch_options(argv) if legacy else parse_compat_tool(argv)


def windows_game_path(exe: str, cwd: str) -> str:
    """Game path as upstream passes it to ``start``: relative to the working
    directory (Steam starts games in their install dir) with ``\\\\``
    separators. Kept byte-for-byte from upstream because it is
    field-tested; non-files (URLs etc.) pass through unchanged."""
    if not os.path.isfile(exe):
        return exe
    rel = os.path.relpath(os.path.realpath(exe), os.path.realpath(cwd))
    return rel.replace(os.sep, "\\\\")


def windows_abs_path(path: str) -> str:
    """``/a/b`` → ``Z:\\\\a\\\\b`` (upstream ``winpath``)."""
    return "Z:" + path.replace(os.sep, "\\\\")
