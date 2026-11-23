#!/usr/bin/env bash
# Install JIRI's systemd units on the Pi.
#
#   scripts/create_systemd_services.sh            # install, enable and start
#   scripts/create_systemd_services.sh --dry-run  # print the rendered units only
#
# The unit files in systemd/ are written for user `pi` in /home/pi/jiri; this
# rewrites both to the invoking user and this checkout before installing.
#   jiri-web.service  admin + /screen preview (login required) on :5000, and the
#                     background workers (minute tick, AI refill)
#   jiri-ui.service   the pygame display, straight to the SPI framebuffer
set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER=${JIRI_USER:-${SUDO_USER:-$(id -un)}}
UNITS="jiri-web.service jiri-ui.service"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

render() {
  sed -e "s#/home/pi/jiri#${ROOT_DIR}#g" -e "s#^User=pi\$#User=${RUN_USER}#" "$ROOT_DIR/systemd/$1"
}

if [ "$DRY_RUN" = 1 ]; then
  for unit in $UNITS; do
    printf '# ---- /etc/systemd/system/%s\n' "$unit"
    render "$unit"
  done
  exit 0
fi

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
  echo "No .venv in $ROOT_DIR - run scripts/install_pi.sh first." >&2
  exit 1
fi
if ! grep -Eq '^JIRI_ADMIN_PASSWORD="?[^"[:space:]]' "$ROOT_DIR/.env" 2>/dev/null; then
  echo "JIRI_ADMIN_PASSWORD is not set in $ROOT_DIR/.env - the admin would refuse every login." >&2
  exit 1
fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO=sudo
for unit in $UNITS; do
  render "$unit" | $SUDO tee "/etc/systemd/system/$unit" >/dev/null
  echo "Installed /etc/systemd/system/$unit"
done
$SUDO systemctl daemon-reload
# shellcheck disable=SC2086
$SUDO systemctl enable --now $UNITS
# shellcheck disable=SC2086
systemctl --no-pager --lines=0 status $UNITS || true
