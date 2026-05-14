#!/usr/bin/env bash
set -eu
export PYTHONPATH=src
export JIRI_DISPLAY_DRIVER=mock
export JIRI_FULLSCREEN=false
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_WEATHER_FAKE=true
export JIRI_WEATHER_LOCATION=${JIRI_WEATHER_LOCATION:-auto}
export JIRI_DB_PATH=${JIRI_DB_PATH:-data/jiri_test_wsl.db}
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
PYTHON_BIN=.venv/bin/python
"$PYTHON_BIN" -m pip install -r requirements-dev.txt
rm -f "$JIRI_DB_PATH"
"$PYTHON_BIN" -m pytest
"$PYTHON_BIN" -m jiri.cli init-db
"$PYTHON_BIN" -m jiri.cli todo add "WSL smoke todo" --due "2026-05-14 21:00"
"$PYTHON_BIN" -m jiri.cli todo list
"$PYTHON_BIN" -m jiri.cli todo done 1
"$PYTHON_BIN" -m jiri.cli note add "WSL smoke note" --body "JIRI notes work from SSH."
"$PYTHON_BIN" -m jiri.cli note list
"$PYTHON_BIN" -m jiri.cli focus start --minutes 1 --title "WSL smoke focus"
"$PYTHON_BIN" -m jiri.cli focus status
"$PYTHON_BIN" -m jiri.cli focus pause
"$PYTHON_BIN" -m jiri.cli focus resume
"$PYTHON_BIN" -m jiri.cli focus complete
"$PYTHON_BIN" -m jiri.ui.pygame_app
"$PYTHON_BIN" -m jiri.cli location set-coords --name "WSL Smoke" --lat 26.1167 --lon 88.85
"$PYTHON_BIN" -m jiri.cli location current
"$PYTHON_BIN" -m jiri.cli weather refresh
"$PYTHON_BIN" -m jiri.cli status
"$PYTHON_BIN" -m jiri.cli health
