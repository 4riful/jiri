# JIRI Methodology

JIRI is a Raspberry Pi-first desk assistant project. This repository is not organized around feature hype; it is organized around constraints, gates, and small reversible implementation steps.

The project target is weak hardware: Raspberry Pi 3B+/3B, 1GB RAM, SD-card storage, small display, unreliable network, and long idle runtime. Every implementation decision is judged against that environment even when development happens in WSL.

## Core Method

JIRI is built with this rule:

```text
AI-assisted, not AI-controlled.
Python owns truth, timing, state, and actions.
Optional AI owns wording only.
```

That means:

- SQLite is the source of truth.
- Python owns todos, notes, focus sessions, weather cache, location settings, display state, and safety rules.
- UI surfaces read snapshots; they do not become business logic owners.
- AI can rewrite or summarize Python-supplied facts only after benchmark gates pass.
- If AI is offline, slow, or rejected, deterministic Python behavior remains available.

## Design Constraints

The system is intentionally small.

Allowed stack:

- Python
- SQLite
- Flask
- Pygame
- `requests`
- pytest
- shell scripts for deployment/checks

Rejected for v1:

- React
- Node.js
- Electron
- Docker
- Kubernetes
- Redis
- Celery
- PostgreSQL
- MongoDB
- Browser kiosk as the Pi display
- Cloud AI dependency

This is not about purity. It is about keeping the system understandable, portable to old Pi hardware, and easy to debug over SSH.

## Surface Separation

JIRI has separate surfaces because they serve different jobs.

### Admin Surface

The admin surface is for human control.

- Runs on its own port.
- Requires password login.
- Manages todos, notes, weather location, weather refresh, and focus controls.
- Uses minimal terminal-style HTML/CSS.
- Must remain light enough for Pi hardware.

Default local route:

```text
http://127.0.0.1:5000/admin
```

Default dev password:

```text
test
```

### Screen Surface

The screen surface is a preview/simulator for the Pi display.

- Runs on a different port.
- Shows the face/display model.
- Does not expose admin pages.
- Does not become the admin dashboard.
- Mirrors what the small Pi display should care about: glanceable state, not full CRUD.

Default local route:

```text
http://127.0.0.1:5001/screen
```

This separation is intentional. A phone/laptop admin dashboard and a 3.5-inch Pi display are not the same product surface.

## Data Method

JIRI persists important state in SQLite.

State currently includes:

- Todos
- Notes
- Focus sessions
- Weather cache
- Selected weather location
- Recent weather locations
- Settings
- Events

Rules:

- No direct SQLite writes from render loops.
- No per-second focus countdown writes.
- No UI-owned truth.
- No AI-owned truth.
- Schema changes must stay simple and easy to reason about.
- Back up real Pi data before future migrations.

## Weather Method

Weather must be real-world and credible.

Provider model:

- Open-Meteo is primary.
- wttr.in is fallback.
- SQLite cache is final fallback.

Location model:

- Geocoding happens only when the user explicitly searches.
- Selected coordinates are saved.
- Refresh uses saved coordinates.
- Recent selected locations are saved and deduped.
- Refresh does not geocode automatically.

Dashboard method:

- Admin weather page shows current weather.
- Admin weather page shows hourly forecast from cached provider data.
- If provider fails, cached weather is shown with a clear message.

Testing note:

- Fake weather is allowed for deterministic automated tests only.
- Real dashboard checks should run with fake weather disabled.

## Focus Method

Focus Assist is stateful but low-write.

Rules:

- Start, pause, resume, complete, and cancel are explicit state transitions.
- Countdown can update visually every second.
- SQLite writes happen on transitions/checkpoints, not every tick.
- Display and dashboard read snapshots of focus state.

## AI Method

AI is not part of the trusted core.

Current AI status:

- Local Gemma ctx512 preflight is allowed in WSL.
- Raspberry Pi acceptance is not complete.
- Production AI integration remains blocked until real Pi benchmark acceptance.

AI is allowed to do later:

- Rewrite short messages.
- Summarize todos or notes from Python-supplied facts.
- Add personality to deterministic state.
- Produce weather commentary from API facts.

AI must never:

- Write SQLite.
- Mark todos done.
- Change due dates.
- Start or stop focus timers.
- Decide weather facts.
- Run shell commands.
- Control systemd.
- Become required for boot.

Benchmark method:

- Default context target is 512.
- Short outputs only.
- Strict timeouts.
- Fallback templates always remain.
- WSL results are development evidence only.
- Real Raspberry Pi 3B measurements decide acceptance.

## Build Gates

Work moves through gates, not vibes.

Current gate status:

| Area | Status | Acceptance Notes |
| --- | --- | --- |
| Core app | Passed in WSL | Config, SQLite, todos, notes, health, CLI. |
| Weather/location | Passed in WSL | Real provider path exists; tests mock network. |
| Web admin | Passed in WSL | Admin and screen surfaces are split. |
| Focus Assist | Passed in WSL | No per-second DB writes. |
| Display foundation | Scaffolded | Needs real Pi display/touch confirmation. |
| AI worker benchmark | Local preflight only | Needs real Pi 3B benchmark. |
| AI integration | Blocked for production | Depends on benchmark acceptance. |
| Telegram | Not started | Later admin surface. |

No stage is accepted from WSL when the gate requires hardware.

## Development Method

The development loop is:

1. Keep changes small.
2. Preserve Pi constraints.
3. Update tests with behavior.
4. Run WSL gate.
5. Do not claim hardware acceptance until hardware is tested.

Primary local gate:

```bash
scripts/test_wsl.sh
```

Latest known WSL gate in this workspace:

```text
71 passed
```

Run surfaces locally:

```bash
scripts/run_admin.sh
scripts/run_screen.sh
```

Admin password can be changed with:

```bash
export JIRI_ADMIN_PASSWORD='change-this'
```

## Raspberry Pi Method

Production target:

- `jiri-main.local`: Raspberry Pi 3B+ main controller.
- `jiri-ai.local`: Raspberry Pi 3B optional AI sidecar after benchmark acceptance.

Main Pi owns:

- SQLite
- CLI
- Admin dashboard
- Screen/display state
- Weather cache
- Focus/todo/note state
- Health checks
- Later Telegram control

AI Pi, if accepted later, owns only:

- llama-server
- Message rewriting
- Summaries
- AI health/benchmark scripts

Hardware gates still required:

- Confirm real display resolution, rotation, framebuffer, and touch behavior.
- Confirm UI RAM/CPU/temperature on Pi.
- Confirm Gemma load, RAM, swap, temperature, latency, SSH responsiveness, and fallback behavior on Pi 3B.

## Repository Structure

```text
docs/                  Methodology, gates, deployment notes
scripts/               Dev, WSL, Pi, and AI helper scripts
src/jiri/              Application package
src/jiri/web/          Flask admin and screen surfaces
src/jiri/ui/           Display view model and Pygame entrypoint
tests/                 WSL-safe automated tests
systemd/               Future service units
config.example.toml    Example runtime configuration
AGENTS.md              Mandatory rules for coding agents
```

## Source Documents

- `docs/ENGINEERING_HANDBOOK.md`: source-of-truth architecture and gate document.
- `docs/MISSION_CONTROL.md`: current operating state.
- `docs/STAGE_GATES.md`: acceptance gates.
- `docs/WSL_DEVELOPMENT.md`: WSL workflow.
- `AGENTS.md`: implementation guardrails.

## License

No license has been selected yet.
