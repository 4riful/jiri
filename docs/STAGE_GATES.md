# Stage Gates

`docs/ENGINEERING_HANDBOOK.md` is the source-of-truth gate document. This file summarizes acceptance gates for implementation work.

## Completed Gates

### Stage 0: Planning And Repo Setup

Status: passed.

Pass condition:

- Repository structure exists.
- README explains WSL and Pi deployment split.
- `AGENTS.md` contains guardrails.

### Stage 1: Core Logic, No UI

Status: passed.

Pass condition:

- Pytest passes on WSL.
- CLI can add/list/done todos.
- Database can be deleted and recreated safely.

### Stage 2: Weather And Location

Status: passed.

Pass condition:

- Open-Meteo weather tests pass with mocked network calls.
- Open-Meteo Geocoding search works only on explicit command.
- Selected coordinates are saved in SQLite settings.
- Weather refresh never geocodes automatically.
- wttr.in fallback and SQLite cache fallback work.
- No-cache unavailable state is friendly and non-crashing.

### Stage 3: CLI

Status: passed.

Pass condition:

- CLI can manage todos and notes without UI.
- CLI can search/set/current weather location.
- CLI weather refresh uses selected coordinates.
- Invalid dates, empty titles, bad coordinates, and invalid location indexes are rejected clearly.
- CLI works in WSL and SSH-style terminal output remains readable.

## Current Build Order

### Stage A: Main App Stable

Status: passed in WSL.

Pass condition:

- Todos, notes, weather, location search, and CLI all work together.
- Weather refresh uses saved coordinates and does not geocode every refresh.
- Open-Meteo primary and wttr.in fallback behavior are covered by tests.
- WSL tests pass.

### Stage B: Web Admin

Status: passed in WSL. Pi response/RAM confirmation still required.

Pass condition:

- Flask dashboard runs locally and on Pi by IP.
- Admin dashboard and screen preview use distinct ports/surfaces.
- Todo CRUD works from phone browser.
- Notes CRUD works from phone browser.
- Weather location search/set/current works from dashboard.
- `/api/status` responds below 500 ms locally.
- `GET /admin/todos` responds below 500 ms locally after admin login.
- `POST /admin/todos` responds below 800 ms locally after admin login.
- Web process RAM target below 100 MB, hard limit 150 MB.
- No React, Node, Electron, browser kiosk, CDN-required core behavior, or heavy frontend toolchain.
- Web survives weather unavailable.

### Stage C: Focus Assist

Status: passed in WSL.

- Focus timer start/pause/resume/complete/cancel.
- Optional todo link.
- No SQLite writes every second.
- Checkpoint writes only on state changes or configured interval.
- Focus milestones emitted once.

### Stage D: ASCII/Touch Display

Status: scaffolded in WSL. Real display/touch acceptance still required.

- Actual display resolution or 480x320 fallback renders.
- Face remains visible.
- Right panel readable.
- Touch zones work.
- Critical emotion cannot be overridden by touch.
- Focus countdown eyes update once per second.
- Typed mouth message works.
- UI runs 30 minutes without crash.
- Confirm real display behavior on Raspberry Pi before finalizing the UI.

### Stage P: Persona And Proactive Behavior

Status: P0/P1 implemented in WSL. P2-P5 remain planned or hardware/AI blocked.

- Deterministic persona engine follows handbook priority order.
- Screen persona decisions do not write SQLite.
- Proactive Telegram nudges are rate-limited and allowlisted.
- Quiet hours suppress low-priority proactive messages.
- Focus suppresses random idle chatter.
- Per-task overdue cooldowns prevent one task from silencing another.
- Typed mouth effect and real display acceptance remain Stage D/P3 hardware work.
- AI rewrite remains blocked until Stage E and Stage F acceptance.

### Stage E: Local AI Benchmark

Status: scripts ready. Real Raspberry Pi 3B benchmark still required.

WSL/local Gemma ctx512 runs are allowed only as opt-in compatibility preflight. They do not satisfy this gate.

- Gemma 3 270M Q4_K_M loads on real Pi 3B.
- Free RAM after load above 150 MB.
- Swap after idle load below 100 MB.
- CPU temp after 10 minutes below 75 C.
- Short rewrite below 8 seconds.
- Summary below 15 seconds.
- SSH remains responsive.
- JIRI works if local AI is offline.
- Benchmark on a real Raspberry Pi 3B, not WSL.

### Stage F: AI Integration

Status: blocked for production acceptance until Stage E passes on real Raspberry Pi 3B. Local development must stay disabled by default, timeout-protected, fallback-safe, and Pi-compatible.

- AI requests run outside render path.
- Fallback templates remain immediate.
- AI cannot write SQLite or control actions.
- AI timeout keeps deterministic fallback message.

### Stage G: Telegram Admin

- Polling bot works without public IP.
- Unknown users ignored.
- Destructive actions require confirmation.
- Internet outage does not crash JIRI core.
- Telegram stays later-stage admin control, not a primary control path.
