# Performance Budgets

All numbers are for a Raspberry Pi 3B/3B+ and must be measured there
(`scripts/measure_pi.sh`). WSL numbers do not count.

## Memory and CPU

| Budget | Target | Hard limit |
| --- | --- | --- |
| UI process RSS (idle) | under 180 MB | 250 MB |
| Web process RSS (idle) | under 100 MB | 150 MB |
| All JIRI processes | under 350 MB | |
| CPU, idle average | under 15% | 30% |
| CPU temperature | under 70 C during an AI refill | 75 C |

## Display

- 10 to 15 FPS (`display.fps`, clamped to that range).
- Snapshot read once a second; the frame loop never does HTTP, never writes
  SQLite, never runs a slow query.
- An unchanged frame writes nothing to the SPI framebuffer.
- Fonts and reusable resources are loaded once.

## Network (background only)

| Call | Timeout | Where it runs |
| --- | --- | --- |
| Weather (Open-Meteo, wttr.in, geocoding) | 3 s, enforced by config validation | minute tick in the web process, or an explicit user action |
| AI provider request | 15 s (`ai.timeout_seconds`) | AI refill worker in the web process |
| Telegram long poll | 25 s (`telegram.polling_timeout_seconds`) | Telegram process |
| Laptop usage push | 3 s | the laptop |

The AI timeout bounds how long the worker thread can stall; it is not on any
path a user waits on. The render path reads `ai_cache` only, in under 5 ms.

## Responses

- `GET /api/status`, `GET /admin/todos`: under 500 ms.
- `POST /admin/todos`: under 800 ms.
- Telegram command reply: under 2 s.

## Startup and storage

- UI ready under 30 s after the service starts; boot to ready under 90 s.
- Database under 50 MB; `ai_cache` adds under 5 MB at its configured maximum.
- Logs are quiet by default (`JIRI_WEB_QUIET`) and never per frame.
