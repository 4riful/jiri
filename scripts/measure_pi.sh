#!/usr/bin/env bash
set -eu
test -r /sys/class/thermal/thermal_zone0/temp && awk '{print "CPU temp C: " $1/1000}' /sys/class/thermal/thermal_zone0/temp || true
grep MemAvailable /proc/meminfo || true
ps -o pid,pcpu,pmem,rss,comm,args -C python || true
df -h .
systemctl --no-pager --full status jiri-web.service || true
systemctl --no-pager --full status jiri-ui.service || true
