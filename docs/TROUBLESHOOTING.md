# Troubleshooting

## `ModuleNotFoundError: jiri`

Run through the scripts (they set `PYTHONPATH=src`) or export it yourself.
Tests do not need it; `tests/conftest.py` adds `src/`.

## Admin login always fails

`JIRI_ADMIN_PASSWORD` is unset, empty or a known-weak value. Set it in `.env`
and restart the web process. There is no default password.

## Port already in use

`scripts/run_all.sh` stops JIRI processes it started before. Anything else on
the port is left alone; pick other ports with `JIRI_ADMIN_PORT` /
`JIRI_SCREEN_PORT`.

## The face or weather looks stale

Only the web process (`jiri-web` / `run_all.sh` / `run_admin.sh`) runs the
minute tick and the AI refill. If it is down, the display keeps showing the
last data it read.

## JIRI only says the built-in lines

The AI cache is empty for that bucket. Check the admin's AI page for provider
errors, the daily cap and the circuit breaker. A fresh install needs about 30 s
after the web process starts before the first refill.

## Display does not work in WSL

Use `scripts/render_preview.py` or the `/screen` preview, or `scripts/run_ui.sh`
with WSLg. Real panel behaviour is only known on the Pi
(`docs/PI_DISPLAY_CHECKLIST.md`).

## Weather shows unavailable

`python -m jiri.cli weather test-providers` checks reachability. JIRI falls
back from Open-Meteo to wttr.in to the cached reading. Set a location first
(`jiri.cli location search ...` then `location set N`).

## Missing config

Safe defaults apply when `config.toml` is absent. Copy `config.example.toml`
to `config.toml` only to change something. Unknown keys fail loudly.

## Database missing

Normal commands create the schema. `python -m jiri.cli init-db` does it
explicitly.
