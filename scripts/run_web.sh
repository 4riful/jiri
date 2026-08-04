#!/usr/bin/env bash
set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH=src
export JIRI_WEB_SURFACE=${JIRI_WEB_SURFACE:-admin}
export JIRI_WEB_PORT=${JIRI_WEB_PORT:-5000}
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
exec "$PYTHON_BIN" -m jiri.web.app
