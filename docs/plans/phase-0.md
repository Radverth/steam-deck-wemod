# Phase 0: baseline and test harness

## Goal
Get a reproducible baseline of upstream 1.543 under test on the VPS, with no
behaviour changes, so later phases can change the launcher safely.

## Approach
1. Import upstream `DeckCheatz/wemod-launcher` (main @ `3dd1e02`, `script_version = "1.543"`)
   into `Radverth/steam-deck-wemod` as `main`; tag it `upstream-1.543`.
   (Tom chose this repo instead of a GitHub fork named `wemod-deck`.)
2. Commit Tom's field-tested installer as `reference/install-wemod-launcher.sh`.
3. Replace upstream's `black.yml` (it reformats, bumps the version, force-pushes
   and auto-syncs `main`/`dev`, none of which we want) with `ci.yml`:
   ruff, shellcheck, pytest on `ubuntu-latest`.
4. `tests/fakes/`:
   - `steam_root.py`: builds a fake Steam root in a temp `HOME`: two libraries
     (internal plus an "SD card" path) in `libraryfolders.vdf`, `appmanifest_1628350.acf`
     with a stub `_v2-entry-point`, `compatibilitytools.d/GE-Proton11-7-x86_64/` with a
     stub `proton` and realistic `toolmanifest.vdf`, a plain game and a "launcher" game.
     Stubs log argv/env as JSON lines and then exec the rest of argv.
   - `fake_nupkg.py`: a Squirrel-like zip containing `lib/net45/WeMod.exe`.
5. Characterisation tests for the current argument handling, run against the
   **unmodified** upstream modules with env set up and popups/network stubbed.
   Scenarios: plain Launch Options, compat tool, custom runner, SD-card library.
   They record today's behaviour, including known-bad behaviour.
6. `docs/architecture-current.md`: module map, import-time globals, every popup,
   network calls, destructive operations.
7. `CHANGELOG.md`, `docs/decisions/0001-*.md`.

## Files touched
New: `reference/`, `tests/`, `docs/`, `pyproject.toml`, `requirements-dev.txt`,
`.github/workflows/ci.yml`, `CHANGELOG.md`, `.gitignore` additions.
Removed: `.github/workflows/black.yml`. Upstream `src/` is **not** changed.

## Risks
- Upstream computes globals at import (`consts.py`), reads/writes `wemod.conf`
  and may pip-install or show popups. Tests must isolate `HOME`, `cwd` and
  `sys.modules`, and stub `FreeSimpleGUI` so nothing touches the network or a display.
- Lint scope: ruff runs on new code only (`tests/`); upstream `src/` stays as-is
  until it's rewritten, so lint noise doesn't hide real changes.

## Test plan
`pytest` locally and in CI; `shellcheck` on the fake stubs. Deck: nothing to test.
