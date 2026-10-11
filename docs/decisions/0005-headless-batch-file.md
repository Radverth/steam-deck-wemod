# 0005: Headless batch file until Phase 4

Date: 2026-10-11. Status: accepted (Phase 1).

Upstream `wemod.bat` blocks a headless launch in two places: `pause` when
WeMod's PID isn't found, and a loop that waits for a Linux popup to delete a
temp file after an early game exit.

`wemod_deck/data/wemod-deck.bat` keeps the field-tested parts (`start` the
app, look for it with `tasklist` up to 4 × 5 s, `start /wait` the game,
`taskkill` twice) and removes the blocking. Changes:
- the app exe comes from `%WEMOD_DECK_EXE%` instead of being worked out
  from the bat's own location;
- a game that exits within `WEMOD_DECK_EARLY_SECONDS` (default 60) is
  treated as a launcher hand-off and the app is left open (Tom's decision 3);
- the app is closed by image name (`/IM`), which also works when the PID
  wasn't found;
- it is installed with CRLF line endings, the native format for `cmd`.

Game and bat paths keep upstream's exact form (relative game path,
`Z:\\` with doubled backslashes) because that is what has been tested.

Not testable on the VPS (no Wine). Phase 4 replaces it with a real helper.
