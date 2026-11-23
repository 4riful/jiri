# JIRI Engineering Handbook

The source-of-truth design and gate document (see `AGENTS.md`). It says what
JIRI must do and the rules it is held to. Companion documents:

| Document | Answers |
| --- | --- |
| `docs/ARCHITECTURE.md` | Which module and process does what, and where writes happen. |
| `docs/STATUS.md` | Which gates have passed, and what still needs the real Pi. |
| `docs/AI_SPEC.md` | The AI wording layer: invariants, buckets, voice policy, AI gates. |
| `docs/AI_STRATEGY.md` | Why no model runs on the Pi. Closed decision. |
| `docs/PERFORMANCE_BUDGETS.md` | The numbers. |
| `docs/HARDWARE.md`, `docs/PI_DISPLAY_CHECKLIST.md` | The board, the panel, and what is still unconfirmed. |
| `docs/SAFE_UPDATE_METHODOLOGY.md` | Backups, restores, updates. |

When a document disagrees with this one, this one wins; fix the other.

## Truth labels

| Label | Meaning |
| --- | --- |
| CONFIRMED | Backed by official documentation or by code and tests in this repo. |
| BENCHMARK REQUIRED | Must be measured on a real Raspberry Pi 3B/3B+ before acceptance. |
| DESIGN DECISION | A chosen rule. Changing it means changing this document first. |

## The rule everything follows

```text
JIRI is AI-assisted, not AI-controlled.
Python owns truth, timing, state, and actions.
Hosted AI owns wording only, in the background, from a cache.
```

## Product

JIRI is a small always-on desk companion on one Raspberry Pi 3B/3B+ (1 GB RAM)
with a 3.5-inch 480x320 SPI touch panel. It has:

- A face that reacts to real state and explains why (the display).
- Todos with polite escalation, notes, focus sessions, water tracking, weather.
- A usage screen for the owner's laptop AI tools (pushed over the LAN).
- A web admin by IP, a CLI over SSH, and an optional Telegram bot.
- Hosted-API wording for its voice, with cached and built-in fallbacks.

Development happens in WSL; production is Raspberry Pi OS. WSL results are
development evidence only. Nothing is tuned for desktop-class hardware.

## Hardware stance

- CONFIRMED: Pi 3B is 4x Cortex-A53 @ 1.2 GHz, Pi 3B+ is 4x Cortex-A53 @
  1.4 GHz; both have 1 GB RAM shared with the GPU.
- DESIGN DECISION: one Pi does everything. There is no second worker board.
- DESIGN DECISION: no model runs on the Pi (`docs/AI_STRATEGY.md`).
- BENCHMARK REQUIRED: panel controller, framebuffer, rotation, touch axes and
  redraw rate. Tracked in `docs/PI_DISPLAY_CHECKLIST.md`; do not guess.

## Display

DESIGN DECISION: the display is a living face and a glance panel, not the
admin dashboard. It is implemented once, in pygame (`src/jiri/ui/`). The web
`/screen` page is only a PNG preview from the same renderer.

### Screens

Six screens, rotated by `ui/stage.py`: `face` (home, 45 s), then `tasks`,
`weather`, `water`, `focus`, `usage` (15 s each). A double tap anywhere pauses
or resumes rotation. A single tap on the home screen pets JIRI.

The home screen is the face-clock: two eyes that show the hour and minutes
(the focus countdown while a session runs), a mouth, a reason line that names
the fact behind the expression, and a speech line.

### Motion has to mean something

DESIGN DECISION: nothing on the display moves unless something happened.

- The face state changes only when the state behind it changes.
- The reason line always names the fact that caused the current face.
- The speech line is seeded by a 15-minute window, so it does not re-roll
  every repaint.
- Idle motion is limited to breathing, blinking, gaze and the clock. Pet
  behaviours (`ui/pet.py`) come from drives that are caused by time, data or
  touch.
- A line must be true in every state that can reach it: JIRI never says
  "nothing to do" beside a counter reading two.

### Face states

The closed set is `ui/face.FACE_STATES`; `ui/mascot.py` must draw every one
(tested):

`idle`, `happy`, `alert`, `annoyed`, `angry`, `rage`, `sleeping`, `blink`,
`curious`, `smirk`, `focused`, `weather_hot`, `weather_rain`, `ai_offline`,
`system_warning`.

These names are the vocabulary. Docs, buckets and tests use them, not
synonyms such as "sleepy", "focus" or "task_done".

## Persona

`persona.screen_moment()` picks the one thing JIRI reacts to. Rows are checked
top to bottom and the first match wins; the priority number orders proactive
nudges, not this check. "Base" is `todos.calculate_mood()`, which is `idle`
whenever no task is late:

| Priority | Condition | Face | Category |
| ---: | --- | --- | --- |
| 90 | A task 120+ min late | `rage` | `todo_rage` |
| 80 | Focus session active | `focused` (base while paused) | `focus` |
| 70 | A task 30+ min late | `angry` | `todo_angry` |
| 70 | A task 10-29 min late | `annoyed` | `todo_annoyed` |
| 70 | A task 0-9 min late | `alert` | `todo_late` |
| 70 | A task due soon | `alert` | `todo_due_soon` |
| 50 | 34 C or hotter, 07:00-20:59 | `weather_hot` | `weather_hot` |
| 50 | Rain chance 70%+, 07:00-20:59 | `weather_rain` | `weather_rain` |
| 10 | Quiet hours | `sleeping` | `sleep` |
| 30 | 500+ ml of the water goal left, 09:00-21:59 | base | `water` |
| 40 | A task completed recently | `happy` | `celebrate` |
| 10 | Otherwise | base | `ambient` |

Minutes-late thresholds come from one table, `todos.OVERDUE_TABLE`
(0 -> level 1 `alert`, 10 -> 2 `annoyed`, 30 -> 3 `angry`, 60 -> 4 `angry`,
120 -> 5 `rage`). Nothing else may hard-code them.

Voice policy: playful and affectionate everywhere, including overdue tasks.
Escalation is theatrical, never meaner; the joke targets the situation or
JIRI, never the user. Full policy in `docs/AI_SPEC.md` §4a.

Proactive Telegram nudges reuse the same moments, rate-limited per category
and per task, allowlisted, and suppressed in quiet hours and during focus.

## AI wording layer

DESIGN DECISION, summarised from `docs/AI_SPEC.md`:

- Hosted, OpenAI-compatible providers in order: FreeLLMAPI (`qwen3.8-27b`),
  Gemini, Groq. A production install needs at least one working key.
- AI writes reusable lines and templates into `ai_cache` from a background
  worker in the web process. Requests carry only a category, a mood and a
  fixed style brief: no todo titles, notes, locations or any other user data.
- The render path is cache-only: `ai.pick()` is a SQLite SELECT. There is no
  live rewrite and no timeout on the render path, because there is no request.
- On a miss, JIRI speaks the built-in pools in `messages.py` / `quips.py`.
  A dead provider, a spent quota and an unplugged cable all look the same to
  the display: a cache miss.
- AI may never manage state, todos, reminders, due dates, focus timers,
  application data, weather facts or cache, system state, shell commands or
  systemd. It returns text; Python decides whether to store it.

## Data rules

- SQLite (`data/jiri.db`) is the only source of truth.
- The display path never writes SQLite (the single throttled exception is
  documented in `docs/ARCHITECTURE.md`) and never touches the network.
- Focus writes on start, pause, resume, complete, cancel and every
  `checkpoint_seconds` (default 60), never every second.
- Weather geocodes only when the user searches or sets a location. Refresh
  uses saved coordinates: Open-Meteo, then wttr.in, then the SQLite cache,
  then an honest "unavailable". Cached weather is labelled as cached.
- Back up SQLite (`scripts/backup_db.sh`) before any schema change once real
  data exists. Avoid noisy logs and frequent writes; the disk is an SD card.

## Control surfaces

- **Web admin** (`:5000/admin`): todo, note, focus, water, weather, persona,
  Telegram and AI pages; DB browser; update check. Login with
  `JIRI_ADMIN_PASSWORD`, CSRF on every write. Plain HTML/CSS, no frontend
  toolchain.
- **CLI** (`python -m jiri.cli`): todos, notes, focus, location, weather,
  status, health. Works over SSH with no display.
- **Telegram** (later-stage admin): long polling, no webhooks; allowlisted
  chat IDs only; unknown chats ignored; destructive commands need `/confirm`.
  Commands: `/todos`, `/todo`, `/notes`, `/note`, `/focus`, `/water`,
  `/weather`, `/status`, `/summary`, `/help`, `/confirm`, `/cancel`.
- **Usage push**: the laptop POSTs `/api/usage` with a bearer token.

## Dependencies

Flask, pygame, requests (and `tomli` below Python 3.11). No React, Node.js,
Electron, Docker, Kubernetes, PostgreSQL, MongoDB, Redis, Celery or browser
kiosk display. Every network request has a timeout.

## Failure handling

| Failure | Required behaviour |
| --- | --- |
| AI provider down, key missing, quota spent | Serve the cache, then built-in wording. No visible error. |
| Weather API fails | Serve the cached reading, marked as cached. |
| No weather cache | Show "unavailable". Never invent weather. |
| Database locked | Friendly error; the display keeps its last frame. |
| Touch driver missing | Display runs read-only; rotation continues. |
| Telegram offline | Core continues. |
| Web process crashes | Display and CLI continue; the face goes stale until the tick returns. |

## Acceptance gates

Every stage needs tests or a smoke check, and a stage is not done until its
gate passes. Current gate status is in `docs/STATUS.md`.

**Software gate (WSL/CI).** `scripts/test_wsl.sh` passes: the pytest suite
(no real network calls anywhere), the CLI walkthrough, and a headless pygame
run.

**Display gate (Pi, BENCHMARK REQUIRED).**
- Every item in `docs/PI_DISPLAY_CHECKLIST.md` is filled in.
- All six screens readable from about 1 m; every face state renders.
- Touch: tap pets, double tap pauses rotation, calibration correct.
- 10-15 FPS; idle frames cost no SPI writes.
- UI RSS under 250 MB, idle CPU under 30%, CPU temperature under 75 C.
- 30 minutes without a crash.

**Web gate (Pi, BENCHMARK REQUIRED).** `GET /api/status` and
`GET /admin/todos` under 500 ms, `POST /admin/todos` under 800 ms, web RSS
under 150 MB, usable from a phone by IP, survives weather being unavailable.

**AI gate.** `docs/AI_SPEC.md` §5: Gate 1 in WSL, Gate 2 with real keys,
Gate 3 on the Pi. No AI claim is accepted before Gate 3.

**Telegram gate.** `/todos` answers under 2 s, destructive commands need
confirmation, unknown chats are ignored, an internet outage does not crash
the core.

**Stability gate (Pi, last).** 24-hour soak with all services: no crash, no
unbounded growth in memory, database size or counters, fallbacks still work.

## Source references

- Raspberry Pi 3 Model B: https://www.raspberrypi.com/products/raspberry-pi-3-model-b/
- Raspberry Pi 3 Model B+: https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/
- Pygame events: https://www.pygame.org/docs/ref/event.html
- Telegram Bot API: https://core.telegram.org/bots/api
