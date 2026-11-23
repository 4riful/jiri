#!/usr/bin/env bash
# WSL dev loop: admin dashboard on 0.0.0.0:JIRI_ADMIN_PORT (default 5000) and
# the screen preview on 127.0.0.1:JIRI_SCREEN_PORT (default 5001). Restarts any
# JIRI web process it started before. Ctrl+C stops both.
set -eu
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

export JIRI_ADMIN_PORT=${JIRI_ADMIN_PORT:-5000}
export JIRI_SCREEN_PORT=${JIRI_SCREEN_PORT:-5001}
export JIRI_WEB_QUIET=1
# Dev loop: hot-reload templates (off in production on the Pi).
export JIRI_DEV=${JIRI_DEV:-1}
# The screen preview has no login, so it only listens on loopback unless
# JIRI_SCREEN_HOST says otherwise. The admin (login-protected) uses config.
JIRI_SCREEN_HOST=${JIRI_SCREEN_HOST:-127.0.0.1}
PID_DIR=${JIRI_RUN_DIR:-/tmp/jiri-run}

mkdir -p "$PID_DIR"
ADMIN_PID_FILE="$PID_DIR/admin-${JIRI_ADMIN_PORT}.pid"
SCREEN_PID_FILE="$PID_DIR/screen-${JIRI_SCREEN_PORT}.pid"

is_jiri_pid() {
  pid="$1"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    return 1
  fi
  cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  case "$cmd" in
    *"from jiri.web.app import main; main()"*|*"jiri.web.app"*) return 0 ;;
    *) return 1 ;;
  esac
}

stop_pid() {
  pid="$1"
  label="$2"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  printf 'Previous JIRI %s process %s did not stop; forcing it.\n' "$label" "$pid" >&2
  kill -KILL "$pid" 2>/dev/null || true
}

clear_previous() {
  pid_file="$1"
  label="$2"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if is_jiri_pid "$pid"; then
    printf 'Stopping previous JIRI %s process %s.\n' "$label" "$pid"
    stop_pid "$pid" "$label"
  fi
  rm -f "$pid_file"
}

jiri_pids_on_port() {
  "$PYTHON_BIN" - "$1" <<'PY'
from pathlib import Path
import os
import sys

port_hex = f"{int(sys.argv[1]):04X}"
inodes = set()
for table in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        lines = Path(table).read_text().splitlines()[1:]
    except OSError:
        continue
    for line in lines:
        parts = line.split()
        if len(parts) < 10 or parts[3] != "0A":
            continue
        local = parts[1]
        if local.rsplit(":", 1)[-1].upper() == port_hex:
            inodes.add(parts[9])

if not inodes:
    sys.exit(0)

seen = set()
for proc in Path("/proc").iterdir():
    if not proc.name.isdigit():
        continue
    fd_dir = proc / "fd"
    try:
        fds = list(fd_dir.iterdir())
    except OSError:
        continue
    matched = False
    for fd in fds:
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:[") and target[8:-1] in inodes:
            matched = True
            break
    if not matched:
        continue
    try:
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        continue
    if "jiri.web.app" in cmdline and proc.name not in seen:
        seen.add(proc.name)
        print(proc.name)
PY
}

clear_jiri_on_port() {
  port="$1"
  label="$2"
  pids="$(jiri_pids_on_port "$port")"
  for pid in $pids; do
    if is_jiri_pid "$pid"; then
      printf 'Stopping previous JIRI %s process %s on port %s.\n' "$label" "$pid" "$port"
      stop_pid "$pid" "$label"
    fi
  done
}

if [ "$JIRI_ADMIN_PORT" = "$JIRI_SCREEN_PORT" ]; then
  printf 'Port conflict: admin and screen both configured for %s.\n' "$JIRI_ADMIN_PORT" >&2
  printf 'Set JIRI_ADMIN_PORT and JIRI_SCREEN_PORT to different values.\n' >&2
  exit 1
fi

clear_previous "$ADMIN_PID_FILE" "admin"
clear_previous "$SCREEN_PID_FILE" "screen"
clear_jiri_on_port "$JIRI_ADMIN_PORT" "admin"
clear_jiri_on_port "$JIRI_SCREEN_PORT" "screen"

jiri_require_port "$JIRI_ADMIN_PORT" admin JIRI_ADMIN_PORT
jiri_require_port "$JIRI_SCREEN_PORT" screen JIRI_SCREEN_PORT

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
  if [ -n "$ADMIN_PID" ] && [ -f "$ADMIN_PID_FILE" ] && [ "$(tr -d '[:space:]' < "$ADMIN_PID_FILE" 2>/dev/null || true)" = "$ADMIN_PID" ]; then
    rm -f "$ADMIN_PID_FILE"
  fi
  if [ -n "$SCREEN_PID" ] && [ -f "$SCREEN_PID_FILE" ] && [ "$(tr -d '[:space:]' < "$SCREEN_PID_FILE" 2>/dev/null || true)" = "$SCREEN_PID" ]; then
    rm -f "$SCREEN_PID_FILE"
  fi
  exit "$status"
}

trap cleanup INT TERM EXIT

JIRI_WEB_SURFACE=admin JIRI_WEB_PORT="$JIRI_ADMIN_PORT" "$PYTHON_BIN" -c "$JIRI_WEB_CMD" &
ADMIN_PID=$!
printf '%s\n' "$ADMIN_PID" > "$ADMIN_PID_FILE"

JIRI_WEB_SURFACE=screen JIRI_WEB_HOST="$JIRI_SCREEN_HOST" JIRI_WEB_PORT="$JIRI_SCREEN_PORT" "$PYTHON_BIN" -c "$JIRI_WEB_CMD" &
SCREEN_PID=$!
printf '%s\n' "$SCREEN_PID" > "$SCREEN_PID_FILE"

printf 'JIRI admin:  http://127.0.0.1:%s/admin\n' "$JIRI_ADMIN_PORT"
printf 'JIRI screen: http://%s:%s/screen\n' "$JIRI_SCREEN_HOST" "$JIRI_SCREEN_PORT"
printf 'Press Ctrl+C to stop both servers.\n'

wait "$ADMIN_PID" "$SCREEN_PID"
