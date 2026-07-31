#!/usr/bin/env bash
# One-click launcher for ai-radar.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo ">>> Creating virtual environment (.venv)"
  # Prefer python3.11+, fall back to system python3
  if command -v python3.11 >/dev/null 2>&1; then
    PY=python3.11
  elif command -v python3.12 >/dev/null 2>&1; then
    PY=python3.12
  else
    PY=python3
  fi
  "$PY" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "ERROR: AI Radar requires Python 3.11 or newer."
  echo "Delete .venv after installing a newer Python, then run ./run.sh again."
  exit 1
fi

echo ">>> Installing dependencies"
python -m pip install -q -r requirements.txt

echo ">>> Starting AI Radar"
echo ">>> Open http://localhost:8501 if the browser does not open automatically."
exec python -m ai_radar.launcher
