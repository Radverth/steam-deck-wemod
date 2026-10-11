"""Run upstream ``wemod.run()`` headless and report the command it builds.

Usage: python upstream_driver.py <src-copy> <out.json> [launcher argv...]

Imports the unmodified upstream modules from ``<src-copy>`` (a temp copy, so
``wemod.conf``/``wemod.log`` writes stay out of the repo) with:
- popups, network and FreeSimpleGUI replaced by stubs that record and raise;
- ``init``, ``troubleshooter`` and the early-close monitor disabled;
- ``subprocess.Popen`` replaced, so the final command is captured, not run.

Writes ``{"final": [...], "init": [proton, iswine], "blocked": [[kind, args], ...],
"error": str|None}`` to ``<out.json>``.
"""

from __future__ import annotations

import json
import sys
import types


class Blocked(Exception):
    pass


def main() -> None:
    src, out, *argv = sys.argv[1:]
    result: dict = {"final": None, "init": None, "blocked": [], "error": None}

    gui = types.ModuleType("FreeSimpleGUI")

    def _no_gui(name):
        raise Blocked(f"FreeSimpleGUI.{name} used")

    gui.__getattr__ = _no_gui
    sys.modules["FreeSimpleGUI"] = gui

    import urllib.request

    def _no_net(*a, **k):
        raise Blocked(f"network access: {a[:1]}")

    urllib.request.urlopen = _no_net

    sys.path.insert(0, src)
    import coreutils

    def _popup(kind):
        def f(*a, **k):
            result["blocked"].append([kind, [str(x) for x in a[:2]]])
            raise Blocked(f"{kind} popup: {a[:2]}")

        return f

    for name in (
        "show_message",
        "popup_options",
        "get_user_input",
        "exit_with_message",
    ):
        setattr(coreutils, name, _popup(name))
    coreutils.http_get = _no_net

    sys.argv = ["wemod", *argv]
    try:
        import wemod

        captured: list[list[str]] = []

        class FakePopen:
            returncode = 0

            def __init__(self, cmd, *a, **k):
                captured.append(list(cmd))

            def communicate(self):
                return b"", b""

        def fake_init(proton, iswine=False):
            result["init"] = [proton, iswine]

        wemod.init = fake_init
        wemod.troubleshooter = lambda: None
        wemod.monitor_file = lambda *a, **k: None
        wemod.subprocess = types.SimpleNamespace(
            Popen=FakePopen, PIPE=-1, run=_popup("subprocess.run")
        )
        wemod.run()
        result["final"] = captured[0] if captured else None
    except BaseException as e:  # noqa: BLE001 - report everything to the test
        result["error"] = f"{type(e).__name__}: {e}"

    with open(out, "w") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
