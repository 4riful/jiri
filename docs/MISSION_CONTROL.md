# Mission Control

This document is the short operational control board for JIRI. The source-of-truth design document is `docs/ENGINEERING_HANDBOOK.md`.

## Current Rule

```text
JIRI is AI-assisted, not AI-controlled.
Python owns truth, timing, state, and actions.
Gemma owns wording, summaries, and personality.
```

## Current Product Direction

JIRI is now planned as a two-Pi desk companion:

- `jiri-main.local`: Raspberry Pi 3B+ body/controller/source of truth.
- `jiri-ai.local`: Raspberry Pi 3B AI/persona sidecar after benchmark acceptance.

The main Pi owns SQLite, todos, notes, focus sessions, weather cache, emotion rules, display state, touch confirmations, config, health, web dashboard, and later Telegram control.

The AI Pi may only rewrite, summarize, and add personality from facts supplied by Python. It must never own state, write SQLite, run shell commands, control systemd, mark todos done, change due dates, or be required for boot.

## Current Implementation Status

Implemented in code:

- Stage 0: repository setup and docs.
- Stage 1: config, SQLite schema, todos, notes, mood, deterministic messages, health, tests.
- Stage 2: Open-Meteo weather, Open-Meteo Geocoding location search, wttr.in fallback, SQLite weather cache, selected coordinates in settings.
- Stage 3: SSH-friendly CLI for init-db, todos, notes, location, weather, status, health.

Not yet implemented:

- Stage B Web Admin dashboard.
- Stage C Focus Assist.
- Stage D ASCII/touch display.
- Stage E AI worker benchmark.
- Stage F AI integration.
- Stage G Telegram admin.

## Active Build Order

Use the handbook build order from now on:

| Stage | Name | Status | Next Rule |
| --- | --- | --- | --- |
| A | Main App Stable | Mostly complete | Keep hardening tests and CLI as needed. |
| B | Web Admin | Next | Plain Flask/HTML only, no React/Node. |
| C | Focus Assist | Later | No SQLite writes every second. |
| D | ASCII/Touch Display | Later | Needs Pi display confirmation first. |
| E | AI Worker Benchmark | Later | Benchmark only, no claims before measurement. |
| F | AI Integration | Later | Only after benchmark passes. |
| G | Telegram Admin | Later | Polling first, whitelist users. |

## Immediate Next Engineering Task

Stage B: Web Admin.

Scope:

- Flask dashboard by IP.
- Todo CRUD.
- Notes CRUD.
- Weather location search/control.
- `/api/status`, `/api/todos`, `/api/weather`.
- Phone-friendly plain HTML/CSS.

Hard limits:

- No React.
- No Node.js.
- No CDN dependency required for core use.
- No browser kiosk as the 3.5-inch display UI.
- Web process RAM target below 100 MB, hard limit 150 MB.
- Local route targets below 500-800 ms as defined in the handbook.

## Critical Guardrails

- Do not optimize for WSL. Production target is Raspberry Pi 3B/3B+.
- Do not add heavy dependencies.
- Keep network requests out of the UI draw loop.
- Keep AI requests out of the UI render path.
- Do not geocode every weather refresh.
- Do not write SQLite every frame or every focus countdown tick.
- Do not implement Gemma as accepted. It is selected for benchmark only.
- Do not add AI worker code before the deterministic main app and relevant gates are stable.
- If hardware behavior is unknown, create a Pi confirmation checklist instead of guessing.

## Verification Commands

Always start future implementation sessions with:

```bash
cd /root/Project/jiri
scripts/test_wsl.sh
```

Weather/location manual smoke:

```bash
source .venv/bin/activate
export PYTHONPATH=src
python -m jiri.cli location search "panchagarh" --country BD
python -m jiri.cli location set 1
python -m jiri.cli location current
python -m jiri.cli weather test-providers
python -m jiri.cli weather refresh
```

## Pi Confirmation Still Needed

- Exact Pi 3B+ and Pi 3B OS versions.
- 32-bit vs 64-bit OS.
- Power supply stability.
- SD card health and free space.
- SSH hostnames/IPs.
- `vcgencmd get_throttled` results.
- Idle CPU temperatures.
- Free RAM after boot.
- Exact 3.5-inch display model, driver, framebuffer behavior, rotation, touch behavior.
- AI Pi Gemma benchmark measurements before acceptance.

Useful read-only Pi commands later:

```bash
cat /proc/device-tree/model
cat /etc/os-release
uname -a
free -h
df -h
vcgencmd measure_temp
vcgencmd get_throttled
```
