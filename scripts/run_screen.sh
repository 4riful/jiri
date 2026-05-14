#!/usr/bin/env bash
set -eu
export PYTHONPATH=src
export JIRI_WEB_SURFACE=screen
export JIRI_WEB_PORT=${JIRI_SCREEN_PORT:-5001}
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
exec "$PYTHON_BIN" -m jiri.web.app
