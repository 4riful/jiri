#!/usr/bin/env bash
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/ai_common.sh"

print_host_mode
echo "Stage E safe debloat helper. Default mode is dry-run."
echo "Never disables SSH, networking, or avahi by default."

SERVICES="bluetooth cups ModemManager triggerhappy"
if test "${JIRI_CONFIRM_DEBLOAT:-0}" != "1"; then
  echo "dry_run: set JIRI_CONFIRM_DEBLOAT=1 on real Pi to disable optional services."
  for svc in $SERVICES; do
    echo "would_disable_if_present: $svc"
  done
  exit 0
fi

require_real_pi
if ! command_exists systemctl; then
  echo "systemctl unavailable" >&2
  exit 1
fi

for svc in $SERVICES; do
  if systemctl list-unit-files "$svc.service" >/dev/null 2>&1; then
    echo "disabling_optional_service: $svc"
    sudo systemctl disable --now "$svc.service" || true
  fi
done
