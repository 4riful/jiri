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
