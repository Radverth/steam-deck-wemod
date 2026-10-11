# 0004: Prebuilt prefixes are unpacked without touching saves

Date: 2026-10-11. Status: accepted (Phase 1, until Phase 2 backups exist).

Upstream unzips a prebuilt prefix (~0.9 GB, with .NET) over the game's
prefix, overwriting anything with the same name, including files under
`drive_c/users/steamuser` where many games keep saves.

Rules in `wemod_deck/prefix.py`:
- Under `pfx/drive_c/users/`, existing files are never overwritten; only
  missing files are added.
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

`reset-prefix` moves `compatdata/<appid>` to
`<library>/steamapps/compatdata-wemod-deck-old/<appid>-<time>` (same
filesystem, so it's a rename) instead of deleting it.
