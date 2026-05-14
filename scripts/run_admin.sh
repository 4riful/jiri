#!/usr/bin/env bash
set -eu
export PYTHONPATH=src
export JIRI_WEB_SURFACE=admin
export JIRI_WEB_PORT=${JIRI_ADMIN_PORT:-5000}
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
exec "$PYTHON_BIN" -m jiri.web.app
