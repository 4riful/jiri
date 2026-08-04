# Persona Implementation Plan

`docs/ENGINEERING_HANDBOOK.md` remains the source of truth. This document turns the handbook persona rules into staged implementation work and acceptance checks.

## Design Rules

- Python owns emotion, timing, cooldowns, priorities, and actions.
- AI may reword only via the background template cache; see docs/AI_SPEC.md.
- Screen rendering must not write to SQLite.
- Telegram nudges must be rate-limited and allowlisted.
- Focus mode suppresses random idle chatter.
- Critical states cannot be hidden by casual animations.
- Weather facts come from provider/cache data only.

## Stage P0: Deterministic Persona Core

Status: implemented in WSL.

Scope:

- Define behavior priority order from the handbook.
- Choose face state, headline, and subheadline from deterministic facts.
- Add quiet hours, ambient micro-expressions, weather tips, water nudges, focus behavior, and todo escalation.
- Keep screen persona decisions read-only.

Acceptance:

- Unit tests cover quiet hours, focus priority, severe overdue priority, per-task cooldown keys, hydration, weather hot/rain, and ambient behavior.
- `scripts/test_wsl.sh` passes.
- No new dependency is added.

## Stage P1: Proactive Message Scheduler

Status: implemented in WSL for Telegram worker path.

Scope:

- Send proactive messages only from worker-style loops, not the UI render path.
- Store last-sent timestamps in SQLite by category or per-task key.
- Suppress low-priority nudges during quiet hours.
- Send to configured Telegram command chat or first allowed chat.

Acceptance:

- Incoming Telegram updates are processed before persona nudges.
- No proactive Telegram message is sent when an inbound command was processed in the same poll cycle.
- Cooldowns prevent repeat spam.
- Unknown chats remain ignored.

## Stage P2: Event Model And Milestones

Status: implemented in WSL.

Scope:

- Introduce compact event records for meaningful state changes.
- Emit focus halfway and almost-done milestones once per session.
- Emit todo due/overdue transition events without scanning every frame.
- Add worker offline/hot/system warning event hooks.

Acceptance:

- No per-second database writes except approved focus checkpoints.
- Milestone events are idempotent.
- Event log remains compact and bounded by cleanup policy.

## Stage P3: Typed Mouth And Display Polish

Status: software implemented; hardware acceptance required.

Scope:

- Implement typed mouth message reveal at 18-30 characters per second.
- Enforce max live display message length of 160 characters until real display testing says otherwise.
- Confirm eyes/mouth readability on real 3.5-inch display.

Acceptance:

- Pygame display stays 10-15 FPS on Raspberry Pi 3B+.
- No UI frame loop network calls.
- No UI frame loop slow database scans.
- Real touch/display test confirms visibility.

Implementation details:

- `src/jiri/ui/typing.py`: pure-Python `type_text()` tracks visible character count from elapsed time and configurable cps; `MAX_MESSAGE_LENGTH = 160`.
- `DisplayConfig.typing_speed_cps`: configurable 18-30 cps (default 24), validated in config.
- `ScreenSnapshot.typing_speed_cps`: passed to templates and API.
- Web screen: vanilla JS typing effect with blinking cursor, speed from server.
- `tests/test_typing.py`: 9 tests covering empty, partial, complete, truncation, speed variation, negative elapsed.

## Stage P4: Web Persona Controls

Status: implemented in WSL.

Scope:

- Add `/admin/persona` for quiet hours, cooldown intervals, and category toggles.
- Store settings in SQLite.
- Keep safe defaults if settings are absent or invalid.

Acceptance:

- Web CRUD saves to SQLite.
- Invalid intervals and quiet-hour values are rejected.
- Defaults work on first install.

## Stage P5: AI Rewrite Layer

Status: blocked for production acceptance until AI worker benchmark passes on real Raspberry Pi 3B.

Scope:

- Python creates factual base message first.
- Optional AI rewrites only wording from supplied facts.
- Timeout keeps deterministic message.

Acceptance:

- Stage E AI benchmark passes on real Pi 3B.
- AI cannot write SQLite, change state, lower critical emotion, or invent facts.
- Fallback remains immediate if AI is offline.

## Current Non-Goals

- No random cloud personality service.
- No AI-owned scheduling.
- No Telegram messages to unapproved chats.
- No browser kiosk display UI.
- No heavy frontend framework.
