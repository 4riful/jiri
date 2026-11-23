#!/usr/bin/env bash
# The full local gate: pytest, then a CLI walkthrough and a headless pygame
# smoke run against a throwaway DB with fake weather. CI runs the same shape.
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -x "$SCRIPT_DIR/../.venv/bin/python" ]; then
  python3 -m venv "$SCRIPT_DIR/../.venv"
fi
. "$SCRIPT_DIR/lib.sh"
jiri_mock_env

export JIRI_WEATHER_LOCATION=${JIRI_WEATHER_LOCATION:-auto}
export JIRI_DB_PATH=${JIRI_TEST_DB_PATH:-$ROOT_DIR/data/jiri_test_wsl.db}

"$PYTHON_BIN" -m pip install -q -r requirements-dev.txt
rm -f "$JIRI_DB_PATH"
"$PYTHON_BIN" -m pytest -q

cli() { "$PYTHON_BIN" -m jiri.cli "$@"; }
cli init-db
cli todo add "WSL smoke todo" --due "2026-05-14 21:00"
cli todo list
cli todo "done" 1
cli note add "WSL smoke note" --body "JIRI notes work from SSH."
cli note list
cli focus start --minutes 1 --title "WSL smoke focus"
cli focus status
cli focus pause
cli focus resume
cli focus complete
"$PYTHON_BIN" -m jiri.ui.pygame_app
cli location set-coords --name "WSL Smoke" --lat 38.7223 --lon -9.1393
cli location current
cli weather refresh
cli status
cli health
