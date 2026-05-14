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
- Stage B: WSL browser-driven Flask admin, todo/note CRUD, weather/location controls, JSON APIs, `/screen` preview.
- Stage C: Focus Assist core, CLI, web/API controls, no per-second SQLite writes.
- Stage D: WSL-safe display foundation, shared display view model, touch zones, critical face guardrails, mock-safe Pygame entrypoint.
- Stage E: AI worker benchmark scaffolding scripts and WSL safety tests.

Implemented but still hardware-gated:

- Stage D ASCII/touch display final acceptance requires real 3.5-inch display confirmation.
- Stage E AI worker benchmark final acceptance requires real Raspberry Pi 3B measurements.

Not yet implemented:

- Stage F AI integration. Blocked until Stage E passes on real hardware.
- Stage G Telegram admin.

## Active Build Order

Use the handbook build order from now on:

| Stage | Name | Status | Next Rule |
| --- | --- | --- | --- |
| A | Main App Stable | Passed in WSL | Keep hardening tests and CLI as needed. |
| B | Web Admin | Passed in WSL | Confirm response/RAM budgets on Pi later. |
| C | Focus Assist | Passed in WSL | No SQLite writes every second. |
| D | ASCII/Touch Display | Scaffolded in WSL | Needs Pi display/touch confirmation before acceptance. |
| E | AI Worker Benchmark | Scripts ready | Benchmark only, no claims before real Pi measurement. |
| F | AI Integration | Blocked | Only after benchmark passes. |
| G | Telegram Admin | Later | Polling first, whitelist users. |

## Immediate Next Engineering Task

Hardware confirmation and gate alignment before Stage F.

Scope:

- Run Stage D display/touch checks on the real Pi 3B+.
- Run Stage E AI baseline and Gemma benchmark scripts on the real Pi 3B.
- Keep WSL tests green while preparing Telegram/admin work.
- Do not implement AI integration until benchmark acceptance exists.

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
