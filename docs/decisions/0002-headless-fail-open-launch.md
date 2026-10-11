# 0002: Headless, fail-open launch through a host-side compat tool

Date: 2026-10-11. Status: accepted (Phase 1).

## Context
Upstream asks up to a dozen Tk questions around a launch, which is unusable in
Game Mode. The reference installer proved that a compat tool without
`require_tool_appid`, which starts the Steam Linux Runtime itself, lets the
launcher run on the host while Proton runs in the container.

## Decision
- The compat tool (`compat/proton`) stays a small bash wrapper with the
  reference's field-tested routing. Machine-specific values live in
  `tool.conf` (written with `printf %q`), so the wrapper itself is a static,
  shellchecked file.
- `wemod-deck launch` is Python, **stdlib only**, Python 3.9+. No venv,
  pip, FreeSimpleGUI or Tk, so a SteamOS update can't break a venv.
- Every decision has a default. Errors before the game starts are logged and
  written to `status.json`, and the original command is `exec`'d unchanged.
  "The game always starts" beats "WeMod always starts".
- The final command is `exec`'d, so there is no post-game step (the
  troubleshooter becomes `doctor` / `reset-prefix`).
- Compat-tool argv is parsed strictly; anything unexpected is a parse error
  and falls open. The guessing parser survives only for Launch Options mode,
  where Proton is the last argument named `proton`.
- Data under XDG dirs: config `~/.config/wemod-deck/config.toml`, data
  `~/.local/share/wemod-deck/`, downloads under `~/.cache/wemod-deck/`
  (never `/tmp`, which is tmpfs).
- Code installs to `~/wemod-deck`, not `~/wemod-launcher`, so an existing
  upstream install is neither updated to our code nor overwritten. Its
  login and binaries are copied once (never moved).

## Consequences
- Upstream `src/` is deleted. Git self-update goes with it; re-running
  `install.sh` updates.
- Tom's old `~/wemod-launcher/wemod %command%` lines keep running the old
  launcher until he switches.
