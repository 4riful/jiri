# WSL Development

Use WSL for deterministic code, CLI, web, and tests. Do not assume Pi display hardware exists.

Recommended environment:

```bash
export PYTHONPATH=src
export JIRI_DISPLAY_DRIVER=mock
export JIRI_FULLSCREEN=false
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_WEATHER_FAKE=true
export JIRI_DB_PATH=data/jiri_dev.db
```

Run tests:

```bash
scripts/test_wsl.sh
```

Run browser surfaces separately:

```bash
scripts/run_admin.sh
scripts/run_screen.sh
```

- Admin dashboard: `http://127.0.0.1:5000/admin`, password `test` unless `JIRI_ADMIN_PASSWORD` is set.
- Screen preview: `http://127.0.0.1:5001/screen`.
- Keep these surfaces distinct; the screen preview is not the admin dashboard.

Useful smoke checks:

```bash
python -m jiri.cli init-db
python -m jiri.cli status
python -m jiri.cli weather test-providers
```

WSL-safe areas:

- Database schema.
- Todo and note logic.
- Mood and messages.
- Config loading.
- CLI behavior.
- Weather parsing and fallback.
- Flask routes once Stage B starts.

WSL is for logic and integration checks only. Real display behavior, thermals, and benchmark results still need Raspberry Pi hardware.

## AI Wording Layer

The AI layer can be developed entirely in WSL. It needs no special hardware
because nothing runs locally — it calls hosted APIs from a background worker.

- Set `GEMINI_API_KEY` and/or `GROQ_API_KEY` to exercise real calls.
- Leave `[ai].enabled = false` to develop against the deterministic path.
- `tests/test_ai.py` covers the whole layer with no network access.
- WSL results satisfy AI_SPEC Gate 1 only. Gate 3 requires real Pi 3B+.

