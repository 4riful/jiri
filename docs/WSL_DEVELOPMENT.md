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

WSL-safe areas:

- Database schema.
- Todo and note logic.
- Mood and messages.
- Config loading.
- CLI behavior.
- Weather parsing and fallback once Stage 2 starts.
- Flask routes once Stage 4 starts.
