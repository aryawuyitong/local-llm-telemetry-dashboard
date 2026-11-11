#!/bin/bash
# Double-click to start the lab. On the first run it sets up a private Python environment in
# this folder. If this Mac has no Python 3.11 or newer, it shows what it would download and
# waits for your OK before putting a private copy of Python in this folder.
# It never installs system software, uses sudo or changes security settings.
cd -- "$(dirname -- "$0")" || exit 1
LAB_PYTHON="./.venv/bin/python"

# The private copy of Python, if one is needed: the official CPython build packaged by Astral
# (python-build-standalone), pinned to one release and checked against its published SHA-256.
PY_VERSION="3.12.16"
PY_BUILD="20261026"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/$PY_BUILD"
PY_SHA_ARM64="fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e"
PY_SHA_X86_64="a962e47df522889eaa7ff0d6a56203f1079f68aabb65ffdbe8455f362bc769f3"

stop() {
  echo "$1"
  if [ -t 0 ]; then read -r -p "Press Return to close." _; fi
  exit 1
}

usable() { "$1" -c "import sys; assert sys.version_info >= (3, 11)" >/dev/null 2>&1; }

# A Python 3.11+ this Mac already has, or the private copy from an earlier run.
find_python() {
  local candidate found
  for candidate in ./.python/python/bin/python3 python3.14 python3.13 python3.12 python3.11 python3; do
    found="$(command -v "$candidate" 2>/dev/null)" || continue
    # Apple's /usr/bin/python3 is only a stub until the developer tools exist; running it opens an
    # install dialog, so skip it then. With the tools it is still too old (3.9) and fails the check.
    if [ "$found" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if usable "$found"; then echo "$found"; return 0; fi
  done
  return 1
}

download_python() {
  local arch sha file actual
  case "$(uname -m)" in
    arm64) arch="aarch64"; sha="$PY_SHA_ARM64" ;;
    x86_64) arch="x86_64"; sha="$PY_SHA_X86_64" ;;
    *) stop "The lab needs Python 3.11 or newer, and this Mac doesn't have it. Install Python 3 from python.org, then double-click Start Lab Helper again." ;;
  esac
  file="cpython-$PY_VERSION+$PY_BUILD-$arch-apple-darwin-install_only.tar.gz"
  echo "This Mac doesn't have Python 3.11 or newer, which the lab needs."
  echo
  echo "The lab can download a private copy of Python $PY_VERSION (about 25 MB) into this folder:"
  echo "  from: $PY_URL/$file"
  echo "  to:   $(pwd)/.python"
  echo "It is the official CPython build packaged by Astral (python-build-standalone). The lab checks"
  echo "the download against its published SHA-256 before using it. It installs nothing anywhere else"
  echo "and needs no password. To undo it later, delete the .python folder."
  echo
  if [ -t 0 ]; then
    read -r -p "Press Return to download it, or close this window to stop. " _
  else
    stop "Open this file from Finder or a terminal window so you can approve the download."
  fi
  rm -rf .python && mkdir .python || stop "Couldn't create the .python folder here."
  echo "Downloading Python $PY_VERSION..."
  curl -fL --progress-bar -o ".python/$file" "$PY_URL/$file" || { rm -rf .python; stop "The download failed. Check your internet connection, then double-click Start Lab Helper again."; }
  actual="$(shasum -a 256 ".python/$file" | awk '{print $1}')"
  if [ "$actual" != "$sha" ]; then
    rm -rf .python
    stop "The downloaded file didn't match its published checksum, so the lab deleted it. Try again later, or tell the team."
  fi
  echo "Checksum matches. Unpacking..."
  tar -xzf ".python/$file" -C .python && rm -f ".python/$file" || { rm -rf .python; stop "Unpacking Python failed. Send the text in this window to the team."; }
  usable ./.python/python/bin/python3 || { rm -rf .python; stop "The downloaded Python didn't start. Send the text in this window to the team."; }
  echo "Python $PY_VERSION is ready in $(pwd)/.python."
}

if [ ! -x "$LAB_PYTHON" ]; then
  BASE="$(find_python)" || { download_python; BASE="./.python/python/bin/python3"; }
  echo "First run: creating the lab's private Python environment in this folder (about 20 seconds)."
  echo "This only adds a .venv folder here. Delete the folder to undo it."
  "$BASE" -m venv .venv && "$LAB_PYTHON" -m pip install --quiet --disable-pip-version-check -r requirements.txt || stop "Setup failed. Send the text in this window to the team."
fi
"$LAB_PYTHON" -c "import sys, psutil; assert sys.version_info >= (3, 11)" >/dev/null 2>&1 || stop "This folder's .venv is missing Python 3.11+ or a dependency. Delete the .venv folder and double-click Start Lab Helper again."
exec "$LAB_PYTHON" -m telemetry_agent.helper
