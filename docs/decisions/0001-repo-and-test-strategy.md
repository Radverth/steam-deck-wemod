# 0001: Repository and test strategy

Date: 2026-10-11. Status: accepted (Tom, Phase 0 go-ahead).

## Repository
The scope named a GitHub fork `Radverth/wemod-deck`. Tom chose to use the
existing empty `Radverth/steam-deck-wemod` instead. Upstream history was
imported unchanged as `main` and tagged `upstream-1.543` (commit `3dd1e02`),
so authorship and AGPL-3.0 notices are kept. Upstream stays available as the
`upstream` remote; nothing is pushed there.

Upstream's `black.yml` was removed: it reformats code, bumps the version,
amends and force-pushes, and opens main↔dev sync PRs. It is replaced by
`ci.yml` (ruff, shellcheck, pytest).

## Tests without a Deck
- `tests/fakes/steam_root.py` builds a fake Steam tree in a temp `HOME`
  (internal + SD-card library, sniper runtime, GE-Proton11-7-x86_64, two
  games). Stubs are bash scripts that log argv/env as JSON lines.
- Upstream modules do work at import time and write next to themselves, so
  characterisation tests run each scenario in a **subprocess** against a temp
  copy of `src/`, with popups, network and `Popen` stubbed
  (`tests/upstream_driver.py`).
- Known upstream bugs are pinned as they are, plus a `strict` xfail for the
  desired behaviour, so a fix flips the xfail and forces the test update.

## Lint scope
ruff checks new code only; `src/` (upstream) and `reference/` are excluded
until rewritten, so lint churn doesn't hide behaviour changes.
CI tests on Python 3.11 (SteamOS 3.x) and 3.13.
