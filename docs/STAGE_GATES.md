# Stage Gates

## Stage 0: Planning And Repo Setup

Build:

- Repository structure.
- Documentation.
- `AGENTS.md`.
- Config example.
- Requirements.

WSL confirmation:

- Python import checks pass.
- No Pi-only code required.

Gate 0 pass condition:

- Repository structure exists.
- README explains WSL and Pi deployment split.
- AGENTS.md contains all guardrails.

## Stage 1: Core Logic, No UI

Build:

- Config loader.
- SQLite schema.
- Todos.
- Notes.
- Mood calculation.
- Deterministic funny messages.
- Unit tests.

Gate 1 pass condition:

- Pytest passes on WSL.
- CLI can add/list/done todos in WSL.
- Database can be deleted and recreated safely.

## Later Stages

Stages 2 through 12 are intentionally deferred until the prior gate is confirmed. See `README.md` and project prompt for detailed later-stage requirements.
