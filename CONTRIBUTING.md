# Contributing to JIRI

Thanks for looking at JIRI. It is a small Python app that lives on a Raspberry Pi 3B+ and tries
to feel alive without pretending to be a cloud product. Contributions are welcome, and quite a
few of the most useful ones need no hardware at all.

Two things worth knowing before you start:

1. The core is deterministic. Python owns state, timing, and actions. AI only supplies wording.
2. The target machine is a Pi 3B/3B+ with 1 GB of RAM. Every change is judged against that,
   not against the laptop you wrote it on.

If a change respects those two things, the rest is normal open-source work.

## Table of contents

- [Getting set up](#getting-set-up)
- [Running the app](#running-the-app)
- [Running the tests](#running-the-tests)
- [The hard rules](#the-hard-rules)
- [Code style](#code-style)
- [Commits and pull requests](#commits-and-pull-requests)
- [Good first contributions](#good-first-contributions)
- [Writing persona lines (no hardware needed)](#writing-persona-lines-no-hardware-needed)

## Getting set up

### On WSL, Linux, or macOS

This is where almost all development happens. You do not need a Raspberry Pi.

```bash
git clone https://github.com/4riful/jiri.git
cd jiri
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in `requirements.txt`, so that one command is enough.

Python 3.11 or newer is what CI runs. Python 3.10 still works, because `requirements.txt` adds
`tomli` as a `tomllib` stand-in below 3.11.

A useful development environment, taken from `docs/WSL_DEVELOPMENT.md`:

```bash
export PYTHONPATH=src
export JIRI_DISPLAY_DRIVER=mock
export JIRI_FULLSCREEN=false
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_WEATHER_FAKE=true
export JIRI_DB_PATH=data/jiri_dev.db
```

`JIRI_DISPLAY_DRIVER=mock` matters. The Pygame display is not expected to work in WSL, and
nothing in the test suite assumes it does. `JIRI_WEATHER_FAKE=true` gives deterministic weather
so you are not hitting Open-Meteo while you iterate.

Initialise a database and check that things are wired up:

```bash
PYTHONPATH=src .venv/bin/python -m jiri.cli init-db
PYTHONPATH=src .venv/bin/python -m jiri.cli health
```

### On a Raspberry Pi

Only needed if you are working on the display, thermals, or anything measured in `docs/PERFORMANCE_BUDGETS.md`.

```bash
git clone https://github.com/4riful/jiri.git
cd jiri
scripts/install_pi.sh
```

Then set production display values before starting the UI:

```bash
export JIRI_DISPLAY_DRIVER=pygame
export JIRI_FULLSCREEN=true
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_DB_PATH=data/jiri.db
```

`docs/PI_DEPLOYMENT.md` has the rest, including systemd notes. Install the units only after the
relevant gate in `docs/STAGE_GATES.md` passes. `scripts/measure_pi.sh` collects the numbers used
for hardware acceptance, and `scripts/pi_smoke_test.sh` is the deployment smoke check.

## Running the app

```bash
scripts/run_all.sh       # admin on :5000 and screen preview on :5001
scripts/run_admin.sh     # admin only
scripts/run_screen.sh    # screen preview only
scripts/run_telegram.sh  # Telegram polling worker
scripts/run_ui.sh        # Pygame display
```

Admin is at `http://127.0.0.1:5000/admin`, screen preview at `http://127.0.0.1:5001/screen`.
The development password is `test`; override it with `JIRI_ADMIN_PASSWORD`.

If the ports are taken:

```bash
JIRI_ADMIN_PORT=5100 JIRI_SCREEN_PORT=5101 scripts/run_all.sh
```

## Running the tests

The whole suite, from the repository root:

```bash
.venv/bin/python -m pytest tests/ -q
```

`tests/conftest.py` puts `src/` on `sys.path`, so plain `pytest` works with no install step and
no `PYTHONPATH`. You only need `PYTHONPATH=src` when you invoke `jiri.cli` or a module directly.

The full gate, which runs the tests and then walks the CLI end to end, is:

```bash
scripts/test_wsl.sh
```

That script creates `.venv` if it is missing, installs dev requirements, deletes and rebuilds a
throwaway database, and exercises todos, notes, focus, the mock display, location, weather, and
health. Run it before opening a pull request. It is the same gate the maintainers use.

A few notes on the suite:

- No test may make a real network call. The HTTP layer is injected. See `docs/AI_SPEC.md` §6.
- `tests/test_web.py::test_web_response_budget_smoke` asserts wall-clock response times against
  the budgets in `docs/PERFORMANCE_BUDGETS.md`. It is timing sensitive and can fail on a loaded
  or slow machine without anything being wrong with your change. Re-run it on an idle machine
  before you go hunting.
- New behaviour needs a test or a documented smoke check. Every stage of this project has one.

## The hard rules

These are not preferences. A pull request that breaks one of them will not be merged, however
nice the feature is. The long form lives in `docs/ENGINEERING_HANDBOOK.md` and `AGENTS.md`.

### The deterministic core owns state

Todos, notes, focus timers, due dates, weather facts, water logs, and system state belong to
Python and SQLite. JIRI works with AI disabled, uninstalled, or offline, and that is the normal
configuration.

### AI supplies wording, and only wording

The AI layer generates persona line *templates* in a background worker and stores them in the
`ai_cache` table. Placeholders like `{task}` and `{minutes}` are filled in locally on the device.

That design buys a real privacy property: no todo title, note, location, or water log is ever
transmitted. The outbound request contains a category name, a mood name, and a fixed style
brief. Keep it that way. If you find yourself putting user data into a request body, stop.

AI may never write any table except `ai_cache`, decide *what* to say or *when* (that is
`persona.py`), or become a required dependency.

### Nothing on the render path touches the network

No network call may be reachable from `ai.line()`, `messages.*`, `views.*`, `persona.*`, or
`jiri.ui.*`. A dead provider, an expired key, a spent quota, and an unplugged cable must all look
identical to the display: a cache miss, followed by the built-in deterministic wording.

This is invariant I1 in `docs/AI_SPEC.md` §3, and there is a test for it.

### No per-frame database writes

The UI frame loop never writes to SQLite, never runs slow scans, and never blocks on I/O. The Pi
boots from an SD card, and chatty writes kill SD cards. Focus sessions checkpoint on an interval,
not per second, for exactly this reason.

### Performance budgets are real numbers

`docs/PERFORMANCE_BUDGETS.md` is the reference. The ones you are most likely to touch:

| Budget | Limit |
| --- | --- |
| UI frame rate | 10 to 15 FPS |
| Total JIRI memory | under 350 MB |
| AI cache lookup on the render path | under 5 ms |
| Weather fetch timeout | 3 seconds, hard |
| AI API timeout | 8 seconds, background worker only |
| Web API response, locally | under 500 ms |
| Database file, v1 | under 50 MB |

Every network request needs a timeout and an offline fallback. Fonts and reusable UI resources
are loaded once, not per frame.

### Dependencies stay small

No React, Node, Electron, Docker, Kubernetes, PostgreSQL, MongoDB, Redis, or Celery. No browser
kiosk as the Pi display. The current dependency list is Flask, Pygame, and requests. Adding a
fourth needs a good argument in the pull request.

One more, so nobody spends a weekend on it: on-device LLM inference was measured and rejected
for Pi 3B+ hardware. `docs/AI_STRATEGY.md` records why. Please do not reopen it.

## Code style

There is no formatter or linter configured, so the rule is to match the file you are editing.

- `from __future__ import annotations` at the top of every module.
- Type hints on public functions. Dataclasses for structured data, frozen where they are values.
- Double quotes, 4 spaces, roughly 100 to 110 characters per line.
- Standard library first, then third party, then local relative imports.
- Comments explain *why*, not *what*. The existing ones in `messages.py` and `ai.py` are the
  house style: short, specific, and they cite the doc or the invariant they come from.
- Business logic stays out of `ui/` and `web/`. Database access stays out of rendering.
- Keep module boundaries as described in `docs/ARCHITECTURE.md`.

## Commits and pull requests

Commit messages are lowercase, imperative, and describe the change rather than the file:

```text
persist water history and harden Telegram controls
add Nothing UI theme alongside Catppuccin Mocha
enhance dashboard history and safe updates
```

For pull requests:

- One concern per pull request. A theme change and a schema change are two pull requests.
- Say what you ran. "`scripts/test_wsl.sh` passes" is the sentence maintainers look for.
- If you touched the display, the persona engine, or anything in the AI path, say which budget
  or invariant you checked.
- If you changed the SQLite schema, bump the schema version, keep the migration additive, and
  say how to roll back. `docs/SAFE_UPDATE_METHODOLOGY.md` covers backups before a schema change.
- Documentation changes count as contributions. So do typo fixes.

Open an issue first if the change is large, hardware dependent, or touches the AI boundary. It
saves you writing code that will be turned down on principle.

## Good first contributions

Real areas, roughly in order of how easy it is to start:

**Persona lines.** New wording for JIRI's built-in message pools. No hardware, no setup, and it
is the fastest way to make the device feel different. See the section below.

**Face expressions.** `src/jiri/ui/face.py` holds `FACE_STATES` and `FACE_FRAMES`. Each frame is
a left eye, a right eye, a mouth, and a label, all plain strings. Adding a state means adding it
to both structures and covering it in `tests/test_ui_display.py`. Keep it readable at 480x320.

**Translations.** JIRI has no i18n layer yet, and the strings are currently English constants in
`messages.py` and the Flask templates. If you want to build that, open an issue first so we can
agree on the shape. It has to stay tiny; no heavyweight translation framework on a Pi 3B+.

**Documentation.** `docs/TROUBLESHOOTING.md` and `docs/PI_DEPLOYMENT.md` improve every time
somebody hits a problem and writes down what fixed it. Real Pi 3B+ measurements are especially
welcome, since several claims in the docs are still marked as needing hardware.

**Provider presets.** `PROVIDER_PRESETS` in `src/jiri/ai.py` maps a provider name to an
OpenAI-compatible `base_url`, an API key environment variable, a default model, and tuning
parameters. Adding one is a small dictionary entry. Adding one *well* means saying in the comment
why that model, what the free tier actually is, and whether the provider trains on inputs. The
existing Gemini and Groq entries show the bar.

**A new weather provider.** `src/jiri/weather.py` already does Open-Meteo, then wttr.in, then
the SQLite cache. Another fallback needs a 3 second timeout, a parser, and tests that never
touch the network.

**The AI_SPEC open questions.** `docs/AI_SPEC.md` §9 lists three genuinely undecided questions,
including whether a fresh install should ship with hand-written seed templates. Opinions backed
by measurement are welcome.

## Writing persona lines (no hardware needed)

This is the contribution with the shortest path from idea to merged, and you need nothing but a
text editor and a sense of humour.

JIRI's built-in wording lives in `src/jiri/messages.py` as plain Python lists:

```python
IDLE_MESSAGES = [
    "Systems calm. Suspiciously calm.",
    "No pending tasks. I will allow it.",
    "Desk assistant idle. Try not to break anything.",
]
```

There are pools for idle, celebration, focus, and focus milestones. Pick one, add lines, open a
pull request. If you would rather just suggest wording without touching the code, open a
[persona line issue](https://github.com/4riful/jiri/issues/new?template=persona_line.yml) and
somebody will wire it in.

### The voice

JIRI is dry, brief, and mildly unimpressed. It is not a cheerleader and it is not a therapist.

The first rule is simple: **JIRI jokes about the situation or about itself, never about the
user.** It is a device on somebody's desk, not a heckler.

The second rule surprises people, so it is worth stating plainly:

> **JIRI gets quieter as you fall behind, not louder.**

Look at the escalation ladder in `messages.py`:

```python
1: ("{task} is due.", 0),
2: ("{task}. 10 minutes over.", 10),
3: ("{task}. 30 minutes over.", 30),
4: ("{task}. 1 hour over.", 60),
5: ("{task}.", 120),
```

The wording gets shorter and flatter as a task slips. The face carries the escalation instead;
`persona.py` moves it from alert to annoyed to angry to rage. Commenting on somebody's shortfall
is the behaviour users dislike most in a proactive assistant, and escalating hostility reads as
nagging. Nagging is how a desk device ends up unplugged.

So the personality belongs in the *neutral* moments: idle, ambient, weather, celebration, focus.
Not in the moments where the user is already failing.

### Checklist for a good line

- Under 160 characters after any placeholder is filled. That is `max_output_chars`.
- Uses only the slots its category offers. `docs/AI_SPEC.md` §4 has the table: `task` and
  `minutes` for todos, `amount` and `goal` for water, `temp` and `condition` for weather.
- No markdown, no emoji, no wrapping quotes. The display renders plain text at 480x320.
- Jokes about the situation or about JIRI. Never about the user.
- Funny is good. Mean is not. It has to be readable on somebody's desk at 8am on a Monday.
- Reads well next to the lines already in the pool. Consistency beats cleverness.

Add your line, run `.venv/bin/python -m pytest tests/ -q`, and open the pull request. That is
the whole process.
