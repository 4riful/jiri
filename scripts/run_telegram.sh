#!/usr/bin/env bash
set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH=src
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi

exec "$PYTHON_BIN" -m jiri.telegram poll
