# 0006: Save backups gate every destructive prefix operation

Date: 2026-10-11. Status: accepted (Tom: "Go, as planned", Phase 2).

## Decision
- **Contents:** `drive_c/users/steamuser` (minus `Temp`,
  `AppData/Local/Temp` and our Wand/WeMod login links), `drive_c/ProgramData`
  and `pfx/user.reg`. Symlinks are stored as links and never followed.
  No size cap, only a free-space check.
- **Format:** `backups/<appid>/<time>-<reason>.tar.zst` plus a JSON
  manifest (path, type, size, mtime, SHA-256 or link target). Compression is
  stdlib `compression.zstd` on Python 3.14+, else the `zstd` command
  (SteamOS ships it for pacman), else `.tar.gz`. Restore reads all three.
- **Verified or nothing:** the archive is written as `.part`, read back in
  full and compared with the manifest, and only then renamed. Any failure,
  or too little space, raises `BackupError`. The caller's destructive
  operation does not run.
- **One gate:** `backup.protected()` (backup → operation → put back anything
  now missing, even if the operation failed). The prebuilt-prefix unpack
  runs inside it. `tests/test_guard.py` lists every delete/move/replace call
  in `wemod_deck/` with the reason it is safe; new ones fail until reviewed.
- **Fail-open at launch:** if the backup can't be made, the unpack is
  skipped and the game starts plain with a status error.
- **reset-prefix:** refuses while the game runs (any process with that
  `STEAM_COMPAT_DATA_PATH`, via `/proc`). Then a verified backup, then a
  pending-restore marker (written *before* deleting), then the delete
  (`--keep-old` moves it aside instead).
- **After a reset:** the wrapper routes the missing prefix to wemod-deck
  when a restore is pending. wemod-deck has Proton build the prefix with
  `--verb=run … proton run cmd.exe /c exit`, restores the backup in full
  (`user.reg` merged, backup values win), clears the marker and launches
  normally. If the prefix can't be built that way, the game starts plain
  and the restore is retried on the next launch.
- **Manual restore** takes a `pre-restore` snapshot first, so it is undoable,
  and refuses while the game runs. Restores never delete and never write
  outside the backed-up areas.
- **Retention:** newest `backups_keep` (default 5) per game, pruned only
  after a newer verified backup. The pending-restore target and a backup
  being restored are never pruned.

## Consequences
- The first WeMod launch of each game takes one extra backup (size shown
  by `backups list`).
- `proton run cmd.exe /c exit` as a prefix builder is new: Tom checks it on
  the Deck.
- Saves outside the prefix (game folder) aren't covered; Steam Cloud covers
  its own.
