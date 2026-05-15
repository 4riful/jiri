#!/usr/bin/env bash
set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH=src
export JIRI_ADMIN_PORT=${JIRI_ADMIN_PORT:-5000}
export JIRI_SCREEN_PORT=${JIRI_SCREEN_PORT:-5001}
export PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi

ADMIN_PID=""
SCREEN_PID=""

cleanup() {
  status=$?
  if [ -n "$ADMIN_PID" ] && kill -0 "$ADMIN_PID" 2>/dev/null; then
    kill "$ADMIN_PID" 2>/dev/null || true
  fi
  if [ -n "$SCREEN_PID" ] && kill -0 "$SCREEN_PID" 2>/dev/null; then
    kill "$SCREEN_PID" 2>/dev/null || true
  fi
  wait "$ADMIN_PID" "$SCREEN_PID" 2>/dev/null || true
  exit "$status"
}

trap cleanup INT TERM EXIT

JIRI_WEB_SURFACE=admin JIRI_WEB_PORT="$JIRI_ADMIN_PORT" "$PYTHON_BIN" -m jiri.web.app &
ADMIN_PID=$!

JIRI_WEB_SURFACE=screen JIRI_WEB_PORT="$JIRI_SCREEN_PORT" "$PYTHON_BIN" -m jiri.web.app &
SCREEN_PID=$!

printf 'JIRI admin:  http://127.0.0.1:%s/admin\n' "$JIRI_ADMIN_PORT"
printf 'JIRI screen: http://127.0.0.1:%s/screen\n' "$JIRI_SCREEN_PORT"
printf 'Press Ctrl+C to stop both servers.\n'

wait "$ADMIN_PID" "$SCREEN_PID"
