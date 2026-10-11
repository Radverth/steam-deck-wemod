# Phase 1: compat tool first, headless launch

Status: **approved 2026-10-11 (Tom: "Go, but default to Wand")**. Branch
`agent/phase-1-headless` (stacked on Phase 0, PR #1).

## Goal
Choosing "WeMod + GE-Proton" in a game's Compatibility menu starts the game
with Wand/WeMod and **no popups at any point**. Every decision has a default.
Anything that goes wrong is written to a log and a status file, and the
game still starts (without WeMod) whenever possible.

## Decisions (agreed)
1. **Wand by default.** WeMod has been renamed Wand (12.x, Scoop `wand.json`,
   still on WeMod's CDN `storage-cdn.wemod.com`). Upstream says WeMod 11.x is
   near end of life (upstream PR #318). `app = "wand" | "wemod"` in the
   config; **default `wand`**. Checked on the real 12.62.0 package (file
   listing + `package.json` only): same `lib/net45/` layout, contains
   `Wand.exe` (and a `WeMod.exe` stub), `productName` is `Wand`, so its
   login should live in `AppData/Roaming/Wand`. Both `Roaming/Wand` and
   `Roaming/WeMod` are linked to central folders, so Wand can find an old
   WeMod login if it migrates one.
2. **Upstream `src/` modules are deleted in this phase.** They hold every
   popup and every destructive path. The pinned argument-parsing behaviour
   moves to tests of the new legacy parser. Git self-update goes with them
   (earlier than Phase 3 planned): re-running `install.sh` updates.
3. **"Game closed too early" (launcher games) until Phase 4:** WeMod stays
   open; the player closes it or uses Steam ▸ Exit Game.
4. **Python:** stdlib only (no venv, pip, FreeSimpleGUI or Tk). `tomllib` is
   used when present (3.11+); on older Pythons a small parser for the subset
   our config uses takes over, so the launcher needs only Python 3.9 like the
   reference installer.

## Design

### Pieces
```
install.sh                        ported from reference/, installs everything below
compat/                           templates for the compat tool
  proton                          host-side wrapper (bash)
  compatibilitytool.vdf.in
wemod_deck/                       new Python package, stdlib only
  __main__.py, cli.py             `wemod-deck launch|doctor|reset-prefix|setup|status`
  argv.py                         deterministic compat-tool parser + --legacy-args parser
  steam.py                        VDF/ACF parsing, libraries, runtime entry point lookup
  config.py                       ~/.config/wemod-deck/config.toml, global + per-AppID
  paths.py                        XDG data/config/cache/state locations
  status.py                       status.json + rotating log
  app.py                          WeMod/Wand download, unpack, DWriteCore
  prefix.py                       prebuilt prefix pick/download/unpack (non-destructive)
  login.py                        shared login symlink (ported syncwemod, headless)
  launch.py                       orchestrates a launch, fail-open
  data/wemod-deck.bat             headless replacement for wemod.bat
wemod                             shim: `exec python3 -m wemod_deck launch --legacy-args "$@"`
```

### Compat-tool wrapper (`compat/proton`)
Ported from the reference wrapper. Behaviour the reference already gets
right (field-tested lessons 3–6) is kept exactly:
- our `toolmanifest.vdf` drops `require_tool_appid`, so the wrapper runs on the host;
- the wrapper finds `_v2-entry-point` through `libraryfolders.vdf` →
  `appmanifest_<id>.acf` → `installdir`, on every library including the SD card;
- verbs other than `waitforexitandrun` → `entry-point --verb=V -- GE/proton V …`;
- no `pfx/drive_c` yet (first launch) → plain Proton;
- `wemod-deck` or `python3` missing → plain Proton.

Changes: it calls `python3 -m wemod_deck launch -- <entry-point --verb=V --> GE/proton V exe args…`
with `PYTHONPATH` pointing at the install, and exports `WEMOD_DECK_TOOL=1`.
Per-AppID opt-out lives in TOML, so `wemod-deck` (not bash) checks it and
runs plain Proton itself.

### Fail-open launch (`launch.py`)
`wemod-deck launch` wraps everything before the game starts in one
try/except. On **any** error, or if WeMod isn't ready, it logs, writes
`status.json`, and `os.execvp`s the plain command it was given. The game
always starts. Only a broken Python can stop a launch, and the wrapper
checks that first.

Steps, all headless:
1. Parse argv (below). AppID from `SteamAppId`, else `STEAM_COMPAT_APP_ID`.
2. Config: `enabled = false` for the AppID (or globally) → plain Proton.
3. No `pfx/drive_c` → plain Proton (Proton builds the prefix).
4. WeMod/Wand not installed → try `setup` (timeout-bounded); if it fails, plain Proton.
5. Prefix has no `pfx/.wemod_installer` → download the **closest** prebuilt
   prefix (upstream priority order, no prompt; today GE-Proton 11 picks
   `PfxVer10.1`), cached under `~/.cache/wemod-deck/`, then unpack it
   **non-destructively**: never overwrite an existing file under
   `drive_c/users/`. Only missing files are added there. Elsewhere,
   overwriting is fine (Windows/.NET files). This is the stop-gap until the
   Phase 2 backups. GitHub releases list cached for 24 h; requests have a
   timeout.
6. Shared login: `drive_c/users/steamuser/AppData/Roaming/{Wand,WeMod}` →
   symlinks to `~/.local/share/wemod-deck/login/{wand,wemod}/`. If the prefix has a
   real directory with data and the central one has data too, **central
   wins** and the prefix copy is **moved** to
   `~/.local/share/wemod-deck/displaced-login/<appid>-<ts>/`, never deleted.
7. DWriteCore.dll next to the app exe (ported, skipped if present).
8. Build and `execvp`:
   `<entry-point --verb=V --> GE/proton waitforexitandrun start Z:\…\wemod-deck.bat <game> args…`
   with `WEMOD_DECK_EXE=Z:\…\WeMod.exe` in the environment. The working
   directory is left as Steam set it (game dir), as upstream does.

### Headless batch file (`data/wemod-deck.bat`)
Based on `wemod.bat`, with the two places that block removed: `pause` when
WeMod's PID isn't found, and the loop waiting for the Linux popup. It takes
the app exe from `%WEMOD_DECK_EXE%` instead of computing paths. Early close
follows decision 3. Phase 4 replaces this file.

### Argument parsing (`argv.py`)
- **Compat-tool mode (default):** exactly
  `[<…/_v2-entry-point> --verb=V --] <…/proton> V <exe> [args…]`. The
  runtime part is optional (no runtime found). Anything else is a
  `ParseError` → fail open. No guessing.
- **`--legacy-args`** (Launch Options `wemod %command%`): ported upstream
  logic restricted to Steam + Proton (`reaper … -- steam-launch-wrapper -- …`),
  with the `PROTON[1]` bug fixed. Custom/external wine runners are rejected
  with a clear log line (non-goal).

### Config (`~/.config/wemod-deck/config.toml`)
```toml
app = "wand"             # or "wemod"
enabled = true           # global default
log_level = "info"

[apps."1234560"]
enabled = false          # this game runs plain GE-Proton
```
A missing file means defaults. An invalid file means defaults plus a status
warning; it never blocks a launch.

### Data layout (`~/.local/share/wemod-deck/`)
`app/<wemod|wand>/` (binaries), `login/<app>/`, `bin/wemod-deck.bat`,
`logs/launch.log` (rotating, 5 × 1 MB), `status.json`, `displaced-login/`, `old-prefixes/`.
**Migration:** if `~/wemod-launcher/wemod_data/` exists, `install.sh`
**copies** `wemod_bin` and `wemod_login` into the new layout (the old
folder stays). On the next launch each game's login symlink is pointed at
the new location.

### CLI
- `wemod-deck doctor`: checks Python, compat tool, GE-Proton, runtime
  entry point (every library), app exe, DWriteCore, config validity, last
  status/error. Prints OK/WARN/FAIL; exit code 0/1.
- `wemod-deck reset-prefix <appid>`: **moves** `compatdata/<appid>` to
  `~/.local/share/wemod-deck/old-prefixes/<appid>-<ts>/` (same filesystem →
  rename; otherwise refuses and explains). Nothing is deleted in Phase 1. Phase 2 adds
  backup and restore, then real deletion.
- `wemod-deck setup [--force]`: download/update the app and DWriteCore.
- `wemod-deck status [<appid>]`: prints `status.json`.

### `install.sh`
Port of `reference/install-wemod-launcher.sh` with the same flags
(`--dir --zip --no-proton --no-wemod --no-tool --force-wemod --uninstall`)
and the same GE logic (redirect tag lookup, `-x86_64` asset first, folder
name read from the tarball, `curl -r 0-0` probe, `~/.cache` downloads,
`.sha512sum` check, SIGPIPE-safe `tar | head`). Changes:
- installs **this** repo (git clone of `Radverth/steam-deck-wemod` at `main`,
  or `--zip`); no venv, pip, FreeSimpleGUI, tkinter or winetricks;
- checks `python3 >= 3.9` (see decision 4);
- pre-downloads the app via `python3 -m wemod_deck setup`;
- generates the compat tool from `compat/`; drops the Flatpak paths;
- `--uninstall` removes the install dir and the tool, and keeps
  `~/.local/share/wemod-deck` (login, binaries) unless you type `YES` to a
  second question;
- prints a short Game Mode guide (no Launch Options needed).
- URLs can be overridden by environment variables so tests can point them at a local fake server.

### Removed
`src/` upstream modules and `wemod.bat` (replaced).
Flatpak, external launcher/`WINE`, `build_prefix`, winetricks, dotnet48,
GE-Proton 7 and prefix-copy paths, the troubleshooter, all FreeSimpleGUI
use, and git self-update.
README launch instructions are updated to the compat tool (full docs in Phase 9).

## Build order (each a commit)
1. `wemod_deck` skeleton: `paths`, `config`, `status`, CLI stub; unit tests.
2. `steam.py` (VDF/ACF parser, libraries, runtime lookup); tests on the fake Steam root, including SD card.
3. `argv.py` compat-tool parser + legacy parser; port the Phase 0 expectations, flip the xfail.
4. `app.py` (Scoop manifest → nupkg → unpack, WeMod/Wand, DWriteCore) against a local fake HTTP server + fake nupkg.
5. `prefix.py` (closest release, cache, non-destructive unpack); tests that existing user files survive.
6. `login.py` (symlink, central wins, displace instead of delete, migration from old path).
7. `launch.py` fail-open orchestration + `data/wemod-deck.bat`.
8. `compat/proton` wrapper + `install.sh`; shellcheck.
9. End-to-end scenario tests (below), then delete upstream `src/` and the old characterisation driver.
10. `doctor`, `reset-prefix`, `setup`, `status`; README quick start; CHANGELOG; ADRs.

## Tests (all on the VPS with the Phase 0 fakes)
**End-to-end:** `install.sh` runs into a fake HOME against a local HTTP
server (fake GE tarball + sha512sum, `releases/latest` redirect, Scoop
manifest, fake nupkg, fake prefix zip). Then the **generated** wrapper is
run as Steam would, and the fake stubs' JSON log is asserted for each
scenario:

| Scenario | Expected |
|---|---|
| housekeeping verb (`getcompatpath`, `run`) | entry-point → GE proton, no wemod-deck |
| first launch (no `pfx/drive_c`) | plain Proton, prefix created |
| normal launch | entry-point → proton `waitforexitandrun start …wemod-deck.bat game.exe` |
| opted-out AppID | plain Proton `waitforexitandrun game.exe` |
| launcher (`wemod-deck`) missing | plain Proton |
| runtime missing | GE proton called directly (no entry-point), WeMod still used |
| runtime on SD card | SD-card entry-point used |
| broken config / download failure / parse error | plain Proton + status.json error |

**Other checks:**
- **No Tk:** an AST scan of `wemod_deck/` finds no `tkinter`/`FreeSimpleGUI`
  imports. A launch subprocess also runs with both blocked in `sys.modules`.
- **No network** in a launch once set up (the socket is blocked in the test).
- **Saves:** a prefix with fake save files under `users/steamuser` gets a
  prebuilt prefix unpacked over it; every save file is byte-identical
  afterwards.
- **Linting:** `install.sh` and `compat/proton` pass shellcheck; ruff now
  covers `wemod_deck/`.

## Risks
- **Wand's login folder** is `Roaming/Wand` by its `productName`; Tom confirms the login is kept between games on the Deck.
- **Prefix download size:** the prebuilt prefix is ~0.9 GB on the first WeMod launch of each
  game. That's unchanged from today; Phase 6 addresses storage.
- **Exec'ing the final command** means no post-game step; that's intended (no
  troubleshooter). Early-close handling is in the `.bat` (decision 3).
- **Tom's existing setup:** existing `~/wemod-launcher` installs and Launch Options lines
  keep working through the `wemod` shim. Old prefixes have
  `.wemod_installer`, so they are reused without a new download.

## Tom's Deck checklist (from scope)
- Install with `install.sh` and set "WeMod + GE-Proton" as the default compat tool.
- Launch 3 games, one of them Deck Verified with a forced tool. No popups. WeMod appears.
- `wemod-deck doctor` is all OK.
- `install.sh --uninstall` works.
