# 0004: Prebuilt prefixes are unpacked without touching saves

Date: 2026-10-11. Status: accepted (Phase 1, until Phase 2 backups exist).

Upstream unzips a prebuilt prefix (~0.9 GB, with .NET) over the game's
prefix, overwriting anything with the same name, including files under
`drive_c/users/steamuser` where many games keep saves.

Rules in `wemod_deck/prefix.py`:
- Under `pfx/drive_c/users/`, existing files are never overwritten; only
  missing files are added.
- Zip entry names are normalised (`pfx/./a`, `pfx//a`) before any check.
- The registry hives (`pfx/system.reg`, `user.reg`, `userdef.reg`) must be
  replaced: the prebuilt ones carry .NET's registration and DLL overrides.
  They are first copied to `compatdata/wemod-deck-backup/<time>/`, and
  `user.reg` (HKCU, where e.g. Unity games keep PlayerPrefs and some saves)
  gets back every key the prebuilt hive doesn't have. Keys in both keep the
  prebuilt values.
- Nothing is written through a symlink to outside the prefix (the shared
  login link, `dosdevices/z:` → `/`), and absolute or `..` paths are skipped.
- Only the `dosdevices/c:` and `z:` links are created, and only when absent.
- Nothing is deleted. The `.wemod_installer` marker is written last, so an
  interrupted unpack is retried on the next launch.
- Free space is checked before downloading and before unpacking.
- The closest release is picked in upstream's priority order. Today a
  GE-Proton 11 prefix gets `PfxVer10.1`. Proton upgrades the prefix on the
  next run because the zip's `version` file is written, as upstream does.
- Only the most recently used zip is kept in `~/.cache/wemod-deck/prefixes/`.

`reset-prefix` moved `compatdata/<appid>` aside in Phase 1. Since Phase 2 it
deletes it after a verified backup (`--keep-old` still moves it aside); see
ADR 0006. Since Phase 2 the unpack also runs only after a verified save
backup.
