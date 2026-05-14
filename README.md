<p align="center">
  <img src="./jirie.png" alt="JIRI icon" width="180">
</p>

<h1 align="center">JIRI</h1>

<p align="center">
  A two-Pi AI-assisted Raspberry Pi desk companion built to be reliable first, lightweight second, funny third, and AI-controlled never.
</p>

<p align="center">
  <a href="https://github.com/4riful/jiri"><img alt="Repo" src="https://img.shields.io/badge/GitHub-4riful%2Fjiri-181717?logo=github"></a>
  <img alt="Target" src="https://img.shields.io/badge/Target-Raspberry%20Pi%203B%2B%20%2F%203B-c51a4a?logo=raspberrypi">
  <img alt="Runtime" src="https://img.shields.io/badge/Runtime-Python%203-3776ab?logo=python&logoColor=white">
  <img alt="Database" src="https://img.shields.io/badge/State-SQLite-003b57?logo=sqlite">
  <img alt="Frontend" src="https://img.shields.io/badge/Frontend-No%20React%20%2F%20No%20Node-2ea44f">
  <img alt="Stage" src="https://img.shields.io/badge/Stage-0%20to%203%20passed-blue">
</p>

## The Story

JIRI started as a hands-on lab revival project: an 8-year-old Raspberry Pi 3B+ and a Raspberry Pi 3B were sitting idle, waiting for a reason to boot again.

Instead of turning them into another overbuilt cloud-connected demo, this project aims to make them useful as a small Jarvis-style desk assistant that respects their limits. The Pi 3B+ is the main assistant. The Pi 3B may become an optional worker later. The goal is to get hands dirty again with real Raspberry Pi hardware: SSH, SQLite, Pygame, systemd, thermals, SD card safety, tiny displays, and all the practical constraints that make embedded projects fun.

JIRI is intentionally not a desktop app. It is not an Electron dashboard. It is not a React frontend strapped to a tiny board. It is a low-power Raspberry Pi assistant that should survive reboots, weak hardware, network failures, and long idle sessions.

## What JIRI Will Become

- Persistent ASCII/Unicode face on a 3.5-inch touch display.
- Clock/date and glance panel.
- Weather with Open-Meteo, location search, SQLite cache, and wttr.in fallback.
- Todos with funny or angry reminder behavior.
- Shared notes.
- Focus countdown timer with countdown eyes.
- Phone/laptop web dashboard.
- SSH-friendly CLI.
- Later Telegram admin control.
- Dedicated AI sidecar on Raspberry Pi 3B after benchmark acceptance.

## Design Philosophy

```text
Reliable first.
Lightweight second.
Funny third.
AI-assisted only after benchmark gates.
AI-controlled never.
```

Important state is deterministic:

- SQLite stores todos, notes, weather cache, settings, and event logs.
- Python business logic manages due dates, reminders, angry levels, health, and state transitions.
- The UI only displays small state snapshots.
- Weather has cache and fallback behavior.
- Gemma may only rewrite/summarize from Python-supplied facts after AI worker benchmark acceptance.
- Gemma must never manage todos, reminders, due dates, focus timers, database writes, weather facts, weather cache, system state, shell commands, or systemd.

## Source Of Truth

The source-of-truth architecture and gate document is [`docs/ENGINEERING_HANDBOOK.md`](docs/ENGINEERING_HANDBOOK.md).

Core rule:

```text
JIRI is AI-assisted, not AI-controlled.
Python owns truth, timing, state, and actions.
Gemma owns wording, summaries, and personality.
```

## Target Hardware

Production target:

- Raspberry Pi 3B+ as `jiri-main.local`, the body/controller/source of truth.
- Raspberry Pi 3B as `jiri-ai.local`, the AI/persona sidecar after benchmark acceptance.
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

Current implemented level: Stage 0 through Stage 3.

| Gate | Status | Notes |
| --- | --- | --- |
| Stage 0 | Passed | Repo structure, docs, guardrails, config, requirements. |
| Stage 1 | Passed | Config, SQLite, todos, notes, mood, messages, health, tests. |
| Stage 2 | Passed | Open-Meteo weather, location search, wttr fallback, SQLite cache. |
| Stage 3 | Passed | SSH-friendly CLI for init-db, todos, notes, location, weather, status, and health. |
| Stage A | Mostly complete | Main app stable: todos, notes, weather/location, CLI, tests. |
| Stage B | Next | Web Admin: Flask dashboard by IP, plain HTML/CSS, no heavy frontend. |
| Stage C+ | Blocked | Focus, display, AI benchmark, AI integration, Telegram happen later. |

Web Admin, Focus Assist, ASCII/touch display, Pi smoke tests, display confirmation, AI worker benchmark, AI integration, Telegram, and production systemd installation are intentionally not implemented yet.

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
export JIRI_WEATHER_LOCATION=auto
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
python -m jiri.cli note add "Lab note" --body "Pi revival project."
python -m jiri.cli note list
python -m jiri.cli weather refresh
python -m jiri.cli status
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

For full architecture and gates, read [`docs/ENGINEERING_HANDBOOK.md`](docs/ENGINEERING_HANDBOOK.md).

## Weather CLI

Weather uses Open-Meteo as the primary provider with Open-Meteo Geocoding for location search. wttr.in is retained only as a fallback provider if Open-Meteo weather fetch fails.

Normal weather refresh uses saved latitude/longitude from SQLite settings or config. It does not geocode automatically. This avoids repeated network calls and keeps the Pi 3B+ predictable.

Search and select a place:

```bash
python -m jiri.cli location search "panchagarh" --country BD
python -m jiri.cli location set 1
python -m jiri.cli location current
python -m jiri.cli weather refresh
```

Set coordinates directly:

```bash
python -m jiri.cli location set-coords --name "Home" --lat 26.1167 --lon 88.85
python -m jiri.cli location current
python -m jiri.cli weather refresh
```

Manual provider diagnostic:

```bash
python -m jiri.cli weather test-providers
```

`weather test-providers` may use real internet. Automated tests mock provider requests and do not require internet.

## Next Engineering Task

Stage B: Web Admin.

Expected scope:

- Plain HTML/CSS only.
- Phone-friendly todo and note management.
- Weather location search and selection.
- Local JSON status APIs.
- No React, Node.js, CDN dependency, or heavy frontend tooling.

Do not start UI, Pygame, Pi display, AI worker, Gemma, Telegram, or systemd installation work for Stage B.

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
