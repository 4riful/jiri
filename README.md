# JIRI

JIRI is a lightweight Raspberry Pi 3B/3B+ desk assistant with deterministic core behavior, a small animated face UI, todos, notes, weather, a phone-friendly web dashboard, and SSH CLI control.

The project is designed for Raspberry Pi OS on 1GB RAM hardware with a 3.5-inch GPIO display. Development is WSL-safe, but production decisions prioritize the Raspberry Pi.

## Design Rules

- Reliable first.
- Lightweight second.
- Funny third.
- AI-enhanced only later.
- SQLite owns important state.
- Python business logic owns todos, reminders, due dates, weather cache, and system state.
- Optional future LLMs may only rewrite messages, never manage state.

## WSL And Pi Split

WSL-safe code includes config loading, SQLite schema, todos, notes, mood, deterministic messages, CLI, Flask web dashboard, weather parsing/fallback, and unit tests.

Raspberry Pi-only confirmation includes GPIO display behavior, Pygame fullscreen/framebuffer behavior, service boot behavior, real CPU/RAM measurements, display rotation, and thermal checks.

## Current Stage

This repository currently implements Stage 0 and Stage 1 only:

- Stage 0: repository setup, docs, guardrails, config example, requirements.
- Stage 1: core logic without UI, including config, SQLite, todos, notes, mood, deterministic messages, health, and tests.

Stage 2 weather fetching, Stage 3 full CLI coverage, Stage 4 web dashboard, and display work are intentionally not implemented yet.

## WSL Quick Start

```bash
cd /root/Project/jiri
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export PYTHONPATH=src
export JIRI_DISPLAY_DRIVER=mock
export JIRI_FULLSCREEN=false
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_DB_PATH=data/jiri_dev.db
pytest
python -m jiri.cli init-db
python -m jiri.cli todo add "Test JIRI" --due "2026-05-14 21:00"
python -m jiri.cli todo list
python -m jiri.cli health
```

Or run:

```bash
scripts/test_wsl.sh
```

## Raspberry Pi Direction

Do not start display integration until the earlier gates pass. On Pi, use:

```bash
export JIRI_DISPLAY_DRIVER=pygame
export JIRI_FULLSCREEN=true
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_DB_PATH=data/jiri.db
```

See `docs/PI_DEPLOYMENT.md`, `docs/STAGE_GATES.md`, and later stage checklists before deploying to hardware.

## Mission Control

Future work should start with `docs/MISSION_CONTROL.md`. It summarizes the main goal, current gate, Raspberry Pi 3B/3B+ constraints, safe parallel work lanes, immediate next tasks, and manual Pi confirmations.

## GitHub Sync

Initialize and push only when you are ready:

```bash
cd /root/Project/jiri
git init
git add .
git commit -m "Initialize JIRI Raspberry Pi assistant"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```
