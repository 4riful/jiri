# JIRI Agent Instructions

These rules are mandatory for future Codex sessions working on JIRI.

- Target hardware is Raspberry Pi 3B/3B+.
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
- Do not add an LLM until the deterministic non-AI assistant works and passes the 24-hour stability gate.
- If an LLM is added later, it may only rewrite reminder messages and must never manage state, todos, reminders, due dates, database writes, weather cache, or system state.
- Do not assume the display works in WSL.
- Every stage must have tests or smoke checks.
- If hardware behavior is unknown, create a Pi confirmation checklist instead of guessing.
- Do not move to the next stage until the current stage gate is satisfied.
- Never write to SQLite from the UI frame loop.
- Avoid frequent SD card writes and noisy logs.
- Keep target UI FPS at 10 to 15 FPS.
- Load fonts and reusable UI resources once.
- Back up SQLite before schema changes once real data exists.
