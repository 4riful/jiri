#!/usr/bin/env bash
# Screen preview only (/screen, /screen.png), on JIRI_SCREEN_PORT (default 5001).
# No login on this surface, so it listens on loopback unless JIRI_SCREEN_HOST
# says otherwise. Read-only: it starts no background workers.
set -eu
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

export JIRI_WEB_SURFACE=screen
export JIRI_WEB_HOST=${JIRI_SCREEN_HOST:-127.0.0.1}
export JIRI_WEB_PORT=${JIRI_SCREEN_PORT:-5001}
export JIRI_WEB_QUIET=1
jiri_require_port "$JIRI_WEB_PORT" screen JIRI_SCREEN_PORT
exec "$PYTHON_BIN" -c "$JIRI_WEB_CMD"
