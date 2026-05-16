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
- Stage E: Local AI benchmark scripts. Status: scaffolded in WSL, local ctx512 preflight allowed, real Pi benchmark required.

## New Handbook Build Order

| Stage | Name | Status | Summary |
| --- | --- | --- | --- |
| A | Main App Stable | Passed in WSL | Todos, notes, weather, location search, CLI, tests. |
| B | Web Admin | Passed in WSL | Flask dashboard by IP, todo CRUD, notes CRUD, weather location control, JSON APIs. |
| C | Focus Assist | Passed in WSL | Focus timer, pause/resume/complete, no DB writes every second. |
| D | ASCII/Touch Display | Scaffolded | Persistent face, right info panel, touch zones, focus eyes, typed mouth scaffold; needs real display confirmation. |
| P | Persona And Proactive Behavior | P0-P4 software implemented in WSL | Deterministic persona, Telegram nudges, event model, typed mouth scaffold, and web controls; AI rewrite still blocked. |
| E | Local AI Benchmark | Scripts ready | Safe debloat, llama.cpp, Gemma 3 270M Q4_K_M benchmark at 512 ctx; WSL/local preflight is not acceptance. |
| F | AI Integration | Blocked for acceptance | Local AI client remains disabled by default; production acceptance only after real Pi benchmark acceptance. |
| G | Telegram Admin | Passed in WSL | Polling bot, CRUD/control commands, summary command, user whitelist, and deterministic destructive confirmations. |

## Blockers Before Hardware Stages

- Pi 3B+ display model and driver confirmation.
- Pi 3B+ headless smoke test.
- Pi AI baseline RAM/swap/temp measurements.
- Gemma benchmark acceptance before any AI integration claim.
- WSL/local Gemma results must be compared against real Pi 3B/3B+ behavior before acceptance.
