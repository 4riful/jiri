# WSL Development

WSL is for logic, web and headless rendering. It is not the target: never tune
for its CPU or RAM, and never assume the SPI panel exists.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
echo 'JIRI_ADMIN_PASSWORD="pick-something"' >> .env
PYTHONPATH=src .venv/bin/python -m jiri.cli init-db
```

## Run

| Command | What you get |
| --- | --- |
| `scripts/run_all.sh` | Admin on `http://127.0.0.1:5000/admin` plus screen preview on `http://127.0.0.1:5001/screen` (loopback only). `JIRI_DEV=1` hot-reloads templates. Restart it after Python edits. |
| `scripts/run_ui.sh` | The real pygame display in a 480x320 window (needs WSLg). Click = tap. |
| `scripts/run_admin.sh`, `scripts/run_screen.sh` | One surface each. |
| `PYTHONPATH=src .venv/bin/python scripts/render_preview.py OUT_DIR` | Every mood rendered headless to PNGs plus `sheet.png`; `--live` renders the current database. |
| `PYTHONPATH=src .venv/bin/python scripts/seed_demo.py` | Demo todos, water and focus (backs up the DB first; `--reset-demo` removes them). |

If ports are taken: `JIRI_ADMIN_PORT=5100 JIRI_SCREEN_PORT=5101 scripts/run_all.sh`.

Only `run_all.sh`/`run_admin.sh` (the web process) runs the background minute
tick and AI refill. The screen preview and the pygame window are read-only, so
weather and the AI voice only refresh while the admin is running.

## Test

```bash
.venv/bin/python -m pytest -q      # the suite; no real network calls
scripts/test_wsl.sh                # the full gate: suite + CLI walkthrough + headless pygame
```

`test_wsl.sh` uses the mock display, fake weather and a throwaway database
(`data/jiri_test_wsl.db`).

## AI providers

Nothing runs locally; the layer calls hosted APIs from the refill worker, so
WSL exercises it fully. Put `FREELLM_*`, `GEMINI_API_KEY` or `GROQ_API_KEY` in
`.env` to make real calls (the admin's AI page has a manual refill). Tests
never read `.env` and inject every HTTP response. WSL covers AI Gate 1 only;
Gate 3 needs the Pi (`docs/AI_SPEC.md` §5).
