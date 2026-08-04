# JIRI Final Engineering Handbook

Document status: source-of-truth handbook  
Project: JIRI, AI-assisted Raspberry Pi desk companion  
Target hardware: one Raspberry Pi 3B/3B+  
Last updated: 2026-05-15  
Engineering rule: no claim in this handbook is production-approved until it is confirmed by source, calculated from explicit assumptions, or measured on real hardware.

## Truth Labels

| Label | Meaning |
| --- | --- |
| CONFIRMED | Backed by official documentation or stable project source. |
| CALCULATED | Derived from explicit assumptions shown in this document. |
| BENCHMARK REQUIRED | Must be measured on real Raspberry Pi hardware before acceptance. |
| DESIGN DECISION | Chosen architecture or rule for JIRI based on constraints and reasoning. |

Most important rule:

```text
JIRI is AI-assisted, not AI-controlled.
Python owns truth, timing, state, and actions.
```

## WSL-First Pi Compatibility Rule



- Use the same Pi-oriented shape: 512 context, short prompts, short outputs, strict timeouts, and deterministic fallback.
- Keep the AI wording layer disabled by default until AI_SPEC Gate 3 passes.
- Do not add desktop-only dependencies, desktop-sized context windows, or features that assume WSL CPU/RAM.
- Treat WSL/local benchmark results as development evidence only.
- Compare the same behavior later on Raspberry Pi 3B/3B+ for RAM, swap, temperature, latency, responsiveness, and offline fallback.

## Product Description

JIRI is a tiny AI-assisted Raspberry Pi desk companion. It is designed to feel alive while remaining reliable on weak hardware.

Target features:

- Persistent ASCII/Unicode face on a 3.5-inch touch display.
- Focus countdown timer with countdown eyes.
- Todos.
- Notes.
- Weather and location support.
- Proactive personality messages.
- Web dashboard by IP.
- Telegram admin control by polling.
- Optional on-device AI wording layer after benchmark acceptance.

## Single-Pi Architecture

DESIGN DECISION:

```text
Router
|- Ethernet/Wi-Fi -> Raspberry Pi 3B/3B+  hostname: jiri.local
```

### Raspberry Pi 3B/3B+

The Pi is JIRI's body, controller, and source of truth.

Responsibilities:

- JIRI core Python app.
- SQLite source-of-truth database.
- 3.5-inch touch display.
- Persistent ASCII face.
- Focus countdown eyes.
- Typed mouth message effect.
- Todos.
- Notes.
- Weather and location search.
- Focus timer.
- Deterministic emotion engine.
- Deterministic message engine.
- Proactive behavior engine.
- Web dashboard by IP.
- Telegram bot later.
- Optional AI wording layer with deterministic fallback.

The Pi owns:

- Todos.
- Notes.
- Focus sessions.
- Weather cache.
- Emotion rules.
- Display state.
- Touch confirmations.
- Config.
- System health.

Safe update rule:

- GitHub update detection may check remote SHAs or releases without modifying files.
- Every code update must create and verify a SQLite backup first.
- Database restore must be tested before automatic updates are enabled.
- See `docs/SAFE_UPDATE_METHODOLOGY.md` for the required update, backup, and restore process.

AI must never be required for boot. If the cache is empty or a provider is unreachable, JIRI continues with deterministic messages.

## Evidence And Assumptions

CONFIRMED: Raspberry Pi 3 Model B official specs include a quad-core 1.2GHz Broadcom BCM2837 64-bit CPU and 1GB RAM.

CONFIRMED: Raspberry Pi 3 Model B+ official specs include a Broadcom BCM2837B0 Cortex-A53 64-bit SoC at 1.4GHz and 1GB LPDDR2 SDRAM.




BENCHMARK REQUIRED on the real Raspberry Pi target:

- Model load success.
- Free RAM after model load.
- Swap usage after idle load.
- CPU temperature after 10 minutes.
- Short rewrite latency.
- Todo/behavior summary latency.
- SSH responsiveness.
- Main behavior when the AI cache is empty.

## AI Model Decision

On-device inference is rejected for Raspberry Pi 3B+. A 270M model costs
20-60 seconds and 100% of four cores per line, breaks five documented
performance budgets, and writes worse prose than the hand-authored strings it
would replace. See `docs/AI_STRATEGY.md` for the measurements.

The AI layer is API-driven: hosted free-tier models generate persona line
templates in a background worker. Primary `gemini-3.5-flash`, fallback
`qwen/qwen3.6-27b` on Groq. Both are OpenAI-compatible, so provider choice is
configuration rather than code.


## AI Memory Envelope

The AI layer holds no model in memory. Its runtime footprint is the SQLite
cache it reads, a few hundred KB. The background worker's footprint is one
HTTPS request at a time.


## Swap Rule

DESIGN DECISION: the single Pi may use a 1GB swap safety net for AI experiments, but swap is not VRAM.

```text
Swap is emergency overflow memory.
Swap is not a performance upgrade.
Swap must not be required for normal inference.
```

Acceptance bands:

- Acceptable: swap used after idle model load below 100 MB.
- Warning: swap used after idle model load 100-200 MB.
- Reject or downgrade: swap used after idle model load above 200 MB.

Fallbacks:

1. SmolLM2-135M-Instruct Q4_K_M.
2. Template-only mode.

## AI Acceptance Gate

Defined in full in `docs/AI_SPEC.md` §5 as three gates: software correctness in
WSL/CI, live-provider verification on a dev machine, and blocking measurement
on real Raspberry Pi 3B+ hardware. WSL results satisfy Gate 1 only.


## AI Capability Modes

Mode A: Templates only.

- Always available.
- Instant response.
- Used when the AI cache is empty or during boot.

Mode B: AI rewrite.

```text
1. Python creates factual base message.
2. Display shows base message immediately.
3. Python fills slots in a cached template locally. No facts are transmitted.
5. Display updates only if response arrives before timeout.
```

Mode C: AI summaries.

- Daily summary.
- Todo summary.
- Short note summary.
- Focus summary.
- Behavior feedback.
- Next-focus suggestion explanation.

Mode D: Short casual chat.

- Later-stage optional mode.
- Short motivational/personality replies only.
- Not a ChatGPT replacement.
- Not used for system control.

## Deterministic / AI Data Flow

```text
persona.py    decides WHAT to say and WHEN        (deterministic, always)
     |
messages.py   decides HOW it is worded
     |
     +-- ai.line()      cached template, SQLite only, sub-millisecond
     +-- fallback       built-in deterministic strings
```

The network appears nowhere on that path. `ai.refill()` runs in a background
worker and communicates with the render path only through the `ai_cache`
table. A dead provider, an expired key, a spent quota, and an unplugged cable
are all the same event to the display: a cache miss.


## 3.5-Inch Touch Display Design

DESIGN DECISION: the 3.5-inch display is not the admin dashboard. It is JIRI's living face plus quick-glance info.

BENCHMARK REQUIRED: actual resolution, rotation, touch driver behavior, framebuffer/desktop mode, and usable refresh behavior must be confirmed on real hardware.

Default assumption until confirmed:

```text
480x320
left face area: about 280 px
right glance area: about 200 px
```

Default layout:

```text
+--------------------------+----------------------+
|        JIRI FACE          | Clock                |
|                           | Weather              |
|       O        O          | Next Todo            |
|          _                | Focus Status         |
|                           | Note Preview         |
|   typed mouth message     | AI/Worker Status     |
+--------------------------+----------------------+
```

Focus mode:

```text
+--------------------------+----------------------+
|        FOCUS FACE         | Task: Study Python   |
|                           | Mode: Focus          |
|       18       42         | Progress: 62%        |
|          ___              | Next: Break 5m       |
|                           | AI: online/offline   |
|   Stay locked in.         |                      |
+--------------------------+----------------------+
```

Meaning:

- Left eye equals minutes remaining.
- Right eye equals seconds remaining.
- Mouth area equals typed focus message or coaching line.
- Right panel equals task, progress, next break, and AI state.

## Living Display Mechanics

DESIGN DECISION: the display behaves like JIRI's face, not a static terminal dashboard.

Face region responsibilities:

- ASCII/Unicode face.
- Emotion animation frames.
- Focus countdown eyes.
- Typed mouth message.
- Critical-state reactions.
- Short personality messages.

Right glance region responsibilities:

- Clock card.
- Weather card.
- Forecast card.
- Next todo card.
- Focus status card.
- Note preview card.
- AI worker status card.
- System health card.

Refresh cadence:

- Face animation: 10-15 FPS.
- Clock text: once per second.
- Focus countdown: once per second.
- Right panel data snapshot: every 1-5 seconds depending on panel.
- Weather refresh: from cache only in UI; live fetch outside UI loop.
- Todo snapshot: every 2 seconds or on event.
- AI status: every 5-10 seconds.

Typed mouth effect:

- Base message appears immediately.
- Characters reveal at 18-30 characters per second.
- AI rewrite can replace the message only if it arrives before timeout.
- If AI is late, keep the deterministic message.
- Max live display message is 160 characters unless later measured otherwise.

Focus UI safety:

- Do not write countdown to SQLite every second.
- Write only on start, pause, resume, complete, cancel, and configured checkpoint.
- Do not let AI start, pause, resume, complete, or cancel focus.
- Touch actions must confirm destructive changes.

## Persona Architecture

Layer 1: Deterministic emotion engine.

- Overdue 120+ min -> rage.
- Overdue 30+ min -> angry.
- Overdue 10+ min -> annoyed.
- Task due soon -> alert.
- Task done -> happy.
- Focus running -> focus.
- Focus complete -> task_done/happy.
- Night + idle -> sleepy.
- AI cache empty or provider unreachable -> ai_offline.
- Hot weather -> weather_hot.
- Rain -> weather_rain.
- Nothing happening -> idle.

Layer 2: Deterministic message engine.

- `idle`: Systems online. Suspiciously peaceful.
- `task_done`: Task complete. Humanity gains one point.
- `focus_started`: Focus mode engaged. I will guard your attention.
- `overdue_angry`: You are late. My disappointment database has grown.
- `ai_offline`: AI wording unavailable. Running deterministic mode.


Prompt rules:

- Do not invent facts.
- Do not change task status.
- Do not claim completion.
- Do not change due time.
- Do not mention abilities JIRI does not have.
- Keep under configured character limit.

Layer 4: AI summarizer and suggestion engine.

- Python supplies facts.

## Proactive Behavior

Allowed proactive events:

- Morning greeting.
- Task due soon.
- Task overdue.
- Focus halfway.
- Focus almost done.
- Focus complete.
- Weather hot/rain tip.
- AI offline.
- Long idle check-in.
- Night sleepy message.

Cooldown rules:

- Idle comment: every 30 minutes max.
- Overdue reminder: every 10 minutes per task.
- Weather tip: every 60 minutes.
- AI offline: once, then every 30 minutes.
- Focus milestones: once per session.
- During focus: no random jokes unless explicitly allowed.

## Runtime Behavior Playbook

Behavior priority order:

| Priority | Category | Examples | AI emotion override? |
| ---: | --- | --- | --- |
| 100 | Critical system warning | overheating, database failure | no |
| 90 | Task overdue severe | overdue 120+ minutes -> rage | no |
| 80 | Focus active | running, paused, almost done | no |
| 70 | Task due/overdue | due soon, 10+ min late, 30+ min late | no |
| 60 | AI/system state | AI offline, system hot | no |
| 50 | Weather warning | rain likely, very hot | warning no, wording yes |
| 40 | User interaction | tap, dashboard action, Telegram command | limited |
| 30 | Proactive suggestion | next focus, idle check-in | wording only |
| 10 | Casual/idle | curious, bored, dance, sleepy | yes, if no higher state |

Scenario rules:

- Normal idle: idle/curious face, clock/weather/AI status, rare cooldown-controlled message.
- No todos: idle/curious face, suspiciously peaceful message, no error state.
- Task due soon: alert face, due task card, one due-window message.
- Task overdue under 10 minutes: annoyed face, 10-minute per-task repeat limit.
- Task overdue 30+ minutes: angry face, critical overdue card.
- Task completed: happy/task_done face, one celebration message.
- Focus running: countdown eyes, no random idle jokes.
- Weather rain now: weather_rain face unless higher priority state exists.
- Very hot weather: weather_hot face unless higher priority state exists.
- Weather unavailable: neutral/system_info face, no hallucinated weather.
- AI offline: ai_offline if no higher priority state exists.
- System warning: system_warning, no AI rewrite if safety-critical.

## Engineering Event Model

DESIGN DECISION: JIRI is event-driven. Events update a compact state snapshot. The display renders the snapshot.

Core event types:

```text
todo_created
todo_due_soon
todo_overdue
todo_completed
focus_started
focus_paused
focus_resumed
focus_halfway
focus_almost_done
focus_completed
focus_cancelled
break_started
break_completed
weather_rain_now
weather_rain_likely
weather_hot
weather_unavailable
ai_online
ai_offline
system_warning
idle_long
morning_greeting
night_sleepy
```

Event payload shape:

```json
{
  "event_type": "todo_overdue",
  "created_at": "ISO-8601 timestamp",
  "priority": 70,
  "facts": {
    "todo_id": 1,
    "title": "Study Python",
    "minutes_late": 42,
    "overdue_level": 3
  },
  "allowed_ai_modes": ["rewrite"],
  "allowed_actions": ["suggest_rescue_focus", "open_todo_panel"]
}
```

State snapshot shape for UI:

```json
{
  "now": "ISO-8601 timestamp",
  "emotion": "angry",
  "face_frame_id": 2,
  "message": "Study Python is late.",
  "typed_message_progress": 0.7,
  "right_panel": "todo",
  "focus": {"active": false},
  "weather": {"available": true, "condition": "rain", "temperature_c": 31, "rain_chance": 70},
  "ai": {"online": true, "last_latency_ms": 3200},
  "touch_confirmation": null
}
```

State update cadence:

- Clock tick: 1 second.
- Focus countdown: 1 second.
- Focus milestone check: 1 second or on countdown update.
- Todo due/overdue check: 30 seconds.
- Weather refresh: configured minutes, outside UI loop.
- AI health check: 5-10 seconds.
- Proactive idle check: 60 seconds.
- Right panel snapshot: 1-5 seconds.

Database write rules:

- Do not write every frame.
- Do not write every countdown tick.
- Do not log every animation frame.
- Write events only when meaningful state changes happen.
- Use checkpoint intervals for long-running focus sessions.

## Touch Interaction State Machine

Touch zone map:

- Left face tap: cycle casual emotion.
- Left face double tap: wake/sleep.
- Left face long press: show system status.
- Right top tap: switch clock/weather/forecast panel.
- Right middle tap: switch todo/note/focus panel.
- Right bottom tap: confirm currently offered action.

Confirmation model:

- First tap creates pending confirmation.
- Second tap within timeout executes action.
- Timeout cancels confirmation.
- Default confirmation timeout is 5 seconds.

Actions requiring confirmation:

- Mark todo done.
- Cancel focus.
- Stop break.
- Snooze overdue reminder.
- Clear warning.

Critical-state touch rule:

```text
Touch can acknowledge a critical state.
Touch cannot hide the truth of a critical state.
```

## Implementation Direction

Future behavior modules:

- `src/jiri/ascii_faces.py`: face frames and fallback frames.
- `src/jiri/emotions.py`: priority-based emotion selection.
- `src/jiri/life.py`: idle, boredom, sleep, proactive timing.
- `src/jiri/message_engine.py`: deterministic messages plus AI rewrite interface.
- `src/jiri/persona.py`: persona config and safety rules.
- `src/jiri/proactive.py`: proactive event generation and cooldowns.
- `src/jiri/focus.py`: countdown sessions and milestones.
- `src/jiri/touch.py`: touch zones and confirmation state machine.
- `src/jiri/ai_client.py`: timeout-protected AI worker client.

Required behavior tests later:

- No todos -> idle/curious behavior.
- No notes -> note panel empty state.
- Weather unavailable -> no hallucinated weather.
- Rain now -> weather_rain unless higher priority task/focus exists.
- Rain likely -> weather_rain/alert with weather cooldown.
- Hot weather -> weather_hot unless higher priority exists.
- Focus running -> eyes show countdown.
- Focus running -> random idle comments suppressed.
- Focus halfway -> milestone emitted once.
- Focus almost done -> milestone emitted once.
- Task overdue -> angry/rage based on overdue minutes.
- Touch face during idle -> cycles casual emotion.
- Touch face during rage -> cannot override rage.
- Touch todo -> confirmation required before mark done.
- AI offline -> fallback message remains.
- AI late -> fallback message remains.
- AI rewrite -> cannot change facts/actions.

Display gate additions:

- Normal idle/no-task screen is readable.
- Rain-now screen is readable.
- Rain-likely screen is readable.
- Weather-unavailable screen is truthful.
- Focus countdown eyes are readable at 480x320.
- Mouth typed message does not overflow.
- Right panel switches clock/weather/todo/focus/note/status.
- Touch confirmation timeout works.
- Critical emotion persists after face tap.

## Web Dashboard

DESIGN DECISION: the web dashboard is separate from the 3.5-inch display.

URLs:

```text
Admin dashboard: http://jiri.local:5000/admin
Screen preview:   http://jiri.local:5001/screen
```

Admin and screen preview run as distinct web surfaces. The admin surface must not serve `/screen`; the screen surface must not serve `/admin/*`.

Dashboard responsibilities:

- Full todo CRUD.
- Full notes CRUD.
- Weather location search.
- Focus history.
- Focus controls later.
- Persona settings.
- AI wording status.
- Logs and health.

Performance gate:

- `GET /api/status` below 500 ms.
- `GET /admin/todos` below 500 ms after admin login.
- `POST /admin/todos` below 800 ms after admin login.
- Web process RAM below 150 MB.
- Works from phone by IP.
- Survives weather unavailable.

## Telegram Admin Bot

DESIGN DECISION: Telegram is a later-stage admin/control interface. Use polling first, not webhooks.

Reason:

- No public IP needed.
- No HTTPS certificate needed.
- Simpler for home router.

Commands:

- `/todos`.
- `/addtodo`.
- `/done`.
- `/notes`.
- `/addnote`.
- `/weather`.
- `/focus`.
- `/pause`.
- `/resume`.
- `/stop`.
- `/status`.
- `/summary`.

Security:

- Allow only configured Telegram user IDs.
- Token seeded from environment or config on first boot, then stored in SQLite and managed from the web UI.
- Never commit token.
- Confirm destructive actions.
- Ignore unknown users.

## Focus Assist

JIRI includes a countdown focus timer.

Capabilities:

- Start focus session.
- Pause.
- Resume.
- Complete.
- Cancel.
- Start break.
- Link focus to todo.
- Show countdown as eyes.
- Show focus progress on right panel.
- Suggest break after completion.

Database rule:

```text
Do not write to SQLite every second.
Display may update every second.
Database checkpoint should happen only on state change or configured interval.
```

Recommended defaults:

- Default focus: 25 minutes.
- Default break: 5 minutes.
- Checkpoint: 60 seconds.

## Weather And Location

Weather source order:

1. Open-Meteo by saved latitude/longitude.
2. wttr.in fallback.
3. SQLite weather cache.
4. Unavailable message.

Location search:

- Open-Meteo geocoding is used only when the user searches or changes location.
- Normal weather refresh uses saved coordinates.
- Do not geocode every weather refresh.

Display:

- Right panel shows compact current weather.
- AI may comment on weather facts.
- AI must not invent weather.

## Configuration Direction

Future config sections:

```toml
[display]
layout = "face_left_info_right"
touch_enabled = true
width = 480
height = 320
fps = 15
typing_chars_per_second = 24
confirmation_timeout_seconds = 5
right_panel_rotation_seconds = 20

[focus]
enabled = true
default_minutes = 25
break_minutes = 5
checkpoint_seconds = 60

[persona]
name = "JIRI"
style = "tiny_sarcastic_robot"
humor_level = 0.7
sarcasm_level = 0.6
kindness_level = 0.8
max_message_chars = 160

[proactive]
enabled = true
idle_comment_minutes = 30
overdue_repeat_minutes = 10
weather_tip_minutes = 60
quiet_hours_start = 23
quiet_hours_end = 6
focus_random_jokes_enabled = false

[behavior]
empty_todo_idle_comment_minutes = 30
rain_tip_minutes = 60
critical_emotion_persistent = true
touch_can_override_critical = false

[ai]
enabled = false
provider = "none"
server_port = 8080
server_context = 512
server_threads = 2

[telegram]
enabled = false
bot_token_env = "JIRI_TELEGRAM_BOT_TOKEN"
allowed_user_ids = []
poll_seconds = 3
```

Note: `[ai].enabled` stays false until the real Pi benchmark passes.

## Build Order

Stage A: Main App Stable.

- Todos.
- Notes.
- Weather.
- Location search.
- CLI.
- Tests pass.

Stage B: Web Admin.

- Dashboard by IP.
- Todo CRUD.
- Notes CRUD.
- Focus controls later.

Stage C: Focus Assist.

- Focus timer.
- Pause/resume/complete.
- Focus state in database.
- No DB writes every second.

Stage D: ASCII/Touch Display.

- Persistent face.
- Right info panel.
- Typed mouth messages.
- Touch zones.
- Focus eyes countdown.

Stage E: AI Wording Layer.

- Safe debloat.
- 1GB swap safety net.
- Benchmark RAM/swap/temp/latency.
- Test deterministic fallback when the AI cache is empty.
- WSL tests satisfy AI_SPEC Gate 1 only; Gate 3 needs real hardware.

Stage F: AI Integration.

- Production acceptance only after the real Pi benchmark passes.
- Local development must remain disabled by default and Pi-compatible.
- AI wording layer.
- Background requests only.
- No render-loop waiting.
- Fallback templates.

Stage G: Telegram Admin.

- Remote CRUD.
- Focus controls.
- Summary command.
- Security whitelist.

## AI Verification

The AI layer needs no shell scripts. It is verified by `tests/test_ai.py`,
which covers the whole layer without any network access, plus the Gate 2 and
Gate 3 procedures in `docs/AI_SPEC.md` §5.


## System Acceptance Gates

Display gate passes if:

- Actual detected resolution or 480x320 fallback renders.
- Face remains visible.
- Right panel readable.
- Touch zones work.
- Casual emotion changes on tap.
- Critical emotion cannot be overridden.
- Focus countdown eyes update once per second.
- Typed mouth message works.
- UI runs 30 minutes without crash.
- UI RAM below 250 MB.
- UI idle CPU below 30%.
- Temperature below 75 C.

Web gate passes if:

- `GET /api/status` below 500 ms.
- `GET /admin/todos` below 500 ms after admin login.
- `POST /admin/todos` below 800 ms after admin login.
- Web RAM below 150 MB.
- Works from phone by IP.
- Survives weather unavailable.


Telegram gate passes if:

- `/todos` response below 2 seconds.
- `/done` requires confirmation.
- `/focus` starts timer.
- Unknown users ignored.
- Internet outage does not crash JIRI core.

Fallback gate passes if:

- Main Pi boots without AI worker.
- Template messages work without AI.
- Display does not freeze if AI is unavailable. It cannot: the render path never calls out.
- Web dashboard still works if AI is offline.

## Failure Handling

| Failure | Required behavior |
| --- | --- |
| AI unavailable | Use deterministic messages. Announce once, never repeat. |
| Weather API fails | Use weather cache. |
| No weather cache | Show unavailable weather message. |
| Pi overheats | Disable AI requests and show warning. |
| Database locked | Show friendly error and do not crash display. |
| Touch driver unavailable | Display remains read-only. |
| Telegram offline | JIRI core continues normally. |
| Web dashboard crash | Display and CLI continue. |

## Final Engineering Summary

```text
JIRI is a single-Pi AI-assisted desk companion.
The Pi is the source of truth.
AI is an optional wording layer.
The display is a living face, not an admin dashboard.
Normal idle, no-task, rain, focus, overdue, and touch behaviors are explicitly defined.
Web and Telegram are separate control surfaces.
The system must always fall back to deterministic Python.
```

## Source References

- Raspberry Pi 3 Model B official specs: https://www.raspberrypi.com/products/raspberry-pi-3-model-b/
- Raspberry Pi 3 Model B+ official specs: https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/
- Pygame event documentation: https://www.pygame.org/docs/ref/event.html
- Telegram Bot API: https://core.telegram.org/bots/api
