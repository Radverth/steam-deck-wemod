# Changelog

All notable changes to wemod-deck. Upstream history up to `upstream-1.543`
is DeckCheatz/wemod-launcher.

## [Unreleased]

### Phase 0: baseline and test harness
- Imported upstream wemod-launcher 1.543 unchanged; tagged `upstream-1.543`.
- Added Tom's field-tested installer as `reference/install-wemod-launcher.sh` (spec for install behaviour).
- Replaced upstream's format/auto-sync workflow with CI: ruff, shellcheck, pytest (Python 3.11 and 3.13).
- Added a fake Steam root (internal + SD card libraries, sniper runtime, GE-Proton11-7, plain and launcher games) and a fake WeMod nupkg for tests.
- Added characterisation tests pinning upstream's argument parsing, including a known `IndexError` bug for custom runners after `--`.
- Added `docs/architecture-current.md` (modules, import-time globals, popups, network, destructive operations) and ADR 0001.
