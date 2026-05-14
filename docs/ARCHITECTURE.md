# Architecture

JIRI separates deterministic core behavior from hardware-specific presentation.

## Layers

- `config.py`: defaults, TOML loading, and environment overrides.
- `db.py`: SQLite connection, schema creation, and small query helpers.
- `todos.py`: todo lifecycle and overdue/angry-level logic.
- `notes.py`: shared notes logic.
- `mood.py`: deterministic mood mapping from todo state.
- `messages.py`: deterministic funny messages.
- `weather.py`: Stage 2 cache/fetch placeholder in this stage.
- `cli.py`: SSH-friendly control interface.
- `ui/`: Pygame and mock display code, kept separate from business logic.
- `web/`: Flask dashboard, introduced in Stage 4.

## Reliability Rules

- SQLite is the source of truth for important state.
- UI code reads small snapshots only.
- Network calls never happen in the UI draw loop.
- Weather must use cache and fallback behavior.
- Logs and writes must be conservative for SD card safety.
