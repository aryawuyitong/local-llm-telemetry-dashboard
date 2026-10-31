#!/bin/bash
# Starts the helper only. Dependency installation remains a visible manual step.
cd -- "$(dirname -- "$0")" || exit 1
LAB_PYTHON="./.venv/bin/python"
if [ ! -x "$LAB_PYTHON" ]; then
  echo "Create this lab's Python environment manually in this folder:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -r requirements.txt"
  echo "Then double-click Start Lab Helper again. Do not use sudo."
  if [ -t 0 ]; then read -r -p "Press Return to close." _; fi
  exit 1
fi
if ! "$LAB_PYTHON" -c "import sys, psutil; assert sys.version_info >= (3, 11)" >/dev/null 2>&1; then
  echo "The lab needs Python 3.11+ and its listed dependencies."
  echo "From this folder run: .venv/bin/python -m pip install -r requirements.txt"
  echo "If installation needs admin access or a security bypass, stop and ask the team."
  if [ -t 0 ]; then read -r -p "Press Return to close." _; fi
  exit 1
fi
exec "$LAB_PYTHON" -m telemetry_agent.helper
