#!/bin/sh
# Deimos installer for macOS, Linux, WSL and Git Bash.
#
#   curl -fsSL https://raw.githubusercontent.com/kunal-shetty/deimos/main/scripts/install.sh | sh
#
# Installs Deimos into its own virtual environment in ~/.deimos/venv and puts a
# `deimos` command in ~/.local/bin. Running it again updates an existing install.
#
# Environment overrides:
#   DEIMOS_REF=<branch>          install a different branch (default: main)
#   DEIMOS_HOME=<dir>            where Deimos lives (default: ~/.deimos)
#   DEIMOS_BIN_DIR=<dir>         where the `deimos` command goes (default: ~/.local/bin)
#   DEIMOS_NO_MODIFY_PATH=1      don't add the bin directory to your shell profile
#   DEIMOS_SOURCE=<path or url>  install from a local checkout or another archive

set -eu

REPO="kunal-shetty/deimos"
REF="${DEIMOS_REF:-main}"
SOURCE="${DEIMOS_SOURCE:-https://github.com/$REPO/archive/refs/heads/$REF.zip}"
DEIMOS_HOME="${DEIMOS_HOME:-$HOME/.deimos}"
BIN_DIR="${DEIMOS_BIN_DIR:-$HOME/.local/bin}"
VENV="$DEIMOS_HOME/venv"

say()  { printf '  %s\n' "$*"; }
fail() { printf '\n  Error: %s\n\n' "$*" >&2; exit 1; }

printf '\n  Installing Deimos\n\n'

# ── 1. Python 3.11+ ──────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done
[ -n "$PYTHON" ] || fail "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ and run this again."
say "Using $("$PYTHON" -c 'import sys; print(f"Python {sys.version.split()[0]} at {sys.executable}")')"

# ── 2. Private virtual environment ───────────────────────────────────────────
mkdir -p "$DEIMOS_HOME"
if [ ! -d "$VENV" ]; then
    say "Creating an environment in $VENV"
    "$PYTHON" -m venv "$VENV" >/dev/null 2>&1 ||
        fail "Could not create a virtual environment. On Debian/Ubuntu, install it with: sudo apt install python3-venv"
fi
if [ -x "$VENV/bin/python" ]; then
    VENV_PY="$VENV/bin/python"; VENV_BIN="$VENV/bin"; EXE="deimos"
else  # Git Bash on Windows
    VENV_PY="$VENV/Scripts/python.exe"; VENV_BIN="$VENV/Scripts"; EXE="deimos.exe"
fi

# ── 3. Install Deimos ────────────────────────────────────────────────────────
say "Downloading and installing Deimos (this can take a minute)"
"$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$VENV_PY" -m pip install --quiet --disable-pip-version-check --upgrade --force-reinstall --no-deps "deimos @ $SOURCE"
"$VENV_PY" -m pip install --quiet --disable-pip-version-check "deimos @ $SOURCE"
[ -e "$VENV_BIN/$EXE" ] || fail "The install finished but $VENV_BIN/$EXE is missing."

# ── 4. Put `deimos` on the PATH ──────────────────────────────────────────────
# Only the deimos command is linked, so the environment's python and pip
# never shadow the ones you already use.
mkdir -p "$BIN_DIR"
if [ "$EXE" = "deimos.exe" ]; then
    printf '#!/bin/sh\nexec "%s" "$@"\n' "$VENV_BIN/$EXE" > "$BIN_DIR/deimos"
    chmod +x "$BIN_DIR/deimos"
else
    ln -sf "$VENV_BIN/deimos" "$BIN_DIR/deimos"
fi
say "Linked $BIN_DIR/deimos"

PATH_NOTE=""
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        if [ "${DEIMOS_NO_MODIFY_PATH:-0}" = "1" ]; then
            PATH_NOTE="Add $BIN_DIR to your PATH to run deimos from anywhere."
        else
            LINE="export PATH=\"$BIN_DIR:\$PATH\"  # added by the Deimos installer"
            case "$(basename "${SHELL:-sh}")" in
                zsh)  PROFILES="$HOME/.zshrc" ;;
                bash) PROFILES="$HOME/.bashrc"
                      [ -f "$HOME/.bash_profile" ] && PROFILES="$PROFILES $HOME/.bash_profile" ;;
                *)    PROFILES="$HOME/.profile" ;;
            esac
            for rc in $PROFILES; do
                if ! grep -qs "added by the Deimos installer" "$rc"; then
                    printf '\n%s\n' "$LINE" >> "$rc"
                    say "Added $BIN_DIR to PATH in $rc"
                fi
            done
            PATH_NOTE="Open a new terminal (or run: export PATH=\"$BIN_DIR:\$PATH\") so the deimos command is found."
        fi
        ;;
esac

# ── 5. Done ──────────────────────────────────────────────────────────────────
VERSION="$("$VENV_BIN/$EXE" --version 2>/dev/null || echo deimos)"
printf '\n  Installed %s\n\n' "$VERSION"
[ -z "$PATH_NOTE" ] || say "$PATH_NOTE"
say "Run 'deimos' in any project folder. The first run asks for your Groq API key."
say "Update later with 'deimos update'. Uninstall by deleting $DEIMOS_HOME and $BIN_DIR/deimos."
printf '\n'
