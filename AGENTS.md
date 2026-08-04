# JIRI Agent Instructions

These rules are mandatory for future Codex sessions working on JIRI.

- `docs/ENGINEERING_HANDBOOK.md` is the source-of-truth design and gate document.
- Target hardware is Raspberry Pi 3B/3B+.
- Final architecture uses a single Raspberry Pi 3B/3B+ with optional on-device AI.
- Development happens in WSL, but production is Raspberry Pi OS.
- Do not optimize for desktop-class WSL hardware.
- Do not add heavy dependencies.
- Do not add React, Electron, Docker, Kubernetes, or Node.js in v1.
- Do not add PostgreSQL, MongoDB, Redis, Celery, or browser kiosk display UI in v1.
- Keep Pygame UI separate from business logic.
- Keep database operations separate from UI rendering.
- Keep all network requests out of the UI draw loop.
- Use timeouts for every network request.
- Keep offline fallback behavior.
- On-device LLM inference is rejected for Pi 3B+ hardware; see docs/AI_STRATEGY.md. Do not reopen it.
- The AI wording layer is API-driven, background only, and off by default; see docs/AI_SPEC.md.
- Do not enable or claim production AI integration until the deterministic main app and real Pi AI benchmark gates pass.
- If AI is added later, it may only rewrite/summarize from Python-supplied facts and must never manage state, todos, reminders, due dates, focus timers, database writes, weather facts, weather cache, system state, shell commands, or systemd.
- Do not assume the display works in WSL.
- Every stage must have tests or smoke checks.
- If hardware behavior is unknown, create a Pi confirmation checklist instead of guessing.
- Do not move to the next stage until the current stage gate is satisfied.
- Never write to SQLite from the UI frame loop.
- Avoid frequent SD card writes and noisy logs.
- Keep target UI FPS at 10 to 15 FPS.
- Load fonts and reusable UI resources once.
- Back up SQLite before schema changes once real data exists.
- Keep the display as a living face and glance panel, not the admin dashboard.
- Keep the web dashboard separate from the 3.5-inch display.
- Telegram is later-stage admin control; use polling first and whitelist users.
