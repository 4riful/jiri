# Status

Where JIRI stands against the gates in `docs/ENGINEERING_HANDBOOK.md`. This
replaces the old `ROADMAP.md`, `MISSION_CONTROL.md`, `STAGE_GATES.md` and
`STABILITY_TEST.md`. Update it when a gate changes, not when code changes.

"Passed in WSL" means the software gate passes (`scripts/test_wsl.sh`). It is
development evidence only; Pi acceptance is listed separately.

## Stages

| Stage | Scope | Software (WSL/CI) | On the Pi |
| --- | --- | --- | --- |
| A Core | Config, SQLite, todos, notes, water, CLI | Passed | Smoke test pending (`scripts/pi_smoke_test.sh`) |
| W Weather | Open-Meteo, wttr.in, cache, explicit geocoding | Passed | Pending |
| B Web admin | Flask admin, JSON APIs, login, CSRF, surfaces | Passed | Response and RAM budgets pending |
| C Focus | Sessions, pause/resume, checkpoint writes, milestones | Passed | Pending |
| D Display | Pygame face, six screens, pet, touch, framebuffer output | Passed (headless render, read-only path) | **Blocked on the panel**: `docs/PI_DISPLAY_CHECKLIST.md` |
| P Persona | Moments, quiet hours, cooldowns, proactive nudges | Passed | Rides on D |
| E AI wording | Hosted providers, cache-only render, refill worker | Gate 1 passed | Gate 2 (real keys) and Gate 3 (Pi) pending: `docs/AI_SPEC.md` §5 |
| G Telegram | Polling bot, allowlist, confirmations | Passed | Needs a real bot token and chat allowlist |
| U Updates | Backup/restore scripts, read-only update check | Passed | Auto-update stays off until Pi smoke acceptance |
| S Stability | 24-hour soak, all services | - | Last; after every other Pi gate |

## Next

1. Fill in `docs/PI_DISPLAY_CHECKLIST.md` on the real panel (controller,
   framebuffer, rotation, touch calibration, redraw rate).
2. Install with `scripts/install_pi.sh` and
   `scripts/create_systemd_services.sh`; run `scripts/pi_smoke_test.sh` and
   `scripts/measure_pi.sh` against `docs/PERFORMANCE_BUDGETS.md`.
3. AI Gate 2 with real provider keys, then Gate 3 on the Pi.
4. The 24-hour stability soak.

## Pi facts still unconfirmed

Record the answers here as they come in.

- Raspberry Pi OS version, 32- or 64-bit.
- Power supply stability (`vcgencmd get_throttled`).
- SD card health and free space.
- Idle CPU temperature and free RAM after boot.
- Everything in `docs/PI_DISPLAY_CHECKLIST.md`.

Read-only commands that answer most of these:

```bash
cat /proc/device-tree/model
cat /etc/os-release
uname -a
free -h
df -h
vcgencmd measure_temp
vcgencmd get_throttled
```

## Stability soak (stage S)

Run only after the display, web, AI and Telegram gates pass on the Pi. With
all services up for 24 hours: no crash or restart loop, no unbounded growth in
RSS, database size or the AI daily counter, the display keeps 10-15 FPS, and
pulling the network shows no visible error.
