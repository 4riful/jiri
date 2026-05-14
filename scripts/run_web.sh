#!/usr/bin/env bash
set -eu
export PYTHONPATH=src
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
"$PYTHON_BIN" -m jiri.web.app
