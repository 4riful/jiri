#!/usr/bin/env bash
# Admin dashboard only (login required), on JIRI_ADMIN_PORT (default 5000).
# Runs the background workers: minute tick (weather, focus, water) + AI refill.
set -eu
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

export JIRI_WEB_SURFACE=admin
export JIRI_WEB_PORT=${JIRI_ADMIN_PORT:-5000}
export JIRI_WEB_QUIET=1
jiri_require_port "$JIRI_WEB_PORT" admin JIRI_ADMIN_PORT
exec "$PYTHON_BIN" -c "$JIRI_WEB_CMD"
