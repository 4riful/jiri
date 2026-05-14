#!/usr/bin/env bash
set -eu
export PYTHONPATH=src
export JIRI_DB_PATH=${JIRI_DB_PATH:-data/jiri.db}
PYTHON_BIN=${PYTHON_BIN:-python3}
"$PYTHON_BIN" --version
"$PYTHON_BIN" - <<'PY'
import jiri
from jiri import db
db.init_db()
print("imports ok", jiri.__version__)
PY
"$PYTHON_BIN" -m jiri.cli init-db
"$PYTHON_BIN" -m jiri.cli todo add "Pi smoke todo"
"$PYTHON_BIN" -m jiri.cli todo list
"$PYTHON_BIN" -m jiri.cli health
grep MemAvailable /proc/meminfo || true
test -r /sys/class/thermal/thermal_zone0/temp && awk '{print "temp C: " $1/1000}' /sys/class/thermal/thermal_zone0/temp || true
df -h .
