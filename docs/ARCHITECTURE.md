# Architecture

JIRI separates deterministic core behavior from hardware-specific presentation.

## Layers

- `config.py`: defaults, TOML loading, and environment overrides.
- `db.py`: SQLite connection, schema creation, and small query helpers.
- `models.py`: shared dataclasses and typed snapshots.
- `todos.py`: todo lifecycle and overdue/angry-level logic.
- `notes.py`: shared notes logic.
- `mood.py`: deterministic mood mapping from todo state.
- `messages.py`: deterministic funny messages.
- `weather.py`: Open-Meteo weather, location lookup, cache, and fallback logic.
- `health.py`: health checks and high-level status assembly.
- `system_info.py`: lightweight Pi/system inspection helpers.
- `main.py`: application orchestration.
- `cli.py`: SSH-friendly control interface.
- `ui/`: Pygame and mock display code, kept separate from business logic.
- `web/`: Flask dashboard, kept separate from the 3.5-inch display.

## Reliability Rules

- SQLite is the source of truth for important state.
- UI code reads small snapshots only.
- Network calls never happen in the UI draw loop.
- Weather must use cache and fallback behavior.
- Logs and writes must be conservative for SD card safety.
- Web requests must stay lightweight and deterministic.
- Future AI calls must stay outside the render path and never write state directly.
