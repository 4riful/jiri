#!/usr/bin/env bash
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$SCRIPT_DIR/ai_common.sh"

print_host_mode
echo "date: $(date -Is)"
echo "kernel: $(uname -a)"
test -r /etc/os-release && sed -n '1,8p' /etc/os-release || true
echo "uptime: $(uptime || true)"
echo "cpu_temp_c: $(cpu_temp_c)"
echo "mem_available_mb: $(mem_available_mb)"
echo "swap_used_mb: $(swap_used_mb)"
echo "disk:"
df -h . || true
echo "top_memory_processes:"
ps -eo pid,pcpu,pmem,rss,comm,args --sort=-rss | sed -n '1,8p' || true
if command_exists systemctl; then
  echo "enabled_services:"
  systemctl list-unit-files --state=enabled --no-pager 2>/dev/null | sed -n '1,40p' || true
  echo "running_services:"
  systemctl list-units --type=service --state=running --no-pager 2>/dev/null | sed -n '1,40p' || true
else
  echo "systemctl: unavailable"
fi
