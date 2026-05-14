# Roadmap

`docs/ENGINEERING_HANDBOOK.md` is the source-of-truth roadmap. This file is the short progress tracker.

## Completed / Current

- Stage 0: Planning and repo setup. Status: passed.
- Stage 1: Core deterministic logic. Status: passed.
- Stage 2: Weather and location. Status: passed.
- Stage 3: CLI completion. Status: passed.

## New Handbook Build Order

| Stage | Name | Status | Summary |
| --- | --- | --- | --- |
| A | Main App Stable | Mostly complete | Todos, notes, weather, location search, CLI, tests. |
| B | Web Admin | Next | Flask dashboard by IP, todo CRUD, notes CRUD, weather location control. |
| C | Focus Assist | Pending | Focus timer, pause/resume/complete, no DB writes every second. |
| D | ASCII/Touch Display | Pending | Persistent face, right info panel, typed mouth, touch zones, focus eyes. |
| E | AI Worker Benchmark | Pending | Safe debloat, llama.cpp, Gemma 3 270M Q4_K_M benchmark at 512 ctx. |
| F | AI Integration | Pending | Main Pi AI client, background requests only, deterministic fallback. |
| G | Telegram Admin | Pending | Polling bot, CRUD/control commands, user whitelist. |

## Blockers Before Hardware Stages

- Pi 3B+ display model and driver confirmation.
- Pi 3B+ headless smoke test.
- Pi 3B AI baseline RAM/swap/temp measurements.
- Gemma benchmark acceptance before any AI integration claim.
