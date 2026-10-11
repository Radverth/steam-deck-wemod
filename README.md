# wemod-deck

Run **Wand** (formerly WeMod) with your Steam games on the **Steam Deck**,
straight from Game Mode, with no launcher setup dialogs.

A Steam Deck-first fork of
[DeckCheatz/wemod-launcher](https://github.com/DeckCheatz/wemod-launcher)
(1.x line, AGPL-3.0). See [Credits](#credits).

> **Work in progress.** Phases 1–2 are implemented: compatibility tool,
> headless launch, and verified save backups. Automated tests use simulated
> Steam installs; real Steam Deck/Wine behavior has not yet been verified.
> See the [plans](docs/plans/) and [Deck test checklist](#first-steam-deck-test).

## Disclaimer

Not affiliated with, funded by, or paid by WeMod/Wand. This project only
makes the official client run on SteamOS. It does not change, bypass or
unlock anything in it. **Single-player games only**: don't use it with
online or multiplayer games or with anti-cheat.

## Quick start (Steam Deck)

For native Steam on SteamOS, with Python 3.9 or newer. The launcher uses
Python’s standard library; no pip, virtual environment, or Tk is needed.

1. Switch to **Desktop Mode** and open **Konsole**.
2. Install:
   ```sh
   curl -fLO https://raw.githubusercontent.com/Radverth/steam-deck-wemod/main/install.sh
   bash install.sh
   ```
   This installs wemod-deck to `~/wemod-deck`, downloads Wand from
   WeMod's own servers (checksum-verified), installs the latest GE-Proton,
   and adds a **"WeMod + GE-Proton"** compatibility tool. No sudo.
3. Restart Steam (or reboot) and go back to Game Mode.
4. For a game: **Properties ▸ Compatibility ▸ Force…** ▸ **WeMod + GE-Proton**.
5. Launch the game. The **first** launch of a brand-new game runs without
   Wand while Proton builds its prefix. From the next launch on, Wand
   starts with the game. The first time, a prebuilt prefix (~0.9 GB) is
   downloaded, so that launch takes a while.
6. Log in to Wand once; all games share the login.

If anything goes wrong, the game **still starts**, just without Wand. To
see why, run `~/wemod-deck/wemod-deck doctor` in Desktop Mode.

## How it works

```
Steam ─ "WeMod + GE-Proton" tool (runs on the host)
         ├─ install scripts, path lookups ─► Steam Linux Runtime ─► GE-Proton
         ├─ first launch / game opted out ─► Steam Linux Runtime ─► GE-Proton
         └─ game launch ─► wemod-deck (prefix + login prep, no popups)
                             └─► Steam Linux Runtime ─► GE-Proton ─► Wand + game
```

- Prefixes get a prebuilt Wine prefix with .NET from DeckCheatz's
  BuiltPrefixes. Existing files under `drive_c/users` (your saves) are
  never overwritten.
- `AppData/Roaming/Wand` (and `WeMod`) in every prefix links to one shared
  login in `~/.local/share/wemod-deck/login/`.
- Launcher games (Ubisoft, 2K, …): when the game hands off to its launcher,
  Wand stays open. Close it yourself or use **Steam ▸ Exit Game**.

## Commands

Run from Konsole as `~/wemod-deck/wemod-deck <command>`:

| Command | What it does |
|---|---|
| `doctor` | Checks the install and prints what's wrong |
| `status [AppID]` | Result of the last launch (or of one game) |
| `setup [--force]` | Download or update Wand |
| `reset-prefix <AppID> [--keep-old]` | Backs up the game's saves, then deletes its prefix (or moves it aside with `--keep-old`). The next launch rebuilds it and puts the saves back before the game starts. |
| `backups list [AppID]` | Save backups, newest first |
| `backups create <AppID>` | Back up a game's saves now |
| `backups restore <AppID> [name] [--dry-run]` | Put a backup back. Your current state is backed up first, so you can undo it. |

## Your saves

Before wemod-deck changes a game's prefix (the one-time prebuilt-prefix
install, or `reset-prefix`), it backs up the saves to
`~/.local/share/wemod-deck/backups/<AppID>/` and checks the backup. No
backup (for example, not enough space) means no change: the game just starts
without Wand. Backed up: `drive_c/users/steamuser`, `drive_c/ProgramData`
and the game's registry keys (`user.reg`). The newest 5 per game are kept
by default; backups needed for a pending restore are protected from pruning. Archives use `.tar.zst` when zstd is
available, otherwise `.tar.gz`, with a SHA-256 manifest.

This is a save backup, not a complete prefix image. Temporary folders and
shared Wand/WeMod login links are excluded. Symlinks are recorded without
following them, so saves outside the prefix reached through a link are not
copied. Saves in a game's own install folder or in Steam Cloud aren't part
of this.

Restores verify the archive again before writing. Conflicting paths are reported
as incomplete; a pending restore stays protected, and another reset is refused
until it finishes. If Proton cannot rebuild the prefix before launch, the game
starts plain and restoration is retried on the next launch.

### Manual backup and recovery

Exit the game before backing up, resetting, or restoring. Reset and restore
refuse when they detect the game is still running. Replace `1234560` with
the game's AppID:

```sh
~/wemod-deck/wemod-deck backups create 1234560
~/wemod-deck/wemod-deck backups list 1234560
~/wemod-deck/wemod-deck backups restore 1234560 BACKUP_NAME --dry-run
~/wemod-deck/wemod-deck backups restore 1234560 BACKUP_NAME
```

Use a name from `backups list` (or an unambiguous prefix of it). Omitting
the name selects the newest backup. A dry run previews changes without
writing. A real restore replaces matching save files and merges registry
values from the backup; it does not delete extra files. It first creates a
`pre-restore` backup, which you can select by name to undo overwritten data.

### First Steam Deck test

Use a single-player game with local saves, and keep a separate copy of
those saves while real-device testing is outstanding.

1. Launch the game, log in to Wand, and confirm both work. A brand-new
   prefix needs a second launch before Wand starts.
2. Exit the game, create a backup with the command above, and check it
   appears in `backups list`.
3. Run `~/wemod-deck/wemod-deck reset-prefix 1234560 --keep-old`, then
   launch again. Confirm the saves return and Wand starts. `--keep-old`
   preserves the old prefix under `~/.local/share/wemod-deck/old-prefixes/`.
4. Run `~/wemod-deck/wemod-deck doctor` and
   `~/wemod-deck/wemod-deck status 1234560`. Check for warnings and pending
   restores, even if doctor ends with “All good.”

## Settings

`~/.config/wemod-deck/config.toml` (optional):

```toml
app = "wand"        # or "wemod" for the old WeMod 11.x client
enabled = true      # use Wand for every game with the tool
backups_keep = 5    # save backups kept per game (1–100)
log_level = "info"  # debug, info, warning, or error

[apps."1234560"]    # a game's AppID (shown in its store URL)
enabled = false     # this game runs plain GE-Proton
```

Log: `~/.local/share/wemod-deck/logs/launch.log`.

## Launch Options (alternative)

Instead of the compatibility tool, with a Proton version selected for the
game, set its Launch Options to:

```
~/wemod-deck/wemod %command%
```

## Update / uninstall

- Update: run `bash install.sh` again. `--force-wemod` re-downloads Wand.
- Uninstall: `bash install.sh --uninstall`. Your login and settings are
  kept unless you confirm a second time. **That second confirmation also
  deletes save backups, pending-restore records, and kept old prefixes**
  in the data directory. Game prefixes in Steam’s libraries are not touched.
  GE-Proton stays installed. Games set to the tool need another compatibility tool
  afterwards.

`bash install.sh --help` lists all options.

## Development

No Deck needed: tests run against a fake Steam install and a local fake
download server.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
shellcheck install.sh wemod compat/proton tests/fakes/stubs/*
```

Install ShellCheck separately for the shell checks. GitHub Actions runs
lint and the tests on Python 3.9, 3.11, and 3.13.

Design notes: [`docs/`](docs/) (plans, decisions, upstream architecture).
Changes: [`CHANGELOG.md`](CHANGELOG.md).

## Credits

Built on [wemod-launcher](https://github.com/DeckCheatz/wemod-launcher) by
the DeckCheatz contributors. Please support them:

- Marvin1099 (maintainer):
  [Buymeacoffee](https://www.buymeacoffee.com/marvin1099),
  [Patreon](https://www.patreon.com/marvin1099),
  [Tipeeestream](https://www.tipeeestream.com/marvin1099/tip)
- shymega (rework lead): [GitHub Sponsors](https://github.com/sponsors/shymega)
- DaniAsh551 (original creator):
  [Buymeacoffee](https://www.buymeacoffee.com/TIjUvF1),
  [Patreon](https://www.patreon.com/daniash551),
  [PayPal](https://www.paypal.com/donate/?hosted_button_id=D7Y43PT9HUEUY)
- JohnHamwi (contributor): [GitHub](https://github.com/JohnHamwi)

Prebuilt prefixes: [DeckCheatz/BuiltPrefixes-dev](https://github.com/DeckCheatz/BuiltPrefixes-dev).
GE-Proton: [GloriousEggroll/proton-ge-custom](https://github.com/GloriousEggroll/proton-ge-custom).

## Licence

AGPL-3.0, like upstream. See [LICENSE](LICENSE).
