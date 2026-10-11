#!/usr/bin/env bash
# =============================================================================
#  wemod-deck installer for the Steam Deck (native Steam on SteamOS)
#  Ported from reference/install-wemod-launcher.sh (field-tested by Tom).
#
#  What it does:
#    1. Pre-flight checks (not root, python3 >= 3.9, curl, tar, sha512sum)
#    2. Installs wemod-deck via git clone (or from a .zip with --zip)
#    3. Downloads Wand (formerly WeMod) from WeMod's CDN, checksum-verified
#    4. Installs the latest GE-Proton into Steam's compatibilitytools.d
#    5. Creates the "WeMod + GE-Proton" compatibility tool
#
#  No sudo, no venv, no pip, no Tk. Nothing outside your home is touched.
#  Re-run it any time to update.
#
#  Usage (Desktop Mode -> Konsole):
#    ./install.sh               full install / update
#    ./install.sh --help        all options
# =============================================================================
set -Eeuo pipefail

# ----------------------------------------------------------------- defaults --
INSTALL_DIR="${HOME}/wemod-deck"
REPO_URL="${WEMOD_DECK_REPO:-https://github.com/Radverth/steam-deck-wemod.git}"
BRANCH="${WEMOD_DECK_BRANCH:-main}"
LOCAL_ZIP=""
DO_PROTON=1
DO_WEMOD=1
DO_TOOL=1
TOOL_NAME="WeMod-GE"
FORCE_WEMOD=0
UNINSTALL=0
GE_LATEST="${WEMOD_DECK_GE_LATEST:-https://github.com/GloriousEggroll/proton-ge-custom/releases/latest}"
GE_DL="${WEMOD_DECK_GE_DL:-https://github.com/GloriousEggroll/proton-ge-custom/releases/download}"
ARCH="$(uname -m)"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/wemod-deck"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/wemod-deck"

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
wemod-deck installer for Steam Deck

Options:
  --dir PATH        Install location (default: ~/wemod-deck)
  --zip PATH        Install from a downloaded steam-deck-wemod-main.zip instead of git
  --no-proton       Skip downloading/installing GE-Proton
  --no-wemod        Skip downloading Wand now (it is downloaded on first launch)
  --no-tool         Don't create the "WeMod + GE-Proton" compatibility tool
  --force-wemod     Re-download Wand even if it is up to date
  --uninstall       Remove wemod-deck and the tool (asks first; GE-Proton stays)
  -h, --help        Show this help

Re-running the script is safe: it updates and skips anything already installed.
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

steam_roots() {
    local d
    for d in "$HOME/.steam/root" "$HOME/.steam/steam" "$HOME/.local/share/Steam"; do
        if [[ -d "$d/steamapps" ]]; then realpath "$d"; fi
    done | awk '!seen[$0]++'
}

is_ours() { [[ -f "$1/wemod_deck/__main__.py" ]]; }

# ---------------------------------------------------------------- uninstall --
if [[ $UNINSTALL -eq 1 ]]; then
    if [[ -e "$INSTALL_DIR" ]] && ! is_ours "$INSTALL_DIR"; then
        die "$INSTALL_DIR is not a wemod-deck install; not touching it."
    fi
    printf 'This removes %s and the "%s" compatibility tool.\n' "$INSTALL_DIR" "$TOOL_NAME"
    printf 'Your Wand login, logs and settings are kept unless you remove them next.\n'
    read -r -p "Type YES to continue: " ans
    [[ "$ans" == "YES" ]] || { echo "Cancelled."; exit 0; }
    if [[ -d "$INSTALL_DIR" ]]; then rm -rf -- "$INSTALL_DIR"; ok "Removed $INSTALL_DIR"; fi
    while IFS= read -r root; do
        if [[ -d "$root/compatibilitytools.d/$TOOL_NAME" ]]; then
            rm -rf -- "$root/compatibilitytools.d/$TOOL_NAME"
            ok "Removed compatibility tool '$TOOL_NAME'"
        fi
    done < <(steam_roots)
    if [[ -d "$DATA_DIR" || -d "$CONFIG_DIR" ]]; then
        printf '\nAlso delete %s and %s\n(Wand binaries, shared login, logs, settings)?\n' \
            "$DATA_DIR" "$CONFIG_DIR"
        read -r -p "Type YES to delete them too, anything else keeps them: " ans
        if [[ "$ans" == "YES" ]]; then
            rm -rf -- "$DATA_DIR" "$CONFIG_DIR"
            ok "Removed data and settings"
        else
            ok "Kept $DATA_DIR"
        fi
    fi
    echo "Games set to '$TOOL_NAME' need another compatibility tool now (Properties > Compatibility)."
    echo "Game prefixes and saves were not touched."
    exit 0
fi

# ---------------------------------------------------------------- preflight --
step "Pre-flight checks"

[[ $EUID -ne 0 ]] || die "Don't run this with sudo/as root. Run it as the 'deck' user."

for cmd in curl tar python3 sha512sum; do
    command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' not found."
done
ok "curl, tar, python3, sha512sum found"

if [[ -z "$LOCAL_ZIP" ]] && ! command -v git >/dev/null 2>&1; then
    die "git not found. Re-run with --zip /path/to/steam-deck-wemod-main.zip"
fi

PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || die "Python $PY_VER is too old; wemod-deck needs 3.9+."
ok "Python $PY_VER"

# ------------------------------------------------------------- wemod-deck --
step "Installing wemod-deck to $INSTALL_DIR"

if [[ -e "$INSTALL_DIR" ]] && ! is_ours "$INSTALL_DIR" \
   && [[ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
    die "$INSTALL_DIR exists and is not wemod-deck. Pick another folder with --dir."
fi

if [[ -n "$LOCAL_ZIP" ]]; then
    [[ -f "$LOCAL_ZIP" ]] || die "Zip not found: $LOCAL_ZIP"
    mkdir -p "$HOME/.cache"
    TMP_UNZIP="$(mktemp -d -p "$HOME/.cache" wemod-deck-zip.XXXXXX)"
    python3 - "$LOCAL_ZIP" "$TMP_UNZIP" <<'PY'
import os, stat, sys, zipfile
zf, dest = sys.argv[1], os.path.realpath(sys.argv[2])
with zipfile.ZipFile(zf) as z:
    for info in z.infolist():
        target = os.path.realpath(os.path.join(dest, info.filename))
        if not target.startswith(dest + os.sep):
            raise SystemExit(f"Unsafe path in zip: {info.filename}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.symlink(z.read(info).decode(), target)
        elif info.is_dir():
            os.makedirs(target, exist_ok=True)
        else:
            z.extract(info, dest)
            if mode & 0o111:
                os.chmod(target, 0o755)
PY
    TOP="$(find "$TMP_UNZIP" -mindepth 1 -maxdepth 1 -type d | head -n1)"
    is_ours "$TOP" || die "Zip doesn't look like wemod-deck (no wemod_deck/)."
    rm -rf -- "$INSTALL_DIR"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    mv -- "$TOP" "$INSTALL_DIR"
    rm -rf -- "$TMP_UNZIP"
    ok "Installed from zip"
elif [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" fetch --quiet --depth 1 origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout --quiet --force -B "$BRANCH" FETCH_HEAD
    ok "Updated to $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
else
    rm -rf -- "$INSTALL_DIR"
    git clone --quiet --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned $(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
fi
chmod 755 "$INSTALL_DIR/wemod-deck" "$INSTALL_DIR/compat/proton"
WEMOD_DECK=("python3" "-s" "$INSTALL_DIR/wemod-deck")
"${WEMOD_DECK[@]}" --version >/dev/null || die "wemod-deck doesn't start with $(command -v python3)."
ok "wemod-deck $("${WEMOD_DECK[@]}" --version | awk '{print $2}') ready"

# ------------------------------------------------------------- Wand / WeMod --
if [[ $DO_WEMOD -eq 1 ]]; then
    step "Downloading Wand (formerly WeMod)"
    SETUP_ARGS=(setup)
    [[ $FORCE_WEMOD -eq 1 ]] && SETUP_ARGS+=(--force)
    if "${WEMOD_DECK[@]}" "${SETUP_ARGS[@]}"; then
        ok "Wand ready"
    else
        warn "Wand download failed; it will be retried on the first game launch."
    fi
fi

# ----------------------------------------------------------------- GE-Proton --
STEAM_ROOT="$(steam_roots | head -n1)"
GE_TAG=""
GE_DIR=""
COMPAT_DIR=""
if [[ -n "$STEAM_ROOT" ]]; then
    COMPAT_DIR="$STEAM_ROOT/compatibilitytools.d"
fi

if [[ $DO_PROTON -eq 1 ]]; then
    step "Installing latest GE-Proton"
    [[ -n "$STEAM_ROOT" ]] || die "Couldn't find your Steam folder. Use --no-proton and install GE-Proton with ProtonUp-Qt."
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

# ---------------------------------------------------- compatibility tool --
GE_NAME=""
if [[ $DO_TOOL -eq 1 ]]; then
    step "Creating the 'WeMod + GE-Proton' compatibility tool"

    if [[ -z "$GE_DIR" && -n "$COMPAT_DIR" && -d "$COMPAT_DIR" ]]; then
        # --no-proton: use the newest GE-Proton already installed
        GE_DIR="$(find "$COMPAT_DIR" -mindepth 1 -maxdepth 1 -type d -name 'GE-Proton*' -printf '%f\n' \
                  | sort -V | tail -n1)"
        [[ -n "$GE_DIR" ]] && GE_DIR="$COMPAT_DIR/$GE_DIR"
    fi

    if [[ -z "$GE_DIR" || ! -f "$GE_DIR/proton" ]]; then
        warn "No GE-Proton found, so the tool was skipped."
    else
        GE_NAME="$(basename "$GE_DIR")"; GE_NAME="${GE_NAME%-"$ARCH"}"
        TOOL_DIR="$COMPAT_DIR/$TOOL_NAME"
        rm -rf -- "$TOOL_DIR"
        mkdir -p "$TOOL_DIR"

        # Which Steam Linux Runtime GE-Proton wants (e.g. 1628350 = sniper).
        # Our tool must NOT require it itself, or Steam would start wemod-deck
        # inside that container. The wrapper starts it around GE-Proton only.
        RUNTIME_APPID=""
        if [[ -f "$GE_DIR/toolmanifest.vdf" ]]; then
            RUNTIME_APPID="$(sed -n 's/.*"require_tool_appid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$GE_DIR/toolmanifest.vdf" | head -n1)"
            grep -v 'require_tool_appid' "$GE_DIR/toolmanifest.vdf" > "$TOOL_DIR/toolmanifest.vdf"
        else
            printf '"manifest"\n{\n  "version" "2"\n  "commandline" "/proton %%verb%%"\n}\n' > "$TOOL_DIR/toolmanifest.vdf"
        fi

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
        {
            echo "# Written by install.sh; re-run it to change."
            printf 'GE_PROTON=%q\n' "$GE_DIR/proton"
            printf 'WEMOD_DECK_DIR=%q\n' "$INSTALL_DIR"
            printf 'STEAM_ROOT=%q\n' "$(dirname "$COMPAT_DIR")"
            printf 'RUNTIME_APPID=%q\n' "$RUNTIME_APPID"
        } > "$TOOL_DIR/tool.conf"
        install -m 755 "$INSTALL_DIR/compat/proton" "$TOOL_DIR/proton"
        ok "Created 'WeMod + $GE_NAME' in $TOOL_DIR"
    fi
fi

# -------------------------------------------------------------------- done --
step "All done"
cat <<EOF

${C_B}Use it from Game Mode, no Launch Options needed:${C_RST}
  1. Restart Steam (or reboot) so the new tool shows up.
  2. Game > Properties > Compatibility > tick "Force..." > pick
     ${C_G}WeMod + ${GE_NAME:-${GE_TAG:-GE-Proton}}${C_RST}
     To use it for every game: Steam > Settings > Compatibility > default tool.
  3. The first launch of a brand-new game runs it normally (Proton builds its
     prefix). From the next launch on, Wand starts with it. The very first
     time, a prebuilt prefix (~0.9 GB) is downloaded, so that launch is slow.
  4. Log in to Wand once; every game shares the login.

${C_B}No popups:${C_RST} if something goes wrong the game still starts, without Wand.
  Check:   $INSTALL_DIR/wemod-deck doctor
  Log:     $DATA_DIR/logs/launch.log
  Settings ($CONFIG_DIR/config.toml), e.g. turn it off for one game:
      [apps."<AppID>"]
      enabled = false

Re-run this script any time to update. Update Wand: --force-wemod
EOF
