#!/usr/bin/env bash
set -eu
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m jiri.cli init-db
