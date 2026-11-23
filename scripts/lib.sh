# shellcheck shell=bash
# Shared helpers for JIRI's shell scripts. Source it, do not execute it:
#   . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#
# After sourcing: the working directory is the repo root, PYTHONPATH=src, and
# PYTHON_BIN points at .venv/bin/python (or python3 when there is no venv).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1
export PYTHONPATH=src
PYTHON_BIN=${PYTHON_BIN:-.venv/bin/python}
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=python3
fi
export PYTHON_BIN

# The mock-display, fake-weather environment shared by the WSL dev and test
# loops. Nothing here touches real hardware or the network.
jiri_mock_env() {
  export JIRI_DISPLAY_DRIVER=mock
  export JIRI_FULLSCREEN=false
  export JIRI_WIDTH=480
  export JIRI_HEIGHT=320
  export JIRI_WEATHER_FAKE=true
}

# jiri_port_free PORT -> exit status 0 when PORT can be bound on loopback.
jiri_port_free() {
  "$PYTHON_BIN" - "$1" <<'PY'
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        sys.exit(1)
PY
}

# jiri_require_port PORT LABEL ENV_VAR -> exits 1 with a hint if PORT is taken.
jiri_require_port() {
  if ! jiri_port_free "$1"; then
    printf 'Port %s is already in use; %s was not started.\n' "$1" "$2" >&2
    printf 'Stop the existing process or run with %s=<free-port>.\n' "$3" >&2
    exit 1
  fi
}

# Launch the Flask app (surface/host/port come from JIRI_WEB_* env vars).
export JIRI_WEB_CMD='from jiri.web.app import main; main()'
