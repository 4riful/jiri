from __future__ import annotations

from pathlib import Path
import os


def free_ram_mb() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            return int(int(parts[1]) / 1024)
    return None


def cpu_temperature_c() -> float | None:
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip()) / 1000
    except ValueError:
        return None


def is_raspberry_pi() -> bool:
    model = Path("/proc/device-tree/model")
    if not model.exists():
        return False
    try:
        return "Raspberry Pi" in model.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def process_id() -> int:
    return os.getpid()
