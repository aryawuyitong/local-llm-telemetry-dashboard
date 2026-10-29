#!/bin/bash
# Double-click this file to start the Local AI Lab (macOS).
# Keep this window open while you use the lab; close it to stop.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "The lab needs Python 3. Install it from https://www.python.org/downloads/ and double-click this file again."
  read -r -p "Press Return to close." _
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up the lab's own Python environment in this folder (one time, about 20 seconds)..."
  if ! { python3 -m venv .venv && .venv/bin/python -m pip install --quiet -r requirements.txt; }; then
    rm -rf .venv
    echo "Setup failed. Send the text in this window to your lab team."
    read -r -p "Press Return to close." _
    exit 1
  fi
fi

exec .venv/bin/python -m telemetry_agent.helper
