# Phase 2: save protection

Status: **approved 2026-10-11 (Tom: "Go, as planned")**. Branch `agent/phase-2-backups`
(stacked on Phase 1, PR #2).

## Goal
No code path changes or removes a game's prefix without a **verified**
backup of the player's saves first. Anything that goes missing is put back
afterwards, and the player can list and restore backups by hand.

## What exists after Phase 1
Only two operations change a prefix destructively:
1. **Prebuilt prefix unpack** (`prefix.unpack`, once per game, at launch).
   It never overwrites files under `drive_c/users/`, but it does replace
   other files, including `drive_c/ProgramData/` (some games save there)
   and the registry hives (backed up, and `user.reg` merged).
2. **`reset-prefix`**: moves the prefix aside (nothing deleted). Safe, but
   each reset leaves a 1–3 GB copy behind.

`login.link_logins` moves a prefix's own login aside; it never deletes it.

## Decisions for Tom (recommendation first)
1. **`reset-prefix` really deletes the old prefix, after a verified
   backup.** That frees the 1–3 GB the Phase 1 move-aside keeps.
   `--keep-old` keeps today's move-aside behaviour.
2. **After a reset, the next launch restores your saves before the game
   starts.** Normally a brand-new prefix's first launch runs without WeMod
   while Proton builds it. That would let the game start once without your
   saves and possibly write a fresh, empty save. Instead, when a restore is
   pending, wemod-deck asks Proton to build the prefix (`proton run` on a
   harmless Windows command), puts the saves back, and then launches
   normally with Wand. If building the prefix that way fails, the game
   starts plain and the saves are restored on the following launch; the
   status file says so. **Needs checking on the Deck.**
3. **What a backup contains:**
   - `drive_c/users/steamuser/` (saves, settings, Documents, AppData), minus
     `Temp` / `AppData/Local/Temp` and the Wand/WeMod login links;
   - `drive_c/ProgramData/` (some games save there);
   - `pfx/user.reg` (games' HKCU keys).

   Symlinks are stored as links, never followed. There's no size cap, only a
   free-space check, and the size is logged. If shader caches under
   `AppData/Local` turn out to be huge on real games, we add exclusions
   after the Deck test.

## Design

### Archive format (`wemod_deck/backup.py`)
`~/.local/share/wemod-deck/backups/<appid>/<YYYYmmdd-HHMMSS>-<reason>.tar.zst`
plus a `.json` manifest next to it: every file's path, size, mtime,
SHA-256 and link target, plus the reason (`unpack`, `reset`, `manual`,
`pre-restore`) and the wemod-deck version.

- Compression: stdlib `compression.zstd` (Python 3.14+); else the `zstd`
  command (SteamOS ships it for pacman); else `.tar.gz` (stdlib). The
  extension records which, and restore handles all three. This is ADR 0006.
- Written to `<name>.part` and renamed only after verification.
- **Verification:** the archive is read back in full and every member is
  checked against the manifest (size, SHA-256, link target). Any mismatch
  → the backup is deleted and the operation is **aborted**.
- **Space check:** before writing, the total size of the files plus a
  margin must fit on the backup filesystem. If it doesn't → abort.
- Paths inside the archive are relative to `compatdata/<appid>/`. On
  restore, absolute paths, `..` and anything resolving outside the prefix
  are refused (same rules as Phase 1's unpack).

### One gate for destructive operations
`backup.protected(compatdata, appid, reason)` is a context manager that
every destructive prefix operation must go through:
1. snapshot + verify (abort on failure);
2. run the operation;
3. afterwards, **restore every file from the snapshot that is now
   missing** (never overwriting anything that exists), and log what was put
   back.

A test scans `wemod_deck/` and fails if `rmtree`, `unlink` or `rename` is
used on prefix paths outside `backup.py` / `prefix.py`'s gated functions,
so new code can't skip the gate.

### Where it is used
- **Unpack at launch:** `prefix.ensure` runs the unpack inside
  `protected(..., "unpack")`. If the backup can't be made (no space,
  verification failed), the unpack is skipped and the game starts **plain**
  with a status error ("not enough space for a save backup"). That's
  fail-open, and saves stay untouched.
- **`reset-prefix <appid>`:**
  1. refuses if the game is running: any process whose environment has
     this `STEAM_COMPAT_DATA_PATH` (`/proc/*/environ`, own processes only);
  2. snapshot + verify (`reset`);
  3. deletes the prefix, or moves it aside with `--keep-old`;
  4. writes `pending-restore/<appid>` → the backup to restore.
- **Next launch with a pending restore** (decision 2): the wrapper routes the
  missing-prefix case to wemod-deck when `pending-restore/<appid>` exists.
  wemod-deck runs `<entry-point --verb=run --> proton run cmd.exe /c exit`
  so Proton builds the prefix, restores the backup **in full**, clears the
  marker, then continues the normal launch (prebuilt prefix, login, Wand).

### Restore rules
- **Restore after an operation:** only files that are now missing come back.
- **`backups restore`** (by hand): files that differ from the backup are
  overwritten, but first a `pre-restore` snapshot of the current state is
  taken, so a restore can itself be undone. Files that aren't in the backup
  are left alone. It refuses while the game is running.

### Retention
The newest `backups_keep` (default 5) archives per AppID are kept. The
backup a pending restore points to is never pruned. Pruning happens only
after a new backup has been verified. A config key is added:
`backups_keep = 5`.

### CLI
```
wemod-deck backups list [<appid>]            # time, reason, size, files
wemod-deck backups create <appid>            # manual snapshot
wemod-deck backups restore <appid> [<time>] [--dry-run]
wemod-deck reset-prefix <appid> [--keep-old]
```
`doctor` gains: backup folder size, pending restores, and whether zstd is
available.

## Files
New: `wemod_deck/backup.py`, `docs/decisions/0006-save-backups.md`, tests
`test_backup.py`, plus new e2e cases.
Changed: `prefix.py` (unpack and reset through the gate), `launch.py`
(pending restore), `compat/proton` (pending-restore routing), `cli.py`,
`config.py` (`backups_keep`), `doctor.py`, README, CHANGELOG.

## Build order (each a commit)
1. `backup.py`: snapshot with manifest, three compression backends, verify,
   space check, safe restore (missing-only and full), retention; unit tests.
2. `protected()` gate; route `prefix.unpack` through it; fail-open on
   backup failure; the guard test against ungated deletes.
3. `reset-prefix` rewrite (running-game check, delete or `--keep-old`,
   pending-restore marker).
4. Pending-restore launch path (wrapper + `launch.py`, fake Proton's `run`
   verb builds the prefix).
5. `backups list|create|restore` CLI, `doctor` additions, config key.
6. Docs: ADR 0006, README section, CHANGELOG.

## Tests (VPS, fakes)
- **Acceptance (scope):** fake save files (binary, nested, unicode names,
  a symlink, `user.reg` keys) → `reset-prefix` → next launch through the
  real wrapper → every file byte-identical, links intact, game launched
  with Wand.
- Unpack over a prefix with saves → backup exists and verifies; anything
  deleted during the operation (simulated) comes back.
- Not enough space (`shutil.disk_usage` patched) → reset refuses and leaves
  the prefix untouched; at launch the unpack is skipped and the game starts plain.
- Corrupt archive (truncated after writing) → verification fails, the op is
  aborted, and no `.part` file is left.
- Retention: 7 backups → 5 kept, newest first; the pending-restore target
  survives pruning.
- Each backend round-trips (stdlib zstd when available, `zstd` CLI faked on
  `PATH`, gzip). Restores across backends work.
- Restore refuses `..`/absolute/outside-prefix members.
- `backups restore` takes a `pre-restore` snapshot first and doesn't touch
  files outside the backup.
- Running-game check: a fake process with the prefix in its environment
  blocks reset and restore.
- Guard test: no ungated deletes on prefix paths.
- Python 3.9 runs the full suite (CLI zstd or gzip path).

## Risks
- **Building the prefix with `proton run cmd.exe /c exit`** (decision 2) is
  new and untested on a Deck. The fallback is the old behaviour plus a
  restore on the following launch.
- **Backup size and time:** games that keep big caches in
  `AppData/Local` make the one-time unpack backup slow and large. It's
  measured on the Deck before we decide on exclusions.
- **Saves outside the prefix** (game install folder, Steam Cloud) aren't
  covered. Steam Cloud handles its own; the README says so.
- **Running-game detection** via `/proc` only sees our own user's processes,
  which is what Steam runs as on the Deck.

## Tom's Deck checklist (from scope, plus decision 2)
- [ ] Pick a game with local (non-cloud) saves. Run `wemod-deck backups create <appid>`, then `backups list`.
- [ ] `wemod-deck reset-prefix <appid>`; launch the game from Game Mode. The save is there on that very launch, and Wand starts.
- [ ] `wemod-deck doctor` shows the backup size and no pending restores.
- [ ] Optional: note how big the backup of your largest game is (`backups list`).

## As built (2026-10-11)
Implemented as planned. Details settled while building:
- The guard is an AST scan with a reviewed allowlist (`tests/test_guard.py`)
  rather than a path-based check: every delete/move/replace call is listed
  with why it is safe.
- `reset-prefix` refuses when a game has prefixes in several libraries.
- A backup being restored is protected from the `pre-restore` snapshot's
  pruning.
- Python 3.9's `tarfile` needs string paths in stream mode (found by the
  3.9 test run).
- ADR 0006 records the design.
