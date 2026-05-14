#!/usr/bin/env bash
set -eu

is_raspberry_pi() {
  test -r /proc/device-tree/model && tr -d '\000' </proc/device-tree/model | grep -q "Raspberry Pi"
}

is_wsl() {
  grep -qi "microsoft\|wsl" /proc/version 2>/dev/null
}

print_host_mode() {
  if is_raspberry_pi; then
    echo "host: raspberry-pi"
  elif is_wsl; then
    echo "host: wsl"
  else
    echo "host: unknown-linux"
  fi
}

local_dev_enabled() {
  test "${JIRI_LOCAL_DEV:-0}" = "1"
}

require_real_pi() {
  if ! is_raspberry_pi; then
    echo "Refusing: this benchmark action requires real Raspberry Pi hardware." >&2
    echo "This script is safe to inspect in WSL but acceptance requires the real Pi 3B." >&2
    exit 2
  fi
}

require_real_pi_or_local_dev() {
  if is_raspberry_pi; then
    return 0
  fi
  if local_dev_enabled; then
    echo "local_dev: JIRI_LOCAL_DEV=1 allows off-Pi Gemma ctx512 development only." >&2
    echo "local_dev: this does not satisfy Raspberry Pi 3B benchmark acceptance." >&2
    return 0
  fi
  echo "Refusing: this AI action requires real Raspberry Pi hardware by default." >&2
  echo "Set JIRI_LOCAL_DEV=1 only for local Gemma ctx512 development; acceptance still requires the real Pi 3B." >&2
  exit 2
}

cpu_temp_c() {
  if test -r /sys/class/thermal/thermal_zone0/temp; then
    awk '{print $1/1000}' /sys/class/thermal/thermal_zone0/temp
  else
    echo "unknown"
  fi
}

mem_available_mb() {
  awk '/MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo "0"
}

swap_used_mb() {
  awk '
    /SwapTotal:/ {total=$2}
    /SwapFree:/ {free=$2}
    END {if (total == "") print 0; else printf "%d", (total-free)/1024}
  ' /proc/meminfo 2>/dev/null || echo "0"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}
