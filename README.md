<p align="center">
  <img src="./jiri.png" alt="JIRI icon" width="180">
</p>

<h1 align="center">JIRI</h1>

<p align="center">
  A Raspberry Pi 3B/3B+ desk assistant built to be reliable first, lightweight second, funny third, and AI-enhanced only later.
</p>

<p align="center">
  <a href="https://github.com/4riful/jiri"><img alt="Repo" src="https://img.shields.io/badge/GitHub-4riful%2Fjiri-181717?logo=github"></a>
  <img alt="Target" src="https://img.shields.io/badge/Target-Raspberry%20Pi%203B%2B%20%2F%203B-c51a4a?logo=raspberrypi">
  <img alt="Runtime" src="https://img.shields.io/badge/Runtime-Python%203-3776ab?logo=python&logoColor=white">
  <img alt="Database" src="https://img.shields.io/badge/State-SQLite-003b57?logo=sqlite">
  <img alt="Frontend" src="https://img.shields.io/badge/Frontend-No%20React%20%2F%20No%20Node-2ea44f">
  <img alt="Stage" src="https://img.shields.io/badge/Stage-0%20%2B%201%20passed-blue">
</p>

## The Story

JIRI started as a hands-on lab revival project: an 8-year-old Raspberry Pi 3B+ and a Raspberry Pi 3B were sitting idle, waiting for a reason to boot again.

Instead of turning them into another overbuilt cloud-connected demo, this project aims to make them useful as a small Jarvis-style desk assistant that respects their limits. The Pi 3B+ is the main assistant. The Pi 3B may become an optional worker later. The goal is to get hands dirty again with real Raspberry Pi hardware: SSH, SQLite, Pygame, systemd, thermals, SD card safety, tiny displays, and all the practical constraints that make embedded projects fun.

JIRI is intentionally not a desktop app. It is not an Electron dashboard. It is not a React frontend strapped to a tiny board. It is a low-power Raspberry Pi assistant that should survive reboots, weak hardware, network failures, and long idle sessions.

## What JIRI Will Become

- Animated face on a 3.5-inch GPIO display.
- Clock and date always visible.
- Weather with SQLite cache and offline fallback.
- Todos with funny or angry reminder behavior.
- Shared notes.
- Phone/laptop web dashboard.
- SSH-friendly CLI.
- Optional worker Pi later.
- Optional tiny local LLM later, only as a personality rewrite layer.

## Design Philosophy

```text
Reliable first.
Lightweight second.
Funny third.
AI-enhanced only later.
```

Important state is deterministic:

- SQLite stores todos, notes, weather cache, settings, and event logs.
- Python business logic manages due dates, reminders, angry levels, health, and state transitions.
- The UI only displays small state snapshots.
- Weather has cache and fallback behavior.
- A future LLM may only rewrite messages in a funny style.
- A future LLM must never manage todos, reminders, due dates, database writes, weather cache, or system state.

## Target Hardware

Production target:

- Raspberry Pi 3B+ as the main assistant.
- Raspberry Pi 3B as an optional worker later.
- Raspberry Pi OS.
- 1GB RAM class hardware.
- 3.5-inch GPIO display on the Pi 3B+.
- Phone/laptop dashboard and SSH as control methods.
- No USB mic or speaker required for v1.

Hardware assumptions:

- ARM Cortex-A53 class CPU.
- No GPU compute.
- SD card storage, slower than SSD.
- Weak thermal headroom.
- Power instability is possible.
- Small 480x320 class display.

## Hard Limits

JIRI is designed around Raspberry Pi 3 limits, not desktop development hardware.

| Area | Target | Hard Limit |
| --- | ---: | ---: |
| UI idle RAM | under 180MB | 250MB |
| Web idle RAM | under 100MB | 150MB |
| Total non-LLM RAM | under 350MB | measure on Pi |
| CPU idle average | under 15% | 30% |
| UI FPS | 10 to 15 FPS | no high-FPS UI |
| Weather timeout | max 3s | fail to cache/fallback |
| Worker timeout | max 1s | worker optional |
| Local web API | under 500ms | keep handlers simple |
| Boot-to-ready | under 90s | systemd later |
| v1 database size | under 50MB | avoid noisy writes |

## What Is Explicitly Not Used In v1

- Electron.
- React.
- Node.js.
- Docker.
- Kubernetes.
- PostgreSQL.
- MongoDB.
- Redis.
- Celery.
- OpenAI API.
- Browser kiosk as the main Pi display UI.
- 7B LLMs.
- Continuous weather polling.
- Continuous database writes every frame.

## Stack

- Python 3.
- SQLite.
- Pygame for the future local display UI.
- Flask for the future phone dashboard.
- `requests` for weather fetching.
- TOML config.
- pytest.
- systemd service files later.

## Current Status

Current implemented level: Stage 0 and Stage 1.

| Gate | Status | Notes |
| --- | --- | --- |
| Stage 0 | Passed | Repo structure, docs, guardrails, config, requirements. |
| Stage 1 | Passed | Config, SQLite, todos, notes, mood, messages, health, tests. |
| Stage 2 | Next | Weather fetch/cache/fallback. |
| Stage 3+ | Blocked | Must pass earlier gates first. |

Stage 2 weather fetching, Stage 3 full CLI coverage, Stage 4 web dashboard, Pygame UI, Pi smoke tests, display confirmation, systemd installation, worker Pi, and LLM features are intentionally not implemented yet.

## Repository Layout

```text
jiri/
├── docs/                  Project architecture, gates, deployment notes
├── scripts/               WSL and Pi helper scripts
├── src/jiri/              Python package
│   ├── ui/                Future Pygame UI code
│   └── web/               Future Flask dashboard code
├── systemd/               Future service units
├── tests/                 WSL-safe pytest suite
├── AGENTS.md              Guardrails for future coding agents
├── config.example.toml    Safe example config
└── README.md              This file
```

## WSL Development

Development happens in WSL, but production decisions prioritize Raspberry Pi OS.

Recommended WSL setup:

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
export JIRI_WEATHER_FAKE=true
export JIRI_DB_PATH=data/jiri_dev.db
```

Run the full current WSL check:

```bash
scripts/test_wsl.sh
```

Manual CLI smoke path:

```bash
python -m jiri.cli init-db
python -m jiri.cli todo add "Test JIRI" --due "2026-05-14 21:00"
python -m jiri.cli todo list
python -m jiri.cli todo done 1
python -m jiri.cli health
```

## Raspberry Pi Direction

Do not start display integration until the earlier gates pass.

On Raspberry Pi later:

```bash
export JIRI_DISPLAY_DRIVER=pygame
export JIRI_FULLSCREEN=true
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_DB_PATH=data/jiri.db
```

Headless Pi work comes before display work. Display work comes before final fullscreen UI. AI work comes only after a 24-hour stability test.

## Mission Control

Future work should start with [`docs/MISSION_CONTROL.md`](docs/MISSION_CONTROL.md).

It summarizes:

- Main mission.
- Current gate.
- Raspberry Pi 3B/3B+ constraints.
- Safe parallel work lanes.
- Immediate next tasks.
- Manual Pi confirmations.
- Stop conditions for risky work.

## Next Engineering Task

Stage 2: weather with cache and fallback.

Expected scope:

- Fetch wttr.in JSON using `requests`.
- Timeout at 3 seconds or less.
- Cache last successful weather in SQLite.
- Refresh no more often than configured.
- Return stale cached weather if internet fails.
- Return a friendly unavailable state if no cache exists.
- Add mocked tests for success, timeout, invalid JSON, no internet, and cache fallback.

Do not add schedulers, background workers, async frameworks, UI calls, or Pi-only assumptions for Stage 2.

## GitHub

Repository:

```text
https://github.com/4riful/jiri
```

Normal update flow:

```bash
git status
git add .
git commit -m "Describe the change"
git push
```

## License

No license has been selected yet.
