# Current architecture (upstream 1.543, tag `upstream-1.543`)

Map of the unmodified upstream launcher, so later phases know what they are
replacing. Line numbers refer to `src/` at the tag.

## Entry and modules

`wemod` (repo root) is a symlink to `src/wemod.py`. Steam runs it as
`~/wemod-launcher/wemod %command%` or via the compat-tool wrapper.

| Module | Role |
|---|---|
| `corenodep.py` | No-dependency helpers: `wemod.conf` read/write (`load_conf_setting`/`save_conf_setting`), `parse_version`, `winpath`, `--` list split/join. |
| `coreutils.py` | Logging, `http_get` (urllib), Tk popups (`show_message`, `popup_options`, `get_user_input`, `exit_with_message`), pip bootstrap, early-close monitor (`monitor_file`/`bat_respond`), `cache`, `script_manager` (version stamp). |
| `mainutils.py` | GitHub releases lookup, closest prefix release, Tk progress windows for download/copy/unzip/deref, dotnet48 download, Flatpak runner, `create_symlink`. |
| `setup.py` | venv manager, git self-update, Flatpak detection, WeMod download (Scoop manifest URL) and unpack, DWriteCore.dll from NuGet, first-run setup. |
| `consts.py` | **Import-time globals** (see below). |
| `constutils.py` | `ensure_wine` (prefix version file), `scanfolderforversions` (find another WeMod prefix), winetricks/wine runners, `troubleshooter`. |
| `wemod.py` | Main: two `__main__` blocks around the `consts` import; `syncwemod`, `init`, `download_prefix`, `build_prefix`, `run`. |
| `wemod.bat` | Runs in the prefix: starts WeMod.exe, finds its PID with `tasklist` (4 tries, 5 s apart), `start /wait` the game, `taskkill` WeMod; signals "closed too early" through `.cache/` temp files. |

## Launch flow (`wemod.py`)

1. First `__main__` block (`wemod.py:67`): `script_manager()` writes version to
   `wemod.conf`; `venv_manager()` creates the venv and pip-installs FreeSimpleGUI;
   `self_update()` runs `git fetch` / `git reset --hard origin` / `git pull`
   (`setup.py:259`); Flatpak check; may **re-exec itself** inside the venv.
2. `from consts import ...` (`wemod.py:117`) runs the import-time code below.
3. `run()` (`wemod.py:896`): guesses the Proton argument (see "Argument
   parsing"), calls `init()`, builds `FINAL = reaper_cmd + [proton] + verb +
   ["start", wemod.bat] + GAME_FRONT + [game] + launch_options`, starts the
   early-close monitor thread, runs `FINAL` with `Popen`, then
   `troubleshooter()`.
4. `init()` (`wemod.py:460`): `ensure_wine()` (prefix `version` file), and if
   the prefix has no `pfx/.wemod_installer`: offer to copy another game's
   WeMod prefix, else ask download vs build, then `syncwemod()`;
   `setup_main()` if WeMod.exe is missing; `ensure_dwritecore()` every launch.

## Import-time globals (`consts.py`)

Evaluated on `import consts`, before `run()`:
- `BAT_COMMAND = getbatcmd()` (`consts.py:65`): **downloads `wemod.bat` from
  GitHub** if missing, else popup + exit.
- `BASE_STEAM_COMPAT = get_compat()` (`consts.py:122`): from
  `STEAM_COMPAT_DATA_PATH`, or `WINEPREFIX`/`WINE_PREFIX_PATH` + `WINE` for
  custom runners (also rewrites `STEAM_COMPAT_TOOL_PATHS`). Popup + exit if
  neither is set. `os.makedirs` on the result.
- `STEAM_COMPAT_FOLDER`, `SCAN_FOLDER`, `WINETRICKS`, `WINEPREFIX`,
  `INIT_FILE` derived from it.
- `corenodep.CONFIG` reads `src/wemod.conf` on import. `log()` writes
  `src/wemod.log` and may write `WeModLog` into the config.

Consequence for tests: every scenario needs a fresh interpreter and a
throwaway copy of `src/` (see `tests/upstream_driver.py`).

## Argument parsing (`run()`, `wemod.py:896`)

1. For each entry of `STEAM_COMPAT_TOOL_PATHS`, pick the **highest** argv
   index whose `dirname` equals that entry (loop runs twice, identically).
2. If none found (`fnr <= 0`) and argv has no `--`: first argv whose basename
   contains `wine`, `umu-run` or `proton`.
3. If found: `REAPER_CMD = argv[:fnr]`, `PROTON = argv[fnr]`. If
   `argv[fnr+1]` contains a `.`, treat it as a custom runner: no verb, game is
   `argv[fnr+1]`. Otherwise verb is forced to `waitforexitandrun` and the game
   is `argv[fnr+2]`.
4. Else split on `--`: last chunk is `[proton, verb, game, ...]`.
   **Bug:** the custom-runner check reads `PROTON[1]` (2nd *character* of the
   path), so it never fires; a runner after `--` raises `IndexError`
   (`tests/test_upstream_args.py::test_known_bug_...`).
5. Game path is made relative to `cwd` and converted to Windows form, unless
   it looks like a URL or `NO_EXE` / `NoEXE` says otherwise.

Pinned by `tests/test_upstream_args.py` for: Launch Options, compat-tool
argv, SD-card library, custom wine runner, tool-path mismatch fallback.

## Popups (all Tk via FreeSimpleGUI)

Launch-time (can appear in Game Mode):

| Where | When | What |
|---|---|---|
| `consts.py:59` | `wemod.bat` missing and download fails | exit |
| `consts.py:104,114` | no compat data path / no `WINE` | exit |
| `setup.py:49` `welcome` | WeMod.exe missing (first run) | OK to start setup (fetches logo over network) |
| `setup.py:79` | WeMod download | progress window |
| `setup.py:496` | setup done | "Setup completed" (5 s) |
| `setup.py:104,128,197,226,235,251,505` | venv/Tk/Scoop/unpack failures | exit |
| `constutils.py:108,113` | prefix has no `version` file | text input for wine version |
| `constutils.py:124` | prefix missing | exit "run without wemod-launcher once" |
| `constutils.py:270` | a GE-Proton 7 WeMod prefix found | ask user to zip and upload it |
| `wemod.py:378` | WeMod login in both central dir and prefix | which account (No = **overwrite central login**) |
| `wemod.py:521,533,545` | no WeMod in prefix, another prefix has it | copy that prefix? |
| `wemod.py:618` | still no WeMod | download vs build |
| `wemod.py:706,714` | prebuilt prefix version not exact | download anyway? |
| `wemod.py:739` | prefix download | progress window |
| `mainutils.py:478,563,343` | copy / unzip / deref prefix | progress windows |
| `wemod.py:802` | build path | dotnet48 method |
| `constutils.py:338,348` | winetricks / wine runs | progress |
| `wemod.py:1018,1033` | game exe missing / Proton not found | exit |

Exit-time:

| Where | When | What |
|---|---|---|
| `coreutils.py:398,409` | game closed before `tout` (60/90 s) | keep WeMod open? / "OK to close WeMod" |
| `constutils.py:366` | every exit unless disabled | **troubleshooter** (120 s): enable/disable, delete prefix, delete WeMod.exe |
| `wemod.py:1223` | any exception | "Open the log?" |
| `coreutils.py:210` | `exit_with_message(ask_for_log=True)` | "Open the log?" |

## Network on the launch path

`git fetch`/`reset --hard`/`pull` (self-update, every launch, `setup.py:259`),
User-Agent list from GitHub (`coreutils.py:131`), `wemod.bat` download
(`consts.py:52`), Scoop manifest + WeMod installer (`setup.py:125`), WeMod
logo (`setup.py:52`), DWriteCore NuGet (`setup.py:429`), winetricks
(`setup.py:468`), prefix releases (`mainutils.py:43`) and zips, pip
bootstrap (`coreutils.py:321`). **None are checksum-verified.**

## Destructive operations

| Where | What | Save risk |
|---|---|---|
| `constutils.py:405` | troubleshooter "Delete game prefix": `rmtree(BASE_STEAM_COMPAT)` | **Deletes all non-cloud saves** |
| `wemod.py` `init` copy-prefix path | copies another prefix over this one | overwrites `drive_c/users/steamuser` |
| `wemod.py:747` | unzips prebuilt prefix over `BASE_STEAM_COMPAT` | overwrites user files with the zip's |
| `wemod.py:392` | account conflict "No": `rmtree` central WeMod data | loses shared login |
| `wemod.py:417,435` | replaces prefix `AppData/Roaming/WeMod` with symlink | prefix login data |
| `setup.py:325` | `git reset --hard origin` | local launcher edits |
| `setup.py:489` | `rmtree(wemod_bin)` before re-download | WeMod binaries |

## Other observed bugs (not yet tested)

- `mainutils.create_symlink` (`mainutils.py:684`) calls
  `src_path.symlink_to(dst_path)`, which makes *src* the link (backwards), and
  `dst_path()` is called as a function on one branch.
- `constutils.py:264` GE-7 branch: `os.makedirs(..., exists_ok=True)` (typo,
  raises `TypeError`).
- `setup.py:464` uses `shutil.rmtree` on the winetricks *file*.
