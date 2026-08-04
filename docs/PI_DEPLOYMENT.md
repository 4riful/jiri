# Pi Deployment

Deploy to Raspberry Pi only after the relevant gates pass in `docs/STAGE_GATES.md`.

Initial headless direction:

```bash
git clone <repo-url> jiri
cd jiri
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
python -m jiri.cli init-db
python -m jiri.cli health
```

Production defaults should use:

```bash
export JIRI_DISPLAY_DRIVER=pygame
export JIRI_FULLSCREEN=true
export JIRI_WIDTH=480
export JIRI_HEIGHT=320
export JIRI_DB_PATH=data/jiri.db
```

Deployment rules:

- Confirm the real 3.5-inch display before enabling fullscreen services.
- Keep the main Pi fully functional with the AI layer disabled or offline.
- Back up SQLite before schema changes once real data exists.
- Install systemd units only after the relevant stage gate passes.
