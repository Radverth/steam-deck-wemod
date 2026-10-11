#!/usr/bin/env bash
# =============================================================================
#  WeMod Launcher - Steam Deck installer
#  For DeckCheatz/wemod-launcher (1.x line)
#
#  What it does:
#    1. Pre-flight checks (python3 >= 3.9, tkinter, venv, curl, tar, git)
#    2. Installs / updates the launcher via git clone (keeps self-update working)
#       or from a local .zip with --zip
#    3. Builds the launcher's Python venv (FreeSimpleGUI) and writes wemod.conf
#    4. Pre-downloads winetricks, WeMod itself and DWriteCore.dll
#    5. Installs the latest GE-Proton into Steam's compatibilitytools.d
#    6. Prints the exact Launch Options line and the remaining in-Steam steps
#
#  Usage (Desktop Mode -> Konsole):
#    chmod +x install-wemod-launcher.sh
#    ./install-wemod-launcher.sh                # full install
#    ./install-wemod-launcher.sh --help         # all options
#
#  No sudo needed. Nothing outside your home directory is touched.
# =============================================================================
set -Eeuo pipefail

# ----------------------------------------------------------------- defaults --
INSTALL_DIR="${HOME}/wemod-launcher"
REPO_URL="https://github.com/DeckCheatz/wemod-launcher.git"
LOCAL_ZIP=""
DO_PROTON=1
DO_WEMOD=1
DO_TOOL=1
TOOL_NAME="WeMod-GE"
FORCE_WEMOD=0
UNINSTALL=0
GE_LATEST="https://github.com/GloriousEggroll/proton-ge-custom/releases/latest"
GE_DL="https://github.com/GloriousEggroll/proton-ge-custom/releases/download"
WINETRICKS_URL="https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks"
ARCH="$(uname -m)"
BROWSER_UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# ------------------------------------------------------------------- output --
if [[ -t 1 ]]; then
    C_RST=$'\e[0m'; C_B=$'\e[1m'; C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_C=$'\e[36m'
else
    C_RST=""; C_B=""; C_G=""; C_Y=""; C_R=""; C_C=""
fi
step() { printf '\n%s==>%s %s%s%s\n' "$C_C" "$C_RST" "$C_B" "$*" "$C_RST"; }
ok()   { printf '  %s✔%s %s\n' "$C_G" "$C_RST" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_Y" "$C_RST" "$*"; }
die()  { printf '\n%s✘ ERROR:%s %s\n' "$C_R" "$C_RST" "$*" >&2; exit 1; }
trap 'die "Failed at line $LINENO: $BASH_COMMAND"' ERR

usage() {
    cat <<EOF
WeMod Launcher installer for Steam Deck

Options:
  --dir PATH        Install location (default: ~/wemod-launcher)
  --zip PATH        Install from a downloaded wemod-launcher-main.zip instead of git
                    (self-update will NOT work with this method)
  --no-proton       Skip downloading/installing GE-Proton
  --no-wemod        Skip pre-downloading WeMod (launcher will do it on first run)
  --no-tool         Don't create the "WeMod + GE-Proton" compatibility tool
  --force-wemod     Re-download WeMod even if already present (update WeMod)
  --uninstall       Remove the launcher (asks first; GE-Proton is left in place)
  -h, --help        Show this help

Re-running the script is safe: it updates the launcher and skips anything
already installed.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)         INSTALL_DIR="${2:?--dir needs a path}"; shift 2 ;;
        --zip)         LOCAL_ZIP="${2:?--zip needs a path}"; shift 2 ;;
        --no-proton)   DO_PROTON=0; shift ;;
        --no-wemod)    DO_WEMOD=0; shift ;;
        --no-tool)     DO_TOOL=0; shift ;;
        --force-wemod) FORCE_WEMOD=1; shift ;;
        --uninstall)   UNINSTALL=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             die "Unknown option: $1 (see --help)" ;;
    esac
done

INSTALL_DIR="$(realpath -m "$INSTALL_DIR")"
SRC_DIR="${INSTALL_DIR}/src"
VENV_DIR="${SRC_DIR}/wemod_venv"
VENV_PY="${VENV_DIR}/bin/python"
WEMOD_BIN="${INSTALL_DIR}/wemod_data/wemod_bin"

# ---------------------------------------------------------------- uninstall --
if [[ $UNINSTALL -eq 1 ]]; then
    [[ -d "$INSTALL_DIR" ]] || die "Nothing installed at $INSTALL_DIR"
    printf 'This deletes %s (including saved WeMod login data).\n' "$INSTALL_DIR"
    read -r -p "Type YES to continue: " ans
    [[ "$ans" == "YES" ]] || { echo "Cancelled."; exit 0; }
    rm -rf -- "$INSTALL_DIR"
    ok "Removed $INSTALL_DIR"
    for d in "$HOME/.steam/root" "$HOME/.local/share/Steam" "$HOME/.var/app/com.valvesoftware.Steam/data/Steam"; do
        if [[ -d "$d/compatibilitytools.d/$TOOL_NAME" ]]; then
            rm -rf -- "$d/compatibilitytools.d/$TOOL_NAME"; ok "Removed compatibility tool '$TOOL_NAME'"
        fi
    done
    echo "Remember to clear '... wemod %command%' from each game's Launch Options."
    exit 0
fi

# ---------------------------------------------------------------- preflight --
step "Pre-flight checks"

[[ $EUID -ne 0 ]] || die "Don't run this with sudo/as root. Run it as the 'deck' user."

for cmd in curl tar python3 sha512sum; do
    command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' not found."
done
ok "curl, tar, python3, sha512sum found"

HAVE_GIT=0
if command -v git >/dev/null 2>&1; then HAVE_GIT=1; ok "git found"; fi
if [[ $HAVE_GIT -eq 0 && -z "$LOCAL_ZIP" ]]; then
    die "git not found. Re-run with --zip /path/to/wemod-launcher-main.zip"
fi

PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "Python $PY_VER is too old; the launcher needs 3.9+."
ok "Python $PY_VER"

if ! python3 -c 'import tkinter' 2>/dev/null; then
    cat >&2 <<'EOF'

  tkinter (Tk) is missing, and the launcher's popups need it.
  On SteamOS it normally ships with the system. If it's missing, you can
  install it (this unlocks the read-only root fs and gets reset by SteamOS
  updates):

      sudo steamos-readonly disable
      sudo pacman-key --init && sudo pacman-key --populate archlinux holo
      sudo pacman -S tk
      sudo steamos-readonly enable

EOF
    die "tkinter not available."
fi
ok "tkinter available"

python3 -c 'import venv' 2>/dev/null || die "Python 'venv' module missing."
ok "venv module available"

if ! curl -fsS --max-time 15 -o /dev/null https://github.com; then
    die "Can't reach GitHub. Check your internet connection."
fi
ok "Internet / GitHub reachable"

# ---------------------------------------------------------- launcher files --
step "Installing WeMod Launcher to $INSTALL_DIR"

backup_and_keep_data() {
    # Move a non-git install aside but keep WeMod login/bin data
    local bak
    bak="${INSTALL_DIR}.bak-$(date +%Y%m%d-%H%M%S)"
    mv -- "$INSTALL_DIR" "$bak"
    warn "Existing non-git install moved to $bak"
    if [[ -d "$bak/wemod_data" ]]; then
        mkdir -p "$INSTALL_DIR.tmpdata"
        cp -a "$bak/wemod_data" "$INSTALL_DIR.tmpdata/"
    fi
}
restore_data() {
    if [[ -d "$INSTALL_DIR.tmpdata/wemod_data" ]]; then
        cp -a "$INSTALL_DIR.tmpdata/wemod_data" "$INSTALL_DIR/"
        rm -rf -- "$INSTALL_DIR.tmpdata"
        ok "Restored previous wemod_data (login + WeMod binaries)"
    fi
}

if [[ -n "$LOCAL_ZIP" ]]; then
    [[ -f "$LOCAL_ZIP" ]] || die "Zip not found: $LOCAL_ZIP"
    [[ -e "$INSTALL_DIR" ]] && backup_and_keep_data
    TMP_UNZIP="$(mktemp -d)"
    python3 - "$LOCAL_ZIP" "$TMP_UNZIP" <<'PY'
import sys, zipfile, os, stat
zf, dest = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zf) as z:
    for info in z.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if not target.startswith(os.path.realpath(dest) + os.sep):
            raise SystemExit(f"Unsafe path in zip: {info.filename}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):                       # preserve the 'wemod' symlink
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(z.read(info).decode(), target)
        elif info.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            z.extract(info, dest)
PY
    TOP="$(find "$TMP_UNZIP" -mindepth 1 -maxdepth 1 -type d | head -n1)"
    [[ -f "$TOP/src/wemod.py" ]] || die "Zip doesn't look like wemod-launcher (no src/wemod.py)."
    mv -- "$TOP" "$INSTALL_DIR"
    rm -rf -- "$TMP_UNZIP"
    restore_data
    warn "Installed from zip: the launcher's self-update is disabled (no git)."
elif [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" fetch --quiet origin
    BRANCH="$(git -C "$INSTALL_DIR" branch --show-current)"
    if [[ "$BRANCH" != "main" ]]; then
        warn "On branch '$BRANCH', switching to main"
        git -C "$INSTALL_DIR" checkout --quiet main
    fi
    git -C "$INSTALL_DIR" reset --quiet --hard origin/main
    ok "Updated existing install to $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
else
    [[ -e "$INSTALL_DIR" ]] && backup_and_keep_data
    git clone --quiet --depth 1 --branch main "$REPO_URL" "$INSTALL_DIR"
    restore_data
    ok "Cloned $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
fi

[[ -f "$SRC_DIR/wemod.py" ]] || die "src/wemod.py missing after install."
# Make sure the root 'wemod' entrypoint exists (symlink to src/wemod.py)
if [[ ! -e "$INSTALL_DIR/wemod" ]]; then
    ln -s src/wemod.py "$INSTALL_DIR/wemod"
    warn "Recreated missing 'wemod' symlink"
fi
chmod -R ug+x "$SRC_DIR"/*.py "$SRC_DIR/wemod.bat"
ok "Permissions set"

# ------------------------------------------------------------- python venv --
step "Setting up the launcher's Python environment"

if [[ ! -x "$VENV_PY" ]]; then
    if ! python3 -m venv "$VENV_DIR" 2>/dev/null; then
        warn "venv without ensurepip, falling back to pip.pyz"
        rm -rf -- "$VENV_DIR"
        python3 -m venv --without-pip "$VENV_DIR"
    fi
fi

if "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    PIP=("$VENV_PY" -m pip)
else
    # Same fallback the launcher itself uses
    [[ -f "$VENV_DIR/bin/pip.pyz" ]] || \
        curl -fsSL -o "$VENV_DIR/bin/pip.pyz" https://bootstrap.pypa.io/pip/pip.pyz
    PIP=("$VENV_PY" "$VENV_DIR/bin/pip.pyz")
fi
"${PIP[@]}" install --quiet --disable-pip-version-check -r "$SRC_DIR/requirements.txt"
"$VENV_PY" -c 'import FreeSimpleGUI, tkinter' || die "FreeSimpleGUI/tkinter import failed in venv."
ok "venv ready ($(basename "$VENV_DIR")) with FreeSimpleGUI"

# Tell the launcher about the venv so it doesn't try system pip first
python3 - "$SRC_DIR/wemod.conf" <<'PY'
import configparser, sys
path = sys.argv[1]
c = configparser.ConfigParser(); c.optionxform = str
c.read(path)
if "Settings" not in c: c["Settings"] = {}
c["Settings"]["VirtualEnvironment"] = "wemod_venv"
with open(path, "w") as f: c.write(f)
PY
ok "wemod.conf updated (VirtualEnvironment = wemod_venv)"

# ------------------------------------------------- winetricks + WeMod binary --
if [[ $DO_WEMOD -eq 1 ]]; then
    step "Pre-downloading winetricks and WeMod"

    if [[ ! -f "$SRC_DIR/winetricks" || $FORCE_WEMOD -eq 1 ]]; then
        curl -fsSL -o "$SRC_DIR/winetricks.part" "$WINETRICKS_URL"
        mv -f "$SRC_DIR/winetricks.part" "$SRC_DIR/winetricks"
        chmod 755 "$SRC_DIR/winetricks"
        ok "winetricks downloaded"
    else
        ok "winetricks already present"
    fi

    if [[ -f "$WEMOD_BIN/WeMod.exe" && $FORCE_WEMOD -eq 0 ]]; then
        ok "WeMod already downloaded (use --force-wemod to update)"
    else
        # Uses the launcher's own code to find the WeMod URL (Scoop metadata)
        WEMOD_URL="$(cd "$SRC_DIR" && "$VENV_PY" -c \
            'import sys; sys.path.insert(0, "."); from setup import get_wemod_exe_url; print(get_wemod_exe_url())' \
            | tail -n1)"
        [[ "$WEMOD_URL" == http* ]] || die "Couldn't resolve the WeMod download URL."
        TMP_W="$(mktemp -d)"
        echo "  Downloading WeMod from: $WEMOD_URL"
        curl -fL --progress-bar -A "$BROWSER_UA" -o "$TMP_W/wemod_setup.exe" "$WEMOD_URL"

        rm -rf -- "$WEMOD_BIN"
        mkdir -p "$WEMOD_BIN"
        # Extract the app folder (lib/netXX/...) out of the Squirrel installer
        "$VENV_PY" - "$TMP_W/wemod_setup.exe" "$WEMOD_BIN" <<'PY'
import sys, os, zipfile, shutil
setup, dest = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(setup)
exe = [n for n in z.namelist() if n.startswith("lib/net") and n.endswith("/WeMod.exe")]
if not exe:
    raise SystemExit("WeMod.exe not found inside the installer")
prefix = exe[0].rsplit("/", 1)[0] + "/"
count = 0
for info in z.infolist():
    if not info.filename.startswith(prefix) or info.is_dir():
        continue
    rel = info.filename[len(prefix):]
    out = os.path.realpath(os.path.join(dest, rel))
    if not out.startswith(os.path.realpath(dest) + os.sep):
        raise SystemExit(f"Unsafe path: {info.filename}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with z.open(info) as s, open(out, "wb") as d:
        shutil.copyfileobj(s, d)
    count += 1
print(f"  extracted {count} files from {prefix}")
PY
        rm -rf -- "$TMP_W"
        [[ -f "$WEMOD_BIN/WeMod.exe" ]] || die "WeMod.exe missing after extraction."
        ok "WeMod installed to $WEMOD_BIN"
    fi

    # DWriteCore.dll fix (stops WeMod's Map panel crashing under Wine) - launcher's own code
    (cd "$SRC_DIR" && "$VENV_PY" -c \
        "import sys; sys.path.insert(0, '.'); from setup import ensure_dwritecore; ensure_dwritecore('$WEMOD_BIN')") \
        >/dev/null 2>&1 || true
    if [[ -f "$WEMOD_BIN/DWriteCore.dll" ]]; then
        ok "DWriteCore.dll in place"
    else
        warn "DWriteCore.dll not installed (launcher will retry on launch)"
    fi
fi

# ----------------------------------------------------------------- GE-Proton --
GE_TAG=""
GE_DIR=""
GE_NAME=""
COMPAT_DIR=""
if [[ $DO_PROTON -eq 1 ]]; then
    step "Installing latest GE-Proton"

    STEAM_ROOT=""
    for d in "$HOME/.steam/root" "$HOME/.steam/steam" "$HOME/.local/share/Steam" \
             "$HOME/.var/app/com.valvesoftware.Steam/data/Steam"; do
        if [[ -d "$d" ]]; then STEAM_ROOT="$(realpath "$d")"; break; fi
    done
    [[ -n "$STEAM_ROOT" ]] || die "Couldn't find your Steam folder. Use --no-proton and install GE-Proton with ProtonUp-Qt."
    [[ "$STEAM_ROOT" == *com.valvesoftware.Steam* ]] && \
        warn "Flatpak Steam detected - see the wiki's 'Steam-Flatpak-Usage' page for extra steps."
    COMPAT_DIR="$STEAM_ROOT/compatibilitytools.d"
    mkdir -p "$COMPAT_DIR"

    # Resolve latest tag via the releases/latest redirect (no API rate limit)
    LATEST_URL="$(curl -fsSL -o /dev/null -w '%{url_effective}' "$GE_LATEST")"
    GE_TAG="${LATEST_URL##*/}"
    [[ "$GE_TAG" =~ ^GE-Proton[0-9]+-[0-9]+$ ]] || die "Couldn't work out the latest GE-Proton version (got '$GE_TAG')."
    ok "Latest is $GE_TAG"

    if [[ -d "$COMPAT_DIR/$GE_TAG" || -d "$COMPAT_DIR/$GE_TAG-$ARCH" ]]; then
        ok "$GE_TAG already installed"
        if [[ -d "$COMPAT_DIR/$GE_TAG-$ARCH" ]]; then GE_DIR="$COMPAT_DIR/$GE_TAG-$ARCH"; else GE_DIR="$COMPAT_DIR/$GE_TAG"; fi
    else
        mkdir -p "$HOME/.cache"
        rm -rf -- "$HOME/.cache"/ge-proton.*   # leftovers from interrupted runs
        TMP_P="$(mktemp -d -p "$HOME/.cache" ge-proton.XXXXXX)"
        # Newer releases (GE-Proton11+) ship <tag>-<arch>.tar.gz; older ones ship <tag>.tar.gz
        ASSET=""
        for name in "$GE_TAG-$ARCH" "$GE_TAG"; do
            if curl -fsSL -r 0-0 -o /dev/null "$GE_DL/$GE_TAG/$name.tar.gz"; then ASSET="$name"; break; fi
        done
        [[ -n "$ASSET" ]] || die "No $ARCH download found for $GE_TAG. Use --no-proton and install it with ProtonUp-Qt."
        echo "  Downloading $ASSET.tar.gz (~500 MB)..."
        curl -fL --progress-bar -o "$TMP_P/ge.tar.gz" "$GE_DL/$GE_TAG/$ASSET.tar.gz"
        if curl -fsSL -o "$TMP_P/sum" "$GE_DL/$GE_TAG/$ASSET.sha512sum"; then
            EXPECTED="$(awk '{print $1}' "$TMP_P/sum")"
            ACTUAL="$(sha512sum "$TMP_P/ge.tar.gz" | awk '{print $1}')"
            [[ "$EXPECTED" == "$ACTUAL" ]] || die "GE-Proton checksum mismatch - download corrupted, re-run."
            ok "Checksum verified"
        else
            warn "No checksum file published for $ASSET, skipping verification"
        fi
        TOPDIR="$({ tar -tzf "$TMP_P/ge.tar.gz" || true; } | head -n1 | cut -d/ -f1)"
        [[ -n "$TOPDIR" ]] || die "GE-Proton archive looks empty."
        tar -xzf "$TMP_P/ge.tar.gz" -C "$COMPAT_DIR"
        rm -rf -- "$TMP_P"
        [[ -f "$COMPAT_DIR/$TOPDIR/proton" ]] || die "GE-Proton extraction failed."
        ok "$GE_TAG installed to $COMPAT_DIR/$TOPDIR"
        GE_DIR="$COMPAT_DIR/$TOPDIR"
    fi
fi

# ------------------------------------------------- WeMod compatibility tool --
# A tiny Steam compatibility tool that wraps GE-Proton and starts the game through
# the launcher, so you pick it in the Compatibility dropdown instead of typing
# Launch Options for every game.
if [[ $DO_TOOL -eq 1 ]]; then
    step "Creating the 'WeMod + GE-Proton' compatibility tool"

    if [[ -z "$COMPAT_DIR" ]]; then
        for d in "$HOME/.steam/root" "$HOME/.steam/steam" "$HOME/.local/share/Steam" \
                 "$HOME/.var/app/com.valvesoftware.Steam/data/Steam"; do
            if [[ -d "$d" ]]; then COMPAT_DIR="$(realpath "$d")/compatibilitytools.d"; break; fi
        done
    fi
    if [[ -z "$GE_DIR" && -n "$COMPAT_DIR" && -d "$COMPAT_DIR" ]]; then
        # --no-proton: use the newest GE-Proton already installed
        GE_DIR="$(find "$COMPAT_DIR" -mindepth 1 -maxdepth 1 -type d -name 'GE-Proton*' -printf '%f\n' \
                  | sort -V | tail -n1)"
        [[ -n "$GE_DIR" ]] && GE_DIR="$COMPAT_DIR/$GE_DIR"
    fi

    if [[ -z "$GE_DIR" || ! -f "$GE_DIR/proton" ]]; then
        warn "No GE-Proton found, so the tool was skipped (use the Launch Options line instead)."
    else
        GE_NAME="$(basename "$GE_DIR")"; GE_NAME="${GE_NAME%-"$ARCH"}"
        TOOL_DIR="$COMPAT_DIR/$TOOL_NAME"
        rm -rf -- "$TOOL_DIR"
        mkdir -p "$TOOL_DIR"

        # Which Steam Linux Runtime GE-Proton wants (e.g. 1628350 = sniper).
        # Our tool must NOT require it itself: Steam would then start the launcher
        # inside that container, whose Python has no tkinter. Instead the wrapper
        # starts the runtime itself, only around Proton/the game.
        RUNTIME_APPID=""
        if [[ -f "$GE_DIR/toolmanifest.vdf" ]]; then
            RUNTIME_APPID="$(sed -n 's/.*"require_tool_appid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$GE_DIR/toolmanifest.vdf" | head -n1)"
            grep -v 'require_tool_appid' "$GE_DIR/toolmanifest.vdf" > "$TOOL_DIR/toolmanifest.vdf"
        else
            printf '"manifest"\n{\n  "version" "2"\n  "commandline" "/proton %%verb%%"\n}\n' > "$TOOL_DIR/toolmanifest.vdf"
        fi
        TOOL_STEAM_ROOT="$(dirname "$COMPAT_DIR")"

        cat > "$TOOL_DIR/compatibilitytool.vdf" <<VDF
"compatibilitytools"
{
  "compat_tools"
  {
    "$TOOL_NAME"
    {
      "install_path" "."
      "display_name" "WeMod + $GE_NAME"
      "from_oslist"  "windows"
      "to_oslist"    "linux"
    }
  }
}
VDF

        cat > "$TOOL_DIR/proton" <<WRAP
#!/usr/bin/env bash
# Generated by install-wemod-launcher.sh - routes game launches through WeMod Launcher.
# Runs on the host (so the launcher has tkinter); the Steam Linux Runtime
# container is started here, around GE-Proton only.
GE_PROTON=$(printf '%q' "$GE_DIR/proton")
WEMOD=$(printf '%q' "$INSTALL_DIR/wemod")
STEAM_ROOT=$(printf '%q' "$TOOL_STEAM_ROOT")
RUNTIME_APPID=$(printf '%q' "$RUNTIME_APPID")
export STEAM_COMPAT_TOOL_PATHS="\$(dirname "\$GE_PROTON")\${STEAM_COMPAT_TOOL_PATHS:+:\$STEAM_COMPAT_TOOL_PATHS}"

find_runtime() {
    [[ -n "\$RUNTIME_APPID" ]] || return 1
    local lib acf dir ep
    while IFS= read -r lib; do
        acf="\$lib/steamapps/appmanifest_\$RUNTIME_APPID.acf"
        [[ -f "\$acf" ]] || continue
        dir="\$(sed -n 's/.*"installdir"[[:space:]]*"\\([^"]*\\)".*/\\1/p' "\$acf" | head -n1)"
        ep="\$lib/steamapps/common/\$dir/_v2-entry-point"
        if [[ -x "\$ep" ]]; then printf '%s\n' "\$ep"; return 0; fi
    done < <(printf '%s\n' "\$STEAM_ROOT"; sed -n 's/.*"path"[[:space:]]*"\\([^"]*\\)".*/\\1/p' "\$STEAM_ROOT/steamapps/libraryfolders.vdf" 2>/dev/null)
    return 1
}

VERB="\${1:-}"
RUNTIME_CMD=()
if RT="\$(find_runtime)"; then
    RUNTIME_CMD=("\$RT" "--verb=\$VERB" --)
fi

# Steam's housekeeping verbs (install scripts, path lookups) skip WeMod.
# So does the first ever launch of a game (GE-Proton builds the prefix),
# and any launch if the launcher has been removed.
if [[ "\$VERB" != "waitforexitandrun" ]] \\
   || [[ -n "\${STEAM_COMPAT_DATA_PATH:-}" && ! -d "\$STEAM_COMPAT_DATA_PATH/pfx/drive_c" ]] \\
   || [[ ! -e "\$WEMOD" ]]; then
    exec "\${RUNTIME_CMD[@]}" "\$GE_PROTON" "\$@"
fi

exec "\$WEMOD" "\${RUNTIME_CMD[@]}" "\$GE_PROTON" "\$@"
WRAP
        chmod 755 "$TOOL_DIR/proton"
        ok "Created 'WeMod + $GE_NAME' in $TOOL_DIR"
    fi
fi

# -------------------------------------------------------------------- done --
LAUNCH_OPT="$(printf '%q' "$INSTALL_DIR/wemod") %command%"

step "All done"
cat <<EOF

${C_B}Easiest: no Launch Options needed${C_RST}
  1. Restart Steam (or reboot) so the new tools show up.
  2. Game > Properties > Compatibility > tick "Force..." > pick
     ${C_G}WeMod + ${GE_NAME:-${GE_TAG:-GE-Proton}}${C_RST}  (leave Launch Options empty)
     Tip: to use it for EVERY game, set it in Steam > Settings > Compatibility
     as the default tool. Games with their own forced tool keep that one.
  3. First launch of a brand-new game runs it normally (builds its prefix).
     From the next launch on, WeMod starts with it.

${C_B}Manual alternative (per game, with plain GE-Proton selected):${C_RST}
    ${C_G}${LAUNCH_OPT}${C_RST}

${C_B}First WeMod launch of each game:${C_RST}
  - "copy prefix?" saying "might work" -> No; "likely works" or better -> Yes
  - Prefix Setup -> download, then Yes/OK through popups
    (rundll32.exe errors -> No, safe to ignore)
  - Log in to WeMod (first time only), select the game, press Play.

${C_B}Useful:${C_RST}
  Re-run this script any time to update. Update WeMod: --force-wemod
  Log file: $SRC_DIR/wemod.log
  ".NET error" in WeMod: close the game in-game, choose delete prefix in the
  troubleshooter, relaunch, answer No to copying a prefix, then pick download.
EOF
