#!/usr/bin/env bash
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/ai_common.sh"

INTERVAL=${JIRI_AI_MONITOR_INTERVAL:-5}
SAMPLES=${JIRI_AI_MONITOR_SAMPLES:-12}

print_host_mode
i=1
while test "$i" -le "$SAMPLES"; do
  echo "sample=$i date=$(date -Is) mem_available_mb=$(mem_available_mb) swap_used_mb=$(swap_used_mb) cpu_temp_c=$(cpu_temp_c)"
  ps -eo pid,pcpu,pmem,rss,comm,args --sort=-rss | sed -n '1,6p' || true
  if pgrep -f llama-server >/dev/null 2>&1 || false; then
    echo "llama-server: running"
  else
    echo "llama-server: not-running"
  fi
  i=$((i + 1))
  if test "$i" -le "$SAMPLES"; then
    sleep "$INTERVAL"
  fi
done
