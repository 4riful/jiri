# Pi Deployment

Raspberry Pi OS (Bookworm or later) on a Pi 3B/3B+, logged in as the user that
will run JIRI. Status of each Pi gate is in `docs/STATUS.md`.

## 1. Install

```bash
git clone https://github.com/4riful/jiri.git
cd jiri
scripts/install_pi.sh
```

`install_pi.sh` installs the apt packages pygame and the display fonts need,
creates `.venv`, installs `requirements.txt`, initialises `data/jiri.db`, and
writes `.env` with a generated `JIRI_ADMIN_PASSWORD` (printed once).

## 2. Secrets (`.env`)

Fill in at least one AI provider; everything else is optional.

| Variable | Purpose |
| --- | --- |
| `JIRI_ADMIN_PASSWORD` | Admin login. Required; with none every login is refused. |
| `FREELLM_BASE_URL`, `FREELLM_API_KEY`, `FREELLM_MODEL` | First AI provider. |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | Fallback AI providers. |
| `JIRI_USAGE_TOKEN` | Enables laptop usage pushes to `POST /api/usage`. |
| `JIRI_TELEGRAM_BOT_TOKEN`, `JIRI_TELEGRAM_ALLOWED_CHAT_IDS` | Seeds the Telegram bot. |
| `JIRI_TOUCH_CAL`, `JIRI_FB_DEVICE` | Panel calibration and framebuffer, from the checklist. |

## 3. Panel

Work through `docs/PI_DISPLAY_CHECKLIST.md` (overlay, framebuffer, rotation,
touch). Try the UI by hand before installing services:

```bash
JIRI_DISPLAY_OUTPUT=fb JIRI_FB_DEVICE=/dev/fb1 scripts/run_ui.sh
```

## 4. Services

```bash
scripts/create_systemd_services.sh --dry-run   # inspect the rendered units
scripts/create_systemd_services.sh             # install, enable, start
```

This installs two units, rewritten for the current user and checkout:

- `jiri-web.service`: admin, APIs and the `/screen` preview on `0.0.0.0:5000`
  (login required), plus the background workers (minute tick, AI refill).
- `jiri-ui.service`: the pygame display, writing the SPI framebuffer, with the
  `video` and `input` groups for `/dev/fb*` and `/dev/input/*`.

Telegram is not a unit yet; run `scripts/run_telegram.sh` (for example in
`tmux`) once a bot token and allowlist are set.

## 5. Check

```bash
scripts/pi_smoke_test.sh     # imports, DB, CLI round trip, RAM, temperature, disk
scripts/measure_pi.sh        # numbers for docs/PERFORMANCE_BUDGETS.md
journalctl -u jiri-web -u jiri-ui -n 50 --no-pager
```

From a laptop, `http://<pi-ip>:5000/screen` shows exactly what the panel draws.

## Rules

- Back up SQLite (`scripts/backup_db.sh`) before any schema change or update;
  see `docs/SAFE_UPDATE_METHODOLOGY.md`.
- Cached and built-in wording keep the device working when providers are down;
  a missing key is not a reason for the display to fail.
