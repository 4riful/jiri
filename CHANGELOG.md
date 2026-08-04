# Changelog

All notable changes to JIRI are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

JIRI has not had a tagged release yet. Everything below is on `main`.

## [Unreleased]

### Added

- **Nothing UI theme**, a black, white, and red system that sits alongside the default
  Catppuccin Mocha palette. It uses Nothing-style typography where the font is available and
  falls back cleanly where it is not. The choice is stored in SQLite through persona settings,
  and the navbar button toggles between the two.
- **Water history.** Hydration is no longer just a daily counter. The admin dashboard now shows
  today, the last 7 days, the last 30 days, and a 12-month aggregation, all backed by SQLite.
  Profile-based daily targets set the goal.
- **Safe update tooling.** `/admin` has an Updates button that compares the local Git state with
  the configured upstream using `git ls-remote`. It reports and stops there. It does not run
  `git pull`, does not run `git reset`, and does not touch the working tree.
- `scripts/backup_db.sh`, which uses SQLite's online backup API and writes a manifest with a
  SHA-256 hash, schema version, table names, row counts, and integrity status.
- `scripts/restore_db.sh`, which verifies a backup before restoring it and backs up the current
  database first. The full procedure is in `docs/SAFE_UPDATE_METHODOLOGY.md`.
- **AI wording layer** (`src/jiri/ai.py`), a required production capability. A background worker asks a hosted
  provider for persona line *templates* and caches them in SQLite. Provider failover, a
  consecutive-failure circuit breaker, a daily request cap that survives restarts, and a
  sanitizer that rejects rather than truncates. Provider presets ship for Gemini, Groq, xAI,
  and custom OpenAI-compatible endpoints.
- `/admin/ai` status page showing provider health, cache depth per bucket, and daily quota use.
- Read-only SQLite browser at `/admin/db-browser` for inspecting raw tables.
- Typed mouth message reveal on the display, with the speed configurable through
  `[display].typing_speed_cps`.
- Telegram admin controls: bot status, chat allowlist management, and token handling from
  `/admin/telegram`, with SQLite as the source of truth after first boot.
- Persona settings page for quiet hours, per-category cooldowns, category toggles, and theme.
- Weather forecast display covering current conditions, the next 12 hours across a midnight
  boundary, and daily outlook.

### Changed

- SQLite and backup paths now resolve to stable absolute paths instead of depending on the
  launcher's current directory. WSL tests always use an isolated database and cannot inherit
  and delete the live database path.
- The browser display preview now uses the canonical 480x320 geometry with a fixed-width ASCII
  face, dedicated focus readout, compact glance rows, and touch-sized panel controls.
- Production readiness now requires credentials for at least one hosted AI provider. Provider
  outages still fall back to cached or built-in wording without giving AI control over state.
- **The local-LLM plan was abandoned and replaced with an API-driven wording layer.** On-device
  inference was measured at 20 to 60 seconds per line on a Pi 3B+, which breaks five documented
  performance budgets. `docs/AI_STRATEGY.md` records the measurements and the decision.
  `docs/AI_SPEC.md` defines what replaced it.

  The replacement is deliberately narrow. AI generates reusable templates in the background;
  the device fills `{task}` and `{minutes}` slots locally at render time. The render path reads
  SQLite and nothing else. A dead provider, an expired key, a spent quota, and an unplugged
  cable all look identical to the display: a cache miss, followed by the built-in deterministic
  wording.

  It also buys a privacy property that a live rewrite could not. No todo title, note, location,
  or water log is transmitted. The outbound request carries a category name, a mood name, and a
  fixed style brief. That is structural, not a policy promise.

  The layer stays off by default and is not accepted until Gate 3 in `docs/AI_SPEC.md` passes on
  real Pi 3B+ hardware.
- Persona escalation wording now gets **shorter and flatter** as a task slips, instead of louder.
  The face carries the escalation. Commenting on a user's shortfall is the most-disliked
  behaviour in a proactive assistant, and a nagging desk device gets unplugged.
- Telegram controls hardened: allowlist enforcement, clearer status reporting, and settings that
  live in SQLite rather than in environment variables after first boot.
- Admin and screen surfaces were split into separate processes on separate ports, 5000 and 5001.
  `scripts/run_all.sh` starts both, cleans up stale processes, and refuses to start on a port
  conflict.

### Removed

- The `[llm]` configuration block, replaced by `[ai]` with `[[ai.providers]]` entries. An
  existing `config.toml` that still carries `[llm]` fails to load with an `Unknown config keys`
  error rather than silently ignoring it. That is deliberate, so the rename is noticed.
- Local LLM server management from the dashboard, which went with the abandoned on-device plan.

### Fixed

- Weather location search and forecast rendering in the dashboard.
- Next-12-hour forecast slicing across midnight.

### Security

- API keys are read from the environment (`GEMINI_API_KEY`, `GROQ_API_KEY`, and `JIRI_`-prefixed
  variants). `config.toml` is gitignored and `config.example.toml` carries no real values.
  See `SECURITY.md`.
