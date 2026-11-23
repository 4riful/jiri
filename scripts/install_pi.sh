#!/usr/bin/env bash
# Install JIRI on Raspberry Pi OS (Pi 3B/3B+). Run from the repo root as the
# `pi` user; uses sudo only for apt.
set -eu

# Fonts: Fira Code is JIRI's display font (terminal look + the block glyphs the
# usage gauges use). DejaVu is the fallback and ships with Pi OS already.
# python3-venv/SDL bits are what pygame's wheels need at runtime.
sudo apt-get update -q
sudo apt-get install -y -q fonts-firacode fonts-dejavu-core python3-venv libsdl2-2.0-0 libsdl2-ttf-2.0-0

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m jiri.cli init-db

GENERATED_ADMIN_PASSWORD=""
if [ ! -f .env ]; then
  umask 077
  GENERATED_ADMIN_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')"
  cat > .env <<ENV
# Secrets for JIRI. Never commit this file.
FREELLM_BASE_URL=""
FREELLM_API_KEY=""
FREELLM_MODEL="qwen3.8-27b"
JIRI_ADMIN_PASSWORD="${GENERATED_ADMIN_PASSWORD}"
ENV
  echo "Created .env - fill in FREELLM_*."
elif ! grep -Eq '^JIRI_ADMIN_PASSWORD="?[^"[:space:]]' .env; then
  # Existing .env from an older install with an empty password: the admin
  # refuses all logins until one is set, so generate it now.
  GENERATED_ADMIN_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_urlsafe(12))')"
  sed -i '/^JIRI_ADMIN_PASSWORD=/d' .env
  printf 'JIRI_ADMIN_PASSWORD="%s"\n' "$GENERATED_ADMIN_PASSWORD" >> .env
fi

echo "Next: configure the SPI panel (docs/PI_DISPLAY_CHECKLIST.md), then install the systemd units."

if [ -n "$GENERATED_ADMIN_PASSWORD" ]; then
  echo
  echo "Admin dashboard password (shown once; also stored in .env as JIRI_ADMIN_PASSWORD):"
  echo "  $GENERATED_ADMIN_PASSWORD"
fi
