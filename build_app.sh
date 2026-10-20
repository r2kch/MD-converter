#!/usr/bin/env bash
#
# build_app.sh — build MDConverter.app (UNsigned, self-contained venv bundle).
#
# Produces a double-clickable .app that runs the PyObjC GUI (src/main.py) on a
# Python venv bundled INSIDE the .app (Contents/Frameworks/.venv), so the app
# is a self-contained unit on this Mac and does not depend on the project venv.
#
# Usage:
#   ./build_app.sh [--install] [PYTHON_BIN]
#
#   --install      also copy MDConverter.app to ~/Applications afterwards
#                  (override the target dir with the INSTALL_DEST env var)
#   PYTHON_BIN     optional positional: the python to base the venv on.
#                  Precedence: positional arg > $PYTHON_BIN env > default.
#
# Idempotent: every run tears down and rebuilds MDConverter.app from scratch,
# so a stale/partial bundle can never be left behind.
#
set -euo pipefail

# ------------------------------------------------------------------- config --
APP_NAME="MDConverter"
DEFAULT_PYTHON_BIN="/opt/homebrew/bin/python3"

# --------------------------------------------------------------------- args --
DO_INSTALL=0
ARG_PYTHON=""
for arg in "$@"; do
  case "$arg" in
    --install) DO_INSTALL=1 ;;
    -h|--help)
      echo "Usage: $0 [--install] [PYTHON_BIN]"
      echo "  --install   copy MDConverter.app to ~/Applications"
      echo "  PYTHON_BIN  python to base the venv on (positional > \$PYTHON_BIN > $DEFAULT_PYTHON_BIN)"
      exit 0
      ;;
    *) ARG_PYTHON="$arg" ;;
  esac
done

PYTHON_BIN="${ARG_PYTHON:-${PYTHON_BIN:-$DEFAULT_PYTHON_BIN}}"

# ----------------------------------------------------------------- sanity ----
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: Python not found: $PYTHON_BIN" >&2
  echo "       Override: PYTHON_BIN=/path/to/python3 $0  (or as the 1st argument)" >&2
  exit 1
fi
if [ ! -x "$PYTHON_BIN" ]; then
  echo "Error: $PYTHON_BIN is not executable." >&2
  exit 1
fi

# Repo root = the directory this script lives in (works from any CWD).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$REPO_ROOT/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
VENV_DIR="$CONTENTS/Frameworks/.venv"

for f in "$REPO_ROOT/src/main.py" "$REPO_ROOT/src/converters.py" "$REPO_ROOT/requirements.txt" "$REPO_ROOT/assets/AppIcon.icns"; do
  if [ ! -f "$f" ]; then
    echo "Error: missing input file: $f" >&2
    echo "       Expected repo layout: src/main.py, src/converters.py, requirements.txt" >&2
    exit 1
  fi
done

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

echo ">> Building $APP_NAME.app"
echo "   Repo:      $REPO_ROOT"
echo "   Python:    $PYTHON_BIN (Python $PYTHON_VERSION)"

# --------------------------------------------------------- full rebuild ------
# Wipe any previous bundle so the build is idempotent and never half-stale.
rm -rf "$APP_DIR"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Frameworks" "$CONTENTS/Resources"
printf 'APPL????' > "$CONTENTS/PkgInfo"

# ------------------------------------------------------------------- venv ----
echo ">> Creating venv in bundle: $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo ">> Installing requirements.txt into the venv"
"$VENV_DIR/bin/python3" -m pip install -r "$REPO_ROOT/requirements.txt"

# --------------------------------------------------------------- resources ---
# main.py adds its own directory to sys.path, so converters.py MUST sit next to
# it. Copy both into Contents/Resources/ so the bundle is self-contained.
cp "$REPO_ROOT/src/main.py"       "$CONTENTS/Resources/main.py"
cp "$REPO_ROOT/src/converters.py" "$CONTENTS/Resources/converters.py"
cp "$REPO_ROOT/assets/AppIcon.icns" "$CONTENTS/Resources/AppIcon.icns"

# -------------------------------------------------------------- Info.plist ----
cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>MDConverter</string>
	<key>CFBundleDisplayName</key>
	<string>MDConverter</string>
	<key>CFBundleIdentifier</key>
	<string>com.local.mdconverter</string>
	<key>CFBundleExecutable</key>
	<string>MDConverter</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleVersion</key>
	<string>1</string>
	<key>CFBundleShortVersionString</key>
	<string>1.0</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>LSMinimumSystemVersion</key>
	<string>13.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>LSApplicationCategoryType</key>
	<string>public.app-category.productivity</string>
	<key>NSHumanReadableCopyright</key>
	<string>Built locally - unsigned (not signed / not notarized)</string>
</dict>
</plist>
PLIST

# ---------------------------------------------------------------- launcher ---
# A small bash launcher. It resolves the venv and main.py RELATIVE to its own
# path (Finder double-click safe), never relative to the CWD, and execs the
# bundled venv python on main.py.
cat > "$CONTENTS/MacOS/$APP_NAME" <<'LAUNCHER'
#!/bin/bash
# MDConverter launcher — execs the bundled venv Python on the bundled main.py.
# All paths are resolved relative to this executable (not the CWD), so a
# double-click from Finder or Launch Services works from anywhere.
set -euo pipefail
# Defined here (the heredoc is quoted, so the outer $APP_NAME is NOT expanded
# at build time); keeps the diagnostic messages below safe under `set -u`.
APP_NAME="MDConverter"

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTENTS_DIR="$(cd "$SELF_DIR/.." && pwd)"
VENV_PY="$CONTENTS_DIR/Frameworks/.venv/bin/python3"
MAIN_PY="$CONTENTS_DIR/Resources/main.py"

if [ ! -x "$VENV_PY" ]; then
  echo "$APP_NAME: venv missing ($VENV_PY). Please rebuild: ./build_app.sh" >&2
  exit 1
fi
if [ ! -f "$MAIN_PY" ]; then
  echo "$APP_NAME: main.py missing ($MAIN_PY). Please rebuild: ./build_app.sh" >&2
  exit 1
fi

cd "$CONTENTS_DIR/Resources"
exec "$VENV_PY" "$MAIN_PY" "$@"
LAUNCHER
chmod +x "$CONTENTS/MacOS/$APP_NAME"

# ----------------------------------------------------------------- install ---
if [ "$DO_INSTALL" -eq 1 ]; then
  DEST="${INSTALL_DEST:-$HOME/Applications}"
  mkdir -p "$DEST"
  rm -rf "$DEST/$APP_NAME.app"
  cp -R "$APP_DIR" "$DEST/"
  echo ">> Installed to: $DEST/$APP_NAME.app"
fi

# ---------------------------------------------------------------- next steps --
echo
echo "Done: $APP_DIR"
echo
echo "Next steps:"
echo "  1. Launch: double-click $APP_DIR  (or: open \"$APP_DIR\")"
echo "     The .app is built locally and carries NO quarantine attribute,"
echo "     so it launches directly, without a Gatekeeper warning."
echo "  2. If macOS does ask (e.g. a copy that was quarantined in transit):"
echo "     right-click the .app -> \"Open\" -> \"Open\"."
echo "  3. The app is UNSIGNED: intended for local use only (no"
echo "     Apple Developer certificate, no notarization)."
echo "  4. For console output:  \"$APP_DIR/Contents/MacOS/$APP_NAME\""
echo "  5. After a Homebrew Python update:  re-run ./build_app.sh"
