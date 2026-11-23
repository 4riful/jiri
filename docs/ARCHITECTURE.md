# Architecture

How JIRI is put together today. Rules and behaviour live in
`docs/ENGINEERING_HANDBOOK.md`; what is accepted and what still needs the Pi
lives in `docs/STATUS.md`.

## One sentence

Python owns every fact and every write in SQLite; a pygame process draws the
face from read-only snapshots; one web process serves the admin and runs the
only background workers; hosted AI only ever fills a wording cache.

## Process model

Production runs two systemd services on one Raspberry Pi 3B/3B+. Telegram is
an optional third process.

| Process | Entry point | Unit / script | Reads | Writes |
| --- | --- | --- | --- | --- |
| Display | `python -m jiri.ui.pygame_app` | `jiri-ui.service`, `scripts/run_ui.sh` | snapshot once a second | nothing (one exception, below) |
| Web | `python -m jiri.web.app` | `jiri-web.service`, `scripts/run_admin.sh`, `scripts/run_all.sh` | everything | admin actions, background tick, AI cache, usage pushes |
| Telegram (optional) | `python -m jiri.telegram poll` | `scripts/run_telegram.sh` | everything | whitelisted chat commands, update offset |
| CLI (on demand) | `python -m jiri.cli ...` | SSH | everything | the command you ran |

The web process owns two daemon threads, started by
`jiri.ai_worker.start_background()` from `jiri.web.app.main()`. They are never
started by the `screen` surface, by tests, or by the display process:

- **Minute tick**, `runtime.tick_background()` every 60 s: weather refresh
  (network, 3 s timeout, at most once per refresh window), retiring finished
  focus sessions, the water day rollover, and one-time persona events.
- **AI refill**, `runtime.ai_refill()` every `ai.refill_interval_minutes`
  (default 10, 0 disables): asks hosted providers for new lines for the
  buckets the display missed.

### Web surfaces

`JIRI_WEB_SURFACE` decides what one Flask process serves.

| Surface | Serves | Login | Typical bind |
| --- | --- | --- | --- |
| `all` (default, production) | admin, APIs, `/screen` preview | required for everything private | `0.0.0.0:5000` |
| `admin` (dev) | admin and APIs, no `/screen` | required | `0.0.0.0:5000` |
| `screen` (dev) | `/screen`, `/screen.png`, read-only APIs | none | `127.0.0.1:5001` only |

`scripts/run_all.sh` starts `admin` and `screen` side by side for WSL work.

## Data flow

```text
  phone / laptop          Telegram             laptop (usage push)
        |                     |                        |
        v                     v                        v
 +----------------------------------------------------------------+
 |  WEB PROCESS  (jiri.web.app)                                   |
 |   admin routes --+   /api/usage --+   [telegram process] --+   |
 |                  |                |                        |   |
 |   worker: minute tick --------+   |   worker: AI refill    |   |
 |     weather (Open-Meteo,      |   |     FreeLLM -> Gemini  |   |
 |     wttr.in), focus, water,   |   |     -> Groq (15 s)     |   |
 |     persona events            |   |          |             |   |
 +------------------|------------|---|----------|-------------|---+
                    v            v   v          v             v
              +------------------------------------------------+
              |  SQLite  data/jiri.db   (the only source of     |
              |  truth: todos, notes, focus, water, weather     |
              |  cache, settings, events, ai_cache, usage)      |
              +------------------------------------------------+
                                  |  read-only
                                  v
        runtime.screen_snapshot(read_only=True)  -> views.ScreenSnapshot
                                  |
         +------------------------+-------------------------+
         v                                                  v
 DISPLAY PROCESS (jiri.ui.pygame_app)              /screen.png (web)
   renderer.build_scene -> stage -> pet -> pages     same renderer,
   -> mascot face -> output (SDL window or           one PNG per request
      /dev/fbN RGB565 dirty bands + evdev touch)
```

## The read-only render path

`views.build_screen_snapshot(read_only=True)` assembles the face state, the
reason line, the speech line and every glance number from SQLite and nothing
else. On that path:

- No network. Weather comes from the cache the tick wrote. The AI voice comes
  from `ai.pick()`, a SQLite SELECT.
- No SQLite writes, with one bounded exception: when `ai.pick()` misses an
  empty bucket it records demand in `ai_wanted`, at most once per bucket per
  10 minutes per process. That is how the refill worker learns what to write.
- No timers that change state. A focus session reaching 00:00 is retired by the
  tick, not by the display.

`tests/test_display_readonly.py` enforces this: it makes every network call
and every SQLite write raise, then renders.

## Module map

### Core (`src/jiri/`)

| Module | Job |
| --- | --- |
| `config.py` | Defaults, `config.toml`, `.env` loader, environment overrides, validation. |
| `db.py` | SQLite connection, schema and migrations, settings helpers. |
| `models.py` | Shared dataclasses (`Todo`, `Note`, ...). |
| `runtime.py` | `JiriRuntime`: the one facade CLI, web, Telegram and display call. |
| `todos.py` | Todo lifecycle; `OVERDUE_TABLE` maps minutes late to angry level and mood. |
| `notes.py`, `water.py`, `focus.py` | Notes; hydration goal and history; focus sessions with checkpoint writes. |
| `weather.py` | Open-Meteo, wttr.in fallback, SQLite cache, explicit-only geocoding. |
| `persona.py` | Decides what JIRI reacts to (`PersonaMoment`) by fixed priority. |
| `persona_settings.py` | Quiet hours and proactive-nudge settings. |
| `messages.py` | Built-in wording pools, the deterministic floor under the AI voice. |
| `quips.py` | Offline fallback quips for the home screen's "thoughts". |
| `views.py` | Builds `ScreenSnapshot` (display) and dashboard snapshots (web). |
| `events.py` | One-time event log (milestones, celebrations), deduplicated. |
| `ai.py` | Hosted-provider client, sanitizer, caps, breaker, `ai_cache`, `pick()`. |
| `ai_worker.py` | The two background loops in the web process. |
| `usage.py` | Validates and stores laptop AI-usage pushes for the usage screen. |
| `telegram.py` | Polling bot: allowlist, commands, confirmations, proactive nudges. |
| `health.py`, `system_info.py` | Health checks; RAM, temperature, disk. |
| `update_checker.py` | Read-only "is there a newer commit" check. |
| `cli.py` | SSH-friendly command line. |

### Display (`src/jiri/ui/`)

| Module | Job |
| --- | --- |
| `pygame_app.py` | The loop: snapshot once a second, frame at 10-15 FPS. |
| `renderer.py` | `Scene` from a snapshot; fonts loaded once; usage gauges; PNG preview. |
| `stage.py` | Touch routing, screen rotation, splash transitions, home "thoughts". |
| `pet.py` | Pet brain: drives -> behaviours -> spring physics. In memory only. |
| `pages.py` | The screens: `face`, `tasks`, `weather`, `water`, `focus`, `usage`. |
| `mascot.py` | The face: two eyes that are also the clock (countdown during focus). |
| `output.py` | SDL window, or direct SPI framebuffer writer with evdev touch. |
| `face.py` | `FACE_STATES`, the closed set of moods persona may produce. |

### Web (`src/jiri/web/`)

`app.py` is the Flask app (login, CSRF, surfaces, routes, JSON APIs, worker
start-up). `templates/` holds the admin pages and the `/screen` preview page,
which only shows `/screen.png`. `static/style.css` styles the admin.

## Where writes happen

| Writer | Tables |
| --- | --- |
| Admin routes, CLI, Telegram commands | todos, notes, focus, water, settings, location |
| Minute tick (web worker) | weather cache, focus session end, water day, events |
| AI refill (web worker) | `ai_cache`, AI counters and breaker settings |
| `POST /api/usage` | usage reports (identical pushes within 30 s are skipped) |
| Telegram poller | update offset, nudge cooldowns |
| Display | `ai_wanted` demand only, throttled as above |

## Security boundary

- `JIRI_ADMIN_PASSWORD` must be set; with no password every login is refused.
- Every state-changing form and JSON call needs the CSRF token.
- Private endpoints (`/screen`, `/api/screen`, `/api/focus`, `/api/weather`,
  `/api/water`, `/api/ai/status`, `/api/usage` GET) need a login on the
  `all`/`admin` surfaces. Public `/api/status` is stripped to three fields.
- The login-free `screen` surface binds to `127.0.0.1` unless
  `JIRI_SCREEN_HOST` says otherwise.
- `POST /api/usage` needs `Authorization: Bearer $JIRI_USAGE_TOKEN`; with no
  token it answers 503.
- No user data is sent to any AI provider (see `docs/AI_SPEC.md` §1).
