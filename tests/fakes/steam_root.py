"""Build a fake Steam install inside a temporary HOME.

Layout mirrors native Steam on SteamOS:

    $HOME/.local/share/Steam/                 internal library + Steam root
        ubuntu12_32/{reaper,steam-launch-wrapper}
        compatibilitytools.d/<GE>/{proton,toolmanifest.vdf,...}
        steamapps/libraryfolders.vdf          lists both libraries
    $HOME/.steam/{root,steam} -> ~/.local/share/Steam
    <tmp>/run/media/mmcblk0p1/                "SD card" library

The Steam Linux Runtime (sniper, appid 1628350) and the games can be put on
either library. Every stub logs one JSON line per call to ``log_path``.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

STUBS = Path(__file__).parent / "stubs"

RUNTIME_APPID = "1628350"
RUNTIME_NAME = "Steam Linux Runtime 3.0 (sniper)"
RUNTIME_INSTALLDIR = "SteamLinuxRuntime_sniper"
DEFAULT_GE = "GE-Proton11-7-x86_64"

PLAIN_GAME_APPID = "1234560"
LAUNCHER_GAME_APPID = "1234570"

GE_TOOLMANIFEST = """\
"manifest"
{
  "version" "2"
  "commandline" "/proton %verb%"
  "require_tool_appid" "1628350"
  "use_sessions" "1"
  "compatmanager_layer_name" "proton"
}
"""

GE_COMPATIBILITYTOOL = """\
"compatibilitytools"
{
  "compat_tools"
  {
    "{name}"
    {
      "install_path" "."
      "display_name" "{name}"
      "from_oslist" "windows"
      "to_oslist" "linux"
    }
  }
}
"""


@dataclass
class FakeGame:
    appid: str
    name: str
    library: Path
    install_dir: Path
    exe: Path

    @property
    def compatdata(self) -> Path:
        return self.library / "steamapps" / "compatdata" / self.appid


@dataclass
class FakeSteam:
    home: Path
    steam_root: Path
    sd_card: Path
    log_path: Path
    runtime_dir: Path
    entry_point: Path
    ge_dir: Path
    games: dict[str, FakeGame] = field(default_factory=dict)

    @property
    def ge_proton(self) -> Path:
        return self.ge_dir / "proton"

    @property
    def reaper(self) -> Path:
        return self.steam_root / "ubuntu12_32" / "reaper"

    @property
    def launch_wrapper(self) -> Path:
        return self.steam_root / "ubuntu12_32" / "steam-launch-wrapper"

    def game(self, appid: str = PLAIN_GAME_APPID) -> FakeGame:
        return self.games[appid]

    def env(self, game: FakeGame) -> dict[str, str]:
        """Environment Steam sets when it starts a game with a compat tool."""
        return {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "FAKE_STEAM_LOG": str(self.log_path),
            "SteamAppId": game.appid,
            "STEAM_COMPAT_APP_ID": game.appid,
            "STEAM_COMPAT_DATA_PATH": str(game.compatdata),
            "STEAM_COMPAT_CLIENT_INSTALL_PATH": str(self.steam_root),
            "STEAM_COMPAT_TOOL_PATHS": f"{self.ge_dir}:{self.runtime_dir}",
        }

    def proton_argv(self, game: FakeGame, verb: str = "waitforexitandrun") -> list[str]:
        """``<entry-point> --verb=V -- <proton> V <exe>``: what the compat tool
        wrapper (and Steam) runs inside the runtime container."""
        return [
            str(self.entry_point),
            f"--verb={verb}",
            "--",
            str(self.ge_proton),
            verb,
            str(game.exe),
        ]

    def launch_options_argv(
        self, game: FakeGame, verb: str = "waitforexitandrun"
    ) -> list[str]:
        """Full ``%command%`` as Steam expands it in a game's Launch Options."""
        return [
            str(self.reaper),
            "SteamLaunch",
            f"AppId={game.appid}",
            "--",
            str(self.launch_wrapper),
            "--",
            *self.proton_argv(game, verb),
        ]

    def read_log(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]


def _vdf_libraryfolders(libraries: list[tuple[Path, list[str]]]) -> str:
    out = ['"libraryfolders"', "{"]
    for i, (path, apps) in enumerate(libraries):
        out += [
            f'\t"{i}"',
            "\t{",
            f'\t\t"path"\t\t"{path}"',
            '\t\t"label"\t\t""',
            f'\t\t"contentid"\t\t"{1000 + i}"',
            '\t\t"totalsize"\t\t"0"',
            '\t\t"apps"',
            "\t\t{",
            *[f'\t\t\t"{a}"\t\t"0"' for a in apps],
            "\t\t}",
            "\t}",
        ]
    out.append("}")
    return "\n".join(out) + "\n"


def _acf(appid: str, name: str, installdir: str) -> str:
    return (
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n'
        '\t"universe"\t\t"1"\n'
        f'\t"name"\t\t"{name}"\n'
        '\t"StateFlags"\t\t"4"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        "}\n"
    )


def _install_stub(src: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(STUBS / src, dest)
    dest.chmod(0o755)
    return dest


def build_fake_steam(
    tmp: Path,
    *,
    runtime_on: str = "internal",
    games_on: str = "internal",
    ge_name: str = DEFAULT_GE,
) -> FakeSteam:
    """Create the fake Steam tree under ``tmp``. ``runtime_on`` and
    ``games_on`` are ``"internal"`` or ``"sdcard"``."""
    home = tmp / "home" / "deck"
    steam_root = home / ".local" / "share" / "Steam"
    sd_card = tmp / "run" / "media" / "mmcblk0p1"
    libs = {"internal": steam_root, "sdcard": sd_card}
    if runtime_on not in libs or games_on not in libs:
        raise ValueError("runtime_on/games_on must be 'internal' or 'sdcard'")

    for lib in libs.values():
        (lib / "steamapps" / "common").mkdir(parents=True, exist_ok=True)
    (home / ".steam").mkdir(parents=True, exist_ok=True)
    for link in ("root", "steam"):
        (home / ".steam" / link).symlink_to(steam_root)

    _install_stub("exec-after-dashdash", steam_root / "ubuntu12_32" / "reaper")
    _install_stub(
        "exec-after-dashdash", steam_root / "ubuntu12_32" / "steam-launch-wrapper"
    )

    # Steam Linux Runtime (sniper)
    rt_lib = libs[runtime_on]
    runtime_dir = rt_lib / "steamapps" / "common" / RUNTIME_INSTALLDIR
    entry_point = _install_stub("exec-after-dashdash", runtime_dir / "_v2-entry-point")
    (rt_lib / "steamapps" / f"appmanifest_{RUNTIME_APPID}.acf").write_text(
        _acf(RUNTIME_APPID, RUNTIME_NAME, RUNTIME_INSTALLDIR)
    )

    # GE-Proton in compatibilitytools.d (always on internal storage)
    ge_dir = steam_root / "compatibilitytools.d" / ge_name
    _install_stub("proton", ge_dir / "proton")
    (ge_dir / "toolmanifest.vdf").write_text(GE_TOOLMANIFEST)
    (ge_dir / "compatibilitytool.vdf").write_text(
        GE_COMPATIBILITYTOOL.replace("{name}", ge_name)
    )
    (ge_dir / "version").write_text(f"1700000000 {ge_name.removesuffix('-x86_64')}\n")
    (ge_dir / "files" / "bin").mkdir(parents=True)

    # Games
    game_lib = libs[games_on]
    games: dict[str, FakeGame] = {}

    plain_dir = game_lib / "steamapps" / "common" / "FakeGame"
    plain_dir.mkdir(parents=True)
    plain_exe = plain_dir / "game.exe"
    plain_exe.write_bytes(b"MZ fake game\n")
    games[PLAIN_GAME_APPID] = FakeGame(
        PLAIN_GAME_APPID, "Fake Game", game_lib, plain_dir, plain_exe
    )

    launcher_dir = game_lib / "steamapps" / "common" / "FakeLauncherGame"
    launcher_exe = _install_stub("launcher-game", launcher_dir / "Launcher.exe")
    games[LAUNCHER_GAME_APPID] = FakeGame(
        LAUNCHER_GAME_APPID,
        "Fake Launcher Game",
        game_lib,
        launcher_dir,
        launcher_exe,
    )

    for g in games.values():
        (game_lib / "steamapps" / f"appmanifest_{g.appid}.acf").write_text(
            _acf(g.appid, g.name, g.install_dir.name)
        )

    apps = {name: [] for name in libs}
    apps[runtime_on].append(RUNTIME_APPID)
    apps[games_on] += list(games)
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        _vdf_libraryfolders([(libs[n], apps[n]) for n in ("internal", "sdcard")])
    )

    return FakeSteam(
        home=home,
        steam_root=steam_root,
        sd_card=sd_card,
        log_path=tmp / "steam-calls.jsonl",
        runtime_dir=runtime_dir,
        entry_point=entry_point,
        ge_dir=ge_dir,
        games=games,
    )
