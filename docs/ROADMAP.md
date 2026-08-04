# Roadmap

`docs/ENGINEERING_HANDBOOK.md` is the source-of-truth roadmap. This file is the short progress tracker.

## Completed / Current

- Stage 0: Planning and repo setup. Status: passed.
- Stage 1: Core deterministic logic. Status: passed.
- Stage 2: Weather and location. Status: passed.
- Stage 3: CLI completion. Status: passed.
- Stage B: Web Admin. Status: passed in WSL.
- Stage C: Focus Assist. Status: passed in WSL.
- Stage D: ASCII/Touch Display foundation. Status: scaffolded in WSL, hardware confirmation required.
- Stage P0/P1: Deterministic persona and proactive Telegram nudges. Status: passed in WSL.
- Stage E: AI wording layer. Status: implemented and unit-gated in WSL; real Pi 3B+ measurement required (docs/AI_SPEC.md Gate 3).
- Safe update methodology: documented with verified SQLite backup/restore scripts; automatic update remains opt-in until real Pi smoke acceptance.

## New Handbook Build Order

| Stage | Name | Status | Summary |
| --- | --- | --- | --- |
| A | Main App Stable | Passed in WSL | Todos, notes, weather, location search, CLI, tests. |
| B | Web Admin | Passed in WSL | Flask dashboard by IP, todo CRUD, notes CRUD, weather location control, JSON APIs. |
| C | Focus Assist | Passed in WSL | Focus timer, pause/resume/complete, no DB writes every second. |
| D | ASCII/Touch Display | Scaffolded | Persistent face, right info panel, touch zones, focus eyes, typed mouth scaffold; needs real display confirmation. |
| P | Persona And Proactive Behavior | P0-P4 software implemented in WSL | Deterministic persona, Telegram nudges, event model, typed mouth scaffold, and web controls. |
| E | AI Wording Layer | Implemented, gated | Hosted free-tier APIs generate line templates in the background; render path is cache-only. Gate 3 needs real Pi. |
| F | AI Integration | Gated | Hosted API wording is required; acceptance still requires AI_SPEC Gate 3 on real Pi 3B+. |
| G | Telegram Admin | Passed in WSL | Polling bot, CRUD/control commands, summary command, user whitelist, and deterministic destructive confirmations. |
| U | Safe Updates | Methodology documented | GitHub update checks, mandatory SQLite backup manifests, restore flow, and future opt-in systemd timers. |

## Blockers Before Hardware Stages

- Pi 3B+ display model and driver confirmation.
- Pi 3B+ headless smoke test.
- AI_SPEC Gate 3 acceptance before any AI claim is marked done.
