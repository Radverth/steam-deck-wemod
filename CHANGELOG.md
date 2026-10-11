# Changelog

All notable changes to wemod-deck. Upstream history up to `upstream-1.543`
is DeckCheatz/wemod-launcher.

## [Unreleased]

### Phase 2: save protection
- Save backups (`drive_c/users/steamuser`, `ProgramData`, `user.reg`) as verified `.tar.zst` (or `.tar.gz`) with a SHA-256 manifest; the newest 5 per game are kept (`backups_keep`).
- Every destructive prefix operation goes through one gate: verified backup first (no backup, no change), and anything missing afterwards is put back. A test flags unreviewed delete/move calls.
- The one-time prebuilt-prefix install now runs only after a verified backup; if none can be made, the game starts without Wand.
- `reset-prefix` backs up, then deletes the prefix (`--keep-old` moves it aside). It refuses while the game is running.
- After a reset, the next launch rebuilds the prefix and restores the saves **before** the game starts.
- New `backups list|create|restore` commands; restore is undoable and has `--dry-run`. `doctor` shows backups and pending restores.

### Phase 1: compat tool first, headless launch
- New `wemod_deck` launcher (Python 3.9+, stdlib only): no popups, no venv, pip or Tk at runtime.
- **Wand (formerly WeMod) is the default app**; `app = "wemod"` keeps the 11.x client. Downloads come from WeMod's CDN via the Scoop manifest and are SHA-256 verified.
- "WeMod + GE-Proton" compat tool ported from the reference installer: runs on the host, finds the Steam Linux Runtime on every library (SD card included), only game launches go through wemod-deck.
- Fail-open: if anything goes wrong before the game starts (even a broken Python), it starts with plain Proton and the error goes to `status.json` and `logs/launch.log`.
- Strict compat-tool argument parsing; Launch Options mode (`~/wemod-deck/wemod %command%`) uses a simpler parser and fixes upstream's custom-runner crash.
- Prebuilt prefixes: closest version picked automatically, unpacked without overwriting files under `drive_c/users` (saves); registry hives are backed up first and `user.reg` keeps the game's own keys; release list cached 24 h.
- Shared login for `Roaming/Wand` and `Roaming/WeMod`; a prefix's own login is moved aside, never deleted.
- Per-game opt-out in `~/.config/wemod-deck/config.toml`.
- New commands: `doctor`, `status`, `setup`, `reset-prefix` (moves the prefix aside, deletes nothing).
- `install.sh` (same flags as the reference) installs to `~/wemod-deck`, copies data from an upstream `~/wemod-launcher` install once, and keeps login/settings on uninstall unless confirmed twice.
- Removed: upstream `src/`, Tk popups and troubleshooter, git self-update, Flatpak, external runners, winetricks/dotnet48 prefix building, GE-Proton 7 and prefix-copy paths.
- CI: tests on Python 3.9, 3.11 and 3.13; shellcheck covers `install.sh`, `wemod` and `compat/proton`; end-to-end tests run the real installer and compat tool offline.

### Phase 0: baseline and test harness
- Imported upstream wemod-launcher 1.543 unchanged; tagged `upstream-1.543`.
- Added Tom's field-tested installer as `reference/install-wemod-launcher.sh` (spec for install behaviour).
- Replaced upstream's format/auto-sync workflow with CI: ruff, shellcheck, pytest (Python 3.11 and 3.13).
- Added a fake Steam root (internal + SD card libraries, sniper runtime, GE-Proton11-7, plain and launcher games) and a fake WeMod nupkg for tests.
- Added characterisation tests pinning upstream's argument parsing, including a known `IndexError` bug for custom runners after `--`.
- Added `docs/architecture-current.md` (modules, import-time globals, popups, network, destructive operations) and ADR 0001.
