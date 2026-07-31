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

echo ">>> Installing dependencies"
pip install -q -r requirements.txt

echo ">>> Starting Streamlit"
exec streamlit run app.py --server.headless true
