<div align="center">

<img src="jirie.png" alt="JIRI" width="180">

# JIRI

**A desk companion that lives on a Raspberry Pi, has a face, and quietly judges your todo list.**

*(It has been asked to stop judging. It has agreed to judge more quietly.)*

[![CI](https://github.com/4riful/jiri/actions/workflows/ci.yml/badge.svg)](https://github.com/4riful/jiri/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Runs on Pi 3B+](https://img.shields.io/badge/runs%20on-Pi%203B%2B-c51a4a.svg)](docs/HARDWARE.md)
[![Tests](https://img.shields.io/badge/tests-201%20passing-brightgreen.svg)](tests/)

[About](#about) · [Features](#features) · [Quick start](#quick-start) · [Hardware](#hardware) · [How it works](#how-it-works) · [Contributing](#contributing)

</div>

---

## About

JIRI is a small always-on companion for your desk. It shows a face on a
3.5-inch screen, keeps your todos and notes, runs focus timers, nags you about
water, tells you if it is going to rain, and talks to you on Telegram.

It runs on a Raspberry Pi 3B+. Not a Pi 5. Not a mini PC with a GPU. A ten year
old board with one gigabyte of RAM, because that is what was in the drawer.

**The idea that makes it different:** most assistant projects put a language
model in charge and hope. JIRI does the opposite. A deterministic Python core
owns every fact, every decision, and every piece of state. Nothing else is
allowed to touch them. Hosted API AI is a required part of JIRI, but it gets
exactly one job: choosing nicer words in the background.

That constraint is the whole design. A production-ready setup needs at least
one provider key, while cached and built-in wording keep the device usable
during an outage. AI still cannot be talked into deleting your todos.

### Why you might want one

- You want a physical thing on your desk that is *yours*, not a rented cloud service.
- You like the idea of a pet that reminds you to drink water.
- You have a spare Pi and a weekend.
- You want to read a small codebase where the architecture is actually written down.

### Why this is not another chatbot

| | JIRI | Typical LLM assistant |
|---|---|---|
| Who owns your data | SQLite file on your desk | Somebody's cloud |
| Survives an outage | Yes, cache then built-ins | Usually no |
| Production setup needs an API key | Yes, for wording generation | Yes |
| Can AI change your data | No, structurally | Usually yes |
| API cost | Free-tier friendly, capped | Usually per token |

---

## Features

**A face that means something.** Fifteen expressions driven by real state, not
randomness. It squints when you are focused, perks up when the weather turns,
and goes quiet when you are behind. The mouth types out messages character by
character because that is more fun than blitting a string.

The rule underneath that: **nothing on this screen moves unless something
happened.** No idle mood drift, no timed expression shuffling, no re-rolling the
sentence on every repaint. The face changes when the state behind it changes and
not before, and a line under it always names the fact that caused the change, so
you are never looking at an expression you cannot explain. Idle motion is
limited to breathing, blinking and the ticking seconds. A display that fidgets
on its own is one you stop reading.

**A screen laid out as a guardian, not a dashboard.** 480x320, four rows:

```
● JIRI  by 4riful                        WED 05 AUG 2026 15:06:11
┌──────────┐   ☑ PENDING TASKS
│   face   │   2
└──────────┘   Next: Verify JIRI persistence
▌ No deadlines breathing down anyone's neck. Carry on.
  ▪ 100% RAIN TODAY
 ☑ 2   ◌ 0%   ◷ off   ☀ 28°   ▤ 2
```

The strip along the bottom is every duty JIRI holds — todos, water, focus,
weather, notes — always visible and colour-coded, so you can trace the
expression to the thing that caused it without reading a word. The voice line
never reads back the block above it: when you are already looking at what JIRI
is reacting to, it comments instead of restating. Cached weather is marked as
cached rather than dressed up as live, and the messages can never claim an empty
list while the strip reads two.

**Todos that escalate politely.** Tasks climb five levels of overdue. Here is
the part most reminder apps get wrong: as a task slips, JIRI's messages get
*shorter*, not meaner. The face carries the feeling instead. A nagging device
gets unplugged. See [the research behind that](docs/AI_SPEC.md).

**Focus sessions.** Start a timer, JIRI shuts up and roots for you silently.
Pause, resume, and milestone nudges at the halfway point. No per-second
database writes, which matters when your storage is an SD card.

**Water tracking** with a goal calculated from your age and sex, plus weekly,
monthly, and yearly history.

**Weather** from Open-Meteo, with a wttr.in fallback, and a SQLite cache
fallback behind that. Three layers deep because the first two will fail
eventually.

**A Telegram bot** with a chat allowlist, full CRUD, and confirmation prompts
before anything destructive.

**A web cockpit** on your phone or laptop. Two themes: Catppuccin Mocha and a
Nothing-inspired dot matrix.

**Required API wording.** Hosted models write persona lines in the
background, on a schedule, into a local cache. The display only ever reads the
cache, so AI can never slow down, block, or break the screen. And it sends no
personal data, because it generates *templates* like `{task} is due` that get
filled in on the device.

---

## Quick start

Works on WSL, Linux, and macOS for development. You do not need a Pi to hack on it.

```bash
git clone https://github.com/4riful/jiri.git
cd jiri

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt

PYTHONPATH=src .venv/bin/python -m jiri.cli init-db
```

Add something to do, then look at it:

```bash
PYTHONPATH=src .venv/bin/python -m jiri.cli todo add "Water the plants" --due "2026-08-05 18:00"
PYTHONPATH=src .venv/bin/python -m jiri.cli todo list
```

Start the web surfaces:

```bash
scripts/run_all.sh
```

- Dashboard: <http://localhost:5000/admin> (default password is `test` in dev)
- Live screen preview: <http://localhost:5001/screen>

Run the tests:

```bash
.venv/bin/python -m pytest tests/ -q
```

### Put it on a Pi

```bash
scripts/install_pi.sh
scripts/create_systemd_services.sh
```

Full walkthrough in [docs/PI_DEPLOYMENT.md](docs/PI_DEPLOYMENT.md).

---

## Hardware

| Part | What I used | Notes |
|---|---|---|
| Board | Raspberry Pi 3B+ | 1GB RAM. A Pi 4 or 5 works and is easier. |
| Display | 3.5" GPIO LCD, 480x320 | Touch optional |
| Storage | microSD | A good one. Cheap cards die. |
| Power | 5V 2.5A | |
| Mic or speaker | None | Not needed. JIRI is silent. |

Details and the still-open hardware questions are in
[docs/HARDWARE.md](docs/HARDWARE.md).

---

## How it works

```text
                        Your phone / laptop
                                 |
                    +------------+------------+
                    |  Flask admin :5000      |
                    |  Screen preview :5001   |
                    +------------+------------+
                                 |
  +-------------+      +---------+---------+      +-----------------+
  |  Telegram   |<---->|   JIRI Runtime    |<---->|   Open-Meteo    |
  |  bot        |      | deterministic core|      |   wttr.in       |
  +-------------+      +---------+---------+      +-----------------+
                                 |
                          +------+------+
                          |   SQLite    |   <- the only source of truth
                          +------+------+
                                 |
                +----------------+----------------+
                |                                 |
        +-------+--------+               +--------+-------+
        | Screen preview |               | Pygame display |
        |   (browser)    |               |  (the face)    |
        +----------------+               +----------------+

  Required hosted wording subsystem:
    background worker -> AI API -> line templates -> SQLite cache
    render path       -> SQLite cache -> built-in fallback. Never the network.
```

Four rules the code actually enforces:

1. **SQLite is the only truth.** Everything else is a view.
2. **The render path never does I/O it can block on.** No HTTP in the frame
   loop, no slow scans, no surprises at 15 FPS.
3. **AI returns a string or nothing.** It cannot write state, run commands,
   complete todos, or change a due date. There is no code path where it can.
4. **Every layer degrades to a working one.** AI to cache, cache to built-ins,
   live weather to cached weather.

Deeper reading:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - module map and data flow
- [docs/AI_SPEC.md](docs/AI_SPEC.md) - the AI layer, its invariants, acceptance gates
- [docs/AI_STRATEGY.md](docs/AI_STRATEGY.md) - why a local LLM on a Pi 3B+ does not work
- [docs/PERFORMANCE_BUDGETS.md](docs/PERFORMANCE_BUDGETS.md) - the numbers everything is held to
- [docs/ENGINEERING_HANDBOOK.md](docs/ENGINEERING_HANDBOOK.md) - the long version

---

## Configuration

Copy `config.example.toml` to `config.toml` and edit it. Storage defaults are
resolved to absolute paths, so launching JIRI from another directory does not
silently create a second database.

```toml
[assistant]
name = "JIRI"
personality = "playful_joyful"

[display]
width = 480
height = 320
fps = 15
typing_speed_cps = 24

[ai]

[[ai.providers]]
name = "gemini"

[[ai.providers]]
name = "groq"
```

Environment variables override the file. The ones you are most likely to want:

| Variable | What it does |
|---|---|
| `JIRI_DB_PATH` | Where the SQLite file lives |
| `JIRI_DISPLAY_DRIVER` | `pygame` or `mock` for headless dev |
| `JIRI_TELEGRAM_BOT_TOKEN` | Seeds the Telegram bot on first boot |
| `GEMINI_API_KEY` / `GROQ_API_KEY` | Keys for the default AI provider chain |
| `XAI_API_KEY` | Key for xAI/Grok when configured |
| `JIRI_AI_DAILY_CAP` | Maximum hosted AI requests per day |

### Configure AI Providers

Hosted API wording is required for a production-ready JIRI. Configure one or
more providers; JIRI tries them in order. Gemini and Groq both expose
OpenAI-compatible chat-completions APIs, so no provider-specific SDK is needed.

**Google Gemini:** create a key in [Google AI Studio](https://aistudio.google.com/),
then export it:

```bash
export GEMINI_API_KEY=...
```

```toml
[[ai.providers]]
name = "gemini"
model = "gemini-3.5-flash"
```

**Groq:** create a key in the [Groq Console](https://console.groq.com/), then:

```bash
export GROQ_API_KEY=...
```

```toml
[[ai.providers]]
name = "groq"
model = "qwen/qwen3.6-27b"
```

**xAI/Grok:** xAI uses the same protocol. It is not part of the default
free-tier chain, but can be added with `XAI_API_KEY`:

```toml
[[ai.providers]]
name = "xai"
model = "grok-4.20-0309-non-reasoning"
```

**Any OpenAI-compatible provider:** supply a unique name, API root, key
environment variable, and model identifier. Any chat-completions model can be
used if it follows the OpenAI request/response shape and can obey JIRI's short
template format.

```toml
[[ai.providers]]
name = "my-provider"
base_url = "https://api.example.com/v1"
api_key_env = "MY_PROVIDER_API_KEY"
model = "provider/model-name"
```

Never put a key in TOML or Git. Export the variable named by `api_key_env`.
If a provider is rate limited or down, JIRI moves to the next provider, then
its cache, then built-in resilience wording. User data is never sent: the API
only receives category, mood, style instructions, and placeholders.

Any OpenAI-compatible endpoint works, including
[Ollama](https://ollama.com/) on a machine in your house:

```toml
[[ai.providers]]
name = "ollama"
base_url = "http://192.168.1.50:11434/v1"
model = "llama3.1:8b"
```

---

## Roadmap

- [x] Deterministic core: todos, notes, focus, weather, water
- [x] Web dashboard and live screen preview
- [x] Telegram bot with allowlist and confirmations
- [x] Persona engine with cooldowns and quiet hours
- [x] AI wording layer and required hosted-provider configuration
- [ ] Wire the AI refill worker into a schedule
- [ ] Confirm the 3.5-inch display on real hardware
- [ ] Pi 3B+ acceptance run ([AI_SPEC Gate 3](docs/AI_SPEC.md))
- [ ] Sound, maybe. It is very quiet in here.

Tracked properly in [docs/ROADMAP.md](docs/ROADMAP.md).

---

## Contributing

Contributions are genuinely welcome, and **you do not need a Raspberry Pi**.
Everything except the display runs fine on a laptop.

The easiest place to start is JIRI's personality. Open
`src/jiri/messages.py`, read the pools, and add lines you find funny. There is
an [issue template](.github/ISSUE_TEMPLATE/persona_line.yml) just for this. One
rule: JIRI jokes about the situation or about itself, never about the user. A
second rule, learned the hard way: a line must be true in every state that can
reach it. `IDLE_MESSAGES` claim the list is empty, so they only run when it is —
a pending-but-not-late list gets `WATCHING_MESSAGES` instead. Nothing erodes a
companion faster than cheerfully announcing "zero tasks" beside a counter
reading two.

Other good entry points: new face expressions in `src/jiri/ui/face.py`, a new
weather provider, a new AI provider preset, or the docs.

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. It is short.

---

## FAQ

**Does it need internet?**
Production setup and cache refills need internet. Once running, the display and
core state continue through outages using SQLite cache and built-in wording.

**Does my data go anywhere?**
No personal data. SQLite remains on your device. The AI layer generates *templates* with
`{task}` placeholders that are filled in locally, so your todo titles are never
transmitted. That is a property of the architecture, not a promise.

**Why not run a small model on the Pi itself?**
Tried to. On a Pi 3B+ a 270M model costs 20 to 60 seconds and all four cores
per line, breaks five documented performance budgets, and writes worse prose
than the hand-written strings it would replace. The measurements are in
[docs/AI_STRATEGY.md](docs/AI_STRATEGY.md).

**Will it work on a Pi Zero / Pi 4 / Pi 5?**
Pi 4 and 5, yes and better. Pi Zero 2 W probably, untested. The whole project
is tuned for the worst case, so newer hardware is a bonus.

**Can I make it mean?**
You can, it is your device. The default deliberately is not. There is good
research showing that assistants which get snarkier as you fall behind are the
ones people unplug.

---

## Credits

Built with [Flask](https://flask.palletsprojects.com/),
[Pygame](https://www.pygame.org/), and SQLite. Weather from
[Open-Meteo](https://open-meteo.com/) and [wttr.in](https://wttr.in/). Themes
inspired by [Catppuccin](https://catppuccin.com/) and Nothing OS.

## License

MIT. See [LICENSE](LICENSE).

<div align="center">
<br>
<sub>Built for a 1GB board that refused to die.</sub>
</div>
