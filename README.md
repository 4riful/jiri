<p align="center">
  <img src="jirie.png" alt="JIRI project image" width="220">
</p>

<h1 align="center">JIRI</h1>

<p align="center">
  <strong>A Raspberry Pi-first desk companion with a deterministic core, a small web cockpit, a living display face, and optional local AI wording.</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-89b4fa">
  <img alt="SQLite" src="https://img.shields.io/badge/storage-SQLite-a6e3a1">
  <img alt="Flask" src="https://img.shields.io/badge/web-Flask-cba6f7">
  <img alt="Pygame" src="https://img.shields.io/badge/display-Pygame-f9e2af">
  <img alt="Tests" src="https://img.shields.io/badge/tests-131%20passing-a6e3a1">
  <img alt="Target" src="https://img.shields.io/badge/target-Raspberry%20Pi%203B%2F3B%2B-f38ba8">
</p>

---

## What It Is

JIRI is a small personal desk assistant designed for weak, practical hardware: a Raspberry Pi 3B/3B+, 1 GB RAM, SQLite storage, and a compact display. It manages todos, notes, weather, focus sessions, hydration, persona nudges, Telegram control, and a read-only database browser from a lightweight Flask admin dashboard.

The project is deliberately not a cloud chatbot, not a kiosk website, and not a heavyweight home server stack. It is a deterministic Python application that can optionally use local AI later for wording only.

```text
AI-assisted, not AI-controlled.

Python owns truth, timing, state, safety rules, and actions.
Optional AI owns wording, summaries, and personality only.
```

## Why It Exists

Most “AI assistant” projects put the model in charge too early. JIRI does the opposite:

| Principle | What JIRI Does |
| --- | --- |
| Deterministic first | Todos, focus, weather, events, and persona rules work without AI. |
| Pi-first | Every feature is judged against Raspberry Pi 3B/3B+ constraints. |
| Local state | SQLite is the source of truth. No cloud database required. |
| Separate surfaces | Admin dashboard, screen preview, CLI, Telegram worker, and Pygame UI stay separate. |
| Safe AI boundary | AI cannot write SQLite, run commands, mark todos done, change due dates, or own state. |

## Current Status

| Area | Status | Notes |
| --- | --- | --- |
| Core SQLite app | Working | Todos, notes, settings, events, focus sessions, weather cache. |
| Admin dashboard | Working | Password-protected Flask UI on port `5000`. |
| Screen preview | Working | Separate web surface on port `5001`. |
| CLI | Working | SSH-friendly control path. |
| Weather | Working | Open-Meteo primary, wttr.in fallback, SQLite cache fallback. |
| Focus Assist | Working | Start, pause, resume, complete, cancel, no per-second DB writes. |
| Persona engine | Working | Deterministic priority/cooldown rules and Telegram nudges. |
| Telegram | Working | Polling bot, allowlist, commands, DB-backed settings. |
| DB browser | Working | Read-only raw SQLite inspection in admin. |
| Local AI | Scaffolded | `llama-server` integration is disabled by default and benchmark-gated. |
| Real Pi display | Hardware-gated | Needs final 3.5-inch display/touch confirmation. |

## System Map

```text
                         Browser / Phone
                               |
                               v
                  +---------------------------+
                  | Flask Admin :5000         |
                  | todos / notes / weather   |
                  | focus / telegram / db     |
                  +-------------+-------------+
                                |
                                v
+-------------+        +---------------------+        +------------------+
| Telegram    | <----> | JIRI Runtime        | <----> | Open-Meteo /     |
| polling     |        | deterministic core  |        | wttr.in weather  |
+-------------+        +----------+----------+        +------------------+
                                  |
                                  v
                         +----------------+
                         | SQLite         |
                         | source of truth|
                         +-------+--------+
                                 |
               +-----------------+-----------------+
               |                                   |
               v                                   v
     +--------------------+             +--------------------+
     | Screen Web :5001   |             | Pygame Display     |
     | display preview    |             | real Pi face UI    |
     +--------------------+             +--------------------+

Optional after benchmark:
JIRI Runtime -> local llama-server -> wording rewrite only -> deterministic fallback remains
```

## Features

### Admin Dashboard

Available at `http://127.0.0.1:5000/admin` during local development.

- Todos with due dates, priority, done/cancel/delete actions.
- Notes with tags.
- Weather location search, saved coordinates, refresh controls, current/hourly/daily forecast display.
- Focus sessions with pause/resume/complete/cancel controls.
- Water tracking and profile-based daily targets.
- Telegram binding, bot status, chat allowlist, token management.
- Persona settings for quiet hours, category cooldowns, and category toggles.
- AI status page with clean missing-binary handling for `llama-server`.
- Read-only DB browser for inspecting raw SQLite tables.

### Screen Surface

Available at `http://127.0.0.1:5001/screen` during local development.

- Glanceable face and headline.
- Panel rotation for weather, focus, todos, notes, and system state.
- Intended to mirror the 3.5-inch Pi display without becoming the admin dashboard.

### CLI

The CLI is designed for SSH and recovery work.

```bash
PYTHONPATH=src .venv/bin/python -m jiri.cli --help
PYTHONPATH=src .venv/bin/python -m jiri.cli todo add "Water the plants" --due "2026-05-16 18:00"
PYTHONPATH=src .venv/bin/python -m jiri.cli weather refresh
PYTHONPATH=src .venv/bin/python -m jiri.cli focus start --title "Deep work" --minutes 25
PYTHONPATH=src .venv/bin/python -m jiri.cli health
```

### Telegram

Telegram is an admin control surface, not the core system.

- Uses `getUpdates` polling.
- No public IP, webhook, router port-forward, or TLS certificate required.
- Allowed chat IDs are enforced.
- Settings are stored in SQLite and managed from `/admin/telegram`.
- Commands include `/status`, `/todos`, `/todo add`, `/todo done`, `/notes`, `/note add`, `/weather`, `/focus`, and `/water`.

### Persona Engine

JIRI has a deterministic personality layer. The display and Telegram worker can surface moments such as focus mode, overdue escalation, hydration reminders, weather tips, quiet hours, and ambient micro-expressions.

Priority order is intentionally explicit:

```text
critical overdue > focus > normal overdue > weather > quiet hours > water > ambient
```

The persona can be tuned in `/admin/persona` without changing code.

## Quick Start

### 1. Clone and enter the project

```bash
cd /root/Project/jiri
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 3. Run tests

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

Expected current result:

```text
131 passed
```

### 4. Start admin and screen surfaces

```bash
scripts/run_all.sh
```

Open:

| Surface | URL | Purpose |
| --- | --- | --- |
| Admin | `http://127.0.0.1:5000/admin` | Full dashboard and CRUD controls. |
| Screen | `http://127.0.0.1:5001/screen` | Display preview surface. |

Default development password:

```text
test
```

Override it with:

```bash
export JIRI_ADMIN_PASSWORD='choose-a-real-password'
```

### 5. Optional: run individual surfaces

```bash
scripts/run_admin.sh
scripts/run_screen.sh
scripts/run_telegram.sh
scripts/run_ui.sh
```

## Configuration

Copy the example config when you need persistent local settings:

```bash
cp config.example.toml config.toml
```

Important environment overrides:

| Variable | Purpose |
| --- | --- |
| `JIRI_DB_PATH` | SQLite database path. |
| `JIRI_DISPLAY_DRIVER` | `pygame` or `mock`. |
| `JIRI_WEB_HOST` | Flask bind host. |
| `JIRI_WEB_PORT` | Flask port for the active surface. |
| `JIRI_WEATHER_FAKE` | Deterministic fake weather for tests. |
| `JIRI_TELEGRAM_BOT_TOKEN` | First-boot Telegram token seed. |
| `JIRI_TELEGRAM_ALLOWED_CHAT_IDS` | First-boot Telegram allowlist seed. |
| `JIRI_LLM_SERVER_BINARY` | Full path or command name for `llama-server`. |
| `JIRI_LLM_MODEL_PATH` | Local GGUF model path. |
| `JIRI_LOCAL_DEV` | Explicit opt-in for local AI preflight scripts. |

## Local AI Notes

Local AI is optional and disabled by default. The admin AI page can show whether `llama-server` is available. If it is missing, JIRI now reports a clear setup message instead of exposing a raw `[Errno 2]` crash-style error.

To point JIRI at a custom llama.cpp server binary:

```bash
export JIRI_LLM_SERVER_BINARY=/path/to/llama-server
export JIRI_LLM_MODEL_PATH=/path/to/model.gguf
```

Production acceptance still requires a real Raspberry Pi benchmark. WSL/local runs are compatibility preflight only.

## Database Browser

The read-only DB browser is available at:

```text
http://127.0.0.1:5000/admin/db-browser
```

Use it to inspect what the app or previous agents stored in SQLite:

- `todos`
- `notes`
- `settings`
- `events_log`
- `focus_sessions`
- `weather_cache`

It does not write, delete, or mutate database rows.

## Project Layout

```text
.
├── config.example.toml          # documented configuration defaults
├── data/                        # local SQLite databases (ignored by git)
├── docs/                        # handbook, gates, deployment and troubleshooting docs
├── jirie.png                    # README/project image
├── scripts/                     # development, deployment, AI, and smoke scripts
├── src/jiri/                    # application package
│   ├── cli.py                   # SSH-friendly command line interface
│   ├── db.py                    # SQLite schema and helpers
│   ├── events.py                # idempotent event log
│   ├── focus.py                 # focus session state machine
│   ├── llama.py                 # optional llama-server control helpers
│   ├── persona.py               # deterministic persona engine
│   ├── runtime.py               # central orchestration object
│   ├── telegram.py              # Telegram polling bot
│   ├── todos.py / notes.py      # core personal data models
│   ├── weather.py / water.py    # weather and hydration systems
│   ├── ui/                      # Pygame display model and touch zones
│   └── web/                     # Flask app, templates, static CSS
├── systemd/                     # Raspberry Pi service files
└── tests/                       # pytest coverage for core, web, CLI, Telegram, UI
```

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/test_wsl.sh` | Main WSL test gate. |
| `scripts/run_all.sh` | Start admin and screen surfaces together. |
| `scripts/run_admin.sh` | Start admin surface only. |
| `scripts/run_screen.sh` | Start screen preview only. |
| `scripts/run_telegram.sh` | Start Telegram polling worker. |
| `scripts/run_ui.sh` | Start Pygame UI. |
| `scripts/backup_db.sh` | Back up SQLite database. |
| `scripts/install_pi.sh` | Raspberry Pi installation helper. |
| `scripts/pi_smoke_test.sh` | Pi deployment smoke test. |
| `scripts/ai_*.sh` | Local AI benchmark and monitoring helpers. |

## Testing

Run the full suite:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m pytest tests/ -q
```

Run the WSL gate:

```bash
scripts/test_wsl.sh
```

The suite covers:

- Config/env loading.
- SQLite schema and migration behavior.
- Todos, notes, focus, water, weather.
- Persona priority/cooldown rules.
- Event emission and deduplication.
- Telegram polling and command dispatch.
- Flask admin/screen/API surfaces.
- DB browser read-only inspection.
- Pygame display model and touch zones.
- AI script guardrails.

## Deployment Shape

Target hardware is a single Raspberry Pi 3B/3B+.

```text
Raspberry Pi OS
  -> Python virtualenv
  -> SQLite database
  -> Flask admin/screen services
  -> optional Pygame display service
  -> optional Telegram polling worker
  -> optional local llama-server after benchmark acceptance
```

Real hardware acceptance still needs:

- Exact 3.5-inch display model confirmation.
- Touch/rotation/framebuffer behavior confirmation.
- RAM/CPU/temperature measurements on the target Pi.
- Local Gemma benchmark before production AI integration claims.

## Troubleshooting

### `No module named jiri`

Set `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m jiri.cli health
```

### Admin password rejected

Default development password is `test`. Override with:

```bash
export JIRI_ADMIN_PASSWORD='your-password'
```

### `llama-server` not found

Install llama.cpp or set the binary path:

```bash
export JIRI_LLM_SERVER_BINARY=/path/to/llama-server
```

JIRI will continue working without AI.

### Weather unavailable

JIRI falls back in this order:

```text
Open-Meteo -> wttr.in -> SQLite cache -> unavailable message
```

### Ports already in use

Use alternate ports:

```bash
JIRI_ADMIN_PORT=5100 JIRI_SCREEN_PORT=5101 scripts/run_all.sh
```

## Design Boundaries

JIRI intentionally avoids:

- React / Node.js / Electron.
- Docker / Kubernetes.
- PostgreSQL / MongoDB / Redis / Celery.
- Browser kiosk as the Pi display UI.
- Cloud AI as a required dependency.
- AI-owned state or actions.

This keeps the project small enough to debug over SSH and realistic on Raspberry Pi 3B/3B+ hardware.

## Documentation

| Document | Purpose |
| --- | --- |
| `docs/ENGINEERING_HANDBOOK.md` | Source-of-truth engineering rules and gates. |
| `docs/ARCHITECTURE.md` | Layer overview and reliability rules. |
| `docs/MISSION_CONTROL.md` | Short operational status board. |
| `docs/STAGE_GATES.md` | Acceptance gates by stage. |
| `docs/ROADMAP.md` | Short progress tracker. |
| `docs/PI_DEPLOYMENT.md` | Raspberry Pi deployment notes. |
| `docs/TROUBLESHOOTING.md` | Common issues and fixes. |
| `docs/PERSONA_IMPLEMENTATION_PLAN.md` | Persona staged implementation plan. |

## License

No license has been selected yet. Treat the code as private unless a license file is added.
