#!/usr/bin/env bash
set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH=src
export JIRI_WEB_SURFACE=screen
export JIRI_WEB_PORT=${JIRI_SCREEN_PORT:-5001}
export JIRI_WEB_QUIET=1
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
"$PYTHON_BIN" - "$JIRI_WEB_PORT" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        print(f"Port {port} is already in use; screen was not started.", file=sys.stderr)
        print("Stop the existing process or run with JIRI_SCREEN_PORT=<free-port>.", file=sys.stderr)
        sys.exit(1)
PY
exec "$PYTHON_BIN" -c 'from jiri.web.app import main; main()'
