# Mission Control

This document is the working control board for JIRI. Use it at the start of future coding sessions to keep the project practical, parallelizable, and safe for old Raspberry Pi 3 hardware.

## Main Goal

Build JIRI as a small Jarvis-style desk assistant for an 8-year-old Raspberry Pi 3B+ and optional Pi 3B that were sitting idle in the lab.

The goal is not to build a desktop app or a cloud AI demo. The goal is to get hands dirty again with real Raspberry Pi hardware while making something reliable, useful, funny, and hackable.

JIRI should eventually provide:

- Animated face on a 3.5-inch GPIO display.
- Clock and date.
- Weather with cache and offline fallback.
- Todos and shared notes.
- Funny or angry reminder behavior.
- Phone/laptop web dashboard.
- CLI over SSH.
- Optional worker Pi later.
- Optional tiny LLM later, only as a personality rewrite layer.

## Hardware Reality

The production target is Raspberry Pi 3B/3B+, not the WSL development machine.

Assume:

- 1GB RAM total.
- ARM Cortex-A53 class CPU.
- Slow SD card storage.
- Weak thermal headroom.
- Power instability is possible.
- No GPU compute.
- Small 480x320 class GPIO display.

This means future work must prefer boring, deterministic, low-write, low-RAM Python over heavy frameworks.

## Non-Negotiable Rules

- Reliable first.
- Lightweight second.
- Funny third.
- AI-enhanced only after the deterministic assistant survives a 24-hour stability test.
- SQLite owns important state.
- Deterministic Python code manages todos, reminders, due dates, weather cache, health, and system state.
- LLMs must never manage state, write the database, decide due dates, or become required for core behavior.
- No React, Electron, Node.js, Docker, Kubernetes, Redis, Celery, PostgreSQL, MongoDB, or browser kiosk display UI in v1.
- No network requests in the UI draw loop.
- No database writes in the UI draw loop.
- No display assumptions in WSL.
- No Pi display work until the real display is identified and confirmed.

## Current Progress

Current implemented level: Stage 0 and Stage 1.

Completed:

- Repository structure.
- Guardrails in `AGENTS.md`.
- WSL/Pi split in docs.
- TOML config defaults and environment overrides.
- SQLite schema.
- Todo logic.
- Note logic.
- Mood calculation.
- Deterministic funny messages.
- Health snapshot and CLI health output.
- WSL-safe pytest coverage.
- WSL helper script.

Not implemented yet:

- Real weather fetch/cache/fallback behavior.
- Full CLI test coverage for every command.
- Real Flask dashboard.
- Pygame mock UI.
- Pi smoke confirmation.
- 3.5-inch display confirmation.
- Production fullscreen UI.
- systemd installation flow.
- 24-hour stability test.
- Worker Pi.
- LLM personality layer.

## Gate Status

- Gate 0: passed.
- Gate 1: passed.
- Gate 2: next.
- Gate 3 and later: blocked until previous gates pass.

Last known WSL verification:

```bash
cd /root/Project/jiri
scripts/test_wsl.sh
```

Expected result at this point: pytest passes and CLI smoke add/list/done/health works in mock-display mode.

## Agentic Work Style

Future sessions should work in parallel only where the lanes are independent.

Good parallel lanes:

- One agent audits docs and gate status.
- One agent inspects tests and missing coverage.
- One agent designs the smallest implementation for the next stage.
- One agent checks Raspberry Pi constraints and possible budget risks.

Do not parallelize conflicting edits to the same files unless one agent is explicitly read-only.

Do not let an agent skip gates because later tasks look more exciting. Display and AI work are intentionally delayed.

## Active Parallel Lanes

Lane A: WSL deterministic core

- Config.
- SQLite.
- Todos.
- Notes.
- Mood.
- Messages.
- Weather parsing/cache/fallback.
- CLI.
- Unit tests.

Lane B: Phone and SSH control

- CLI first.
- Flask dashboard after Stage 3.
- Plain HTML and CSS only.
- No frontend build chain.

Lane C: Raspberry Pi readiness

- Headless smoke test.
- RAM, temperature, disk, and network checks.
- systemd service design, not auto-installation.
- Manual confirmation before reboot/service changes.

Lane D: Display path

- Wait until headless Pi passes.
- Identify exact 3.5-inch display model.
- Confirm framebuffer/driver/orientation.
- Run a standalone Pygame display test before integrating UI.

Lane E: Personality layer

- Deterministic funny messages now.
- Optional tiny LLM only after Stage 10.
- LLM disabled by default forever unless explicitly enabled and measured.

## Immediate Next Task

Next coding stage: Stage 2, weather with cache and fallback.

Implement only after confirming Stage 1 still passes.

Stage 2 scope:

- Fetch weather from wttr.in JSON using `requests`.
- Enforce max 3 second timeout.
- Store the last successful response in SQLite `weather_cache`.
- Refresh only when cache is missing or stale according to `refresh_minutes`.
- Return cached weather if network fails.
- Return friendly unavailable state if no cache exists.
- Add mocked tests for success, timeout, invalid JSON, no internet, and cached fallback.

Stage 2 must not add:

- Background schedulers.
- Continuous polling.
- Async framework.
- Extra weather dependency.
- UI calls.
- Any Pi-only assumption.

## Next Brief For Future Agent

Start with:

```bash
cd /root/Project/jiri
scripts/test_wsl.sh
```

If Stage 1 still passes, implement Stage 2 in these files:

- `src/jiri/weather.py`
- `tests/test_weather.py`

Potentially update:

- `src/jiri/cli.py` only if `weather refresh` needs explicit behavior changes.
- `docs/STAGE_GATES.md` only after Stage 2 tests pass.

Do not edit UI, web dashboard, systemd, or Pi display files for Stage 2.

## Manual Pi Confirmation Needed Later

Before Pi-specific work, manually confirm:

- Exact model: Pi 3B or Pi 3B+.
- Raspberry Pi OS version.
- 32-bit or 64-bit OS.
- Power supply rating and stability.
- SD card size and free space.
- SSH username and hostname/IP.
- Network stability.
- `vcgencmd get_throttled` result if available.
- Idle CPU temperature.
- Free RAM after boot.
- Exact 3.5-inch display model.
- Display driver installation method.
- Whether the display appears as framebuffer.
- Rotation and resolution.

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

Run those on the Pi over SSH, not in WSL unless intentionally checking WSL.

## Stop Conditions

Stop and ask before proceeding if:

- A change risks exceeding Pi 3B+ memory or CPU budgets.
- A task requires `sudo` on the Pi.
- A task changes boot, display drivers, framebuffer, systemd enablement, or networking.
- A task would add a heavy dependency.
- Tests fail and the fix is not obvious.
- Hardware behavior is unknown.
