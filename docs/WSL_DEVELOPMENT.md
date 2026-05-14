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
- Local Gemma ctx512 preflight when explicitly enabled.

WSL is for logic and integration checks only. Real display behavior, thermals, and benchmark results still need Raspberry Pi hardware.

## Local Gemma Preflight

Local Gemma development may be used to complete Pi-oriented implementation work before hardware is ready.

Rules:

- Set `JIRI_LOCAL_DEV=1` explicitly for off-Pi Gemma run/benchmark scripts.
- Keep context at 512 tokens and output short enough for Pi 3B planning.
- Keep AI disabled by default in app config until real Pi acceptance passes.
- Do not treat WSL/local latency, RAM, or thermal behavior as acceptance.
- Compare the same scripts later on Raspberry Pi 3B for RAM, swap, temperature, latency, SSH responsiveness, and fallback behavior.

Example local preflight commands:

```bash
export JIRI_LOCAL_DEV=1
export JIRI_GEMMA_MODEL="$HOME/models/gemma-3-270m-q4_k_m.gguf"
scripts/ai_run_gemma_512.sh
scripts/ai_benchmark_gemma.sh
```
