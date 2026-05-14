from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def test_required_ai_scripts_exist_and_are_guarded():
    required = [
        "ai_common.sh",
        "ai_baseline.sh",
        "ai_safe_debloat.sh",
        "ai_monitor.sh",
        "ai_run_gemma_512.sh",
        "ai_benchmark_gemma.sh",
    ]
    for name in required:
        path = SCRIPTS / name
        assert path.exists(), name
        text = path.read_text(encoding="utf-8")
        assert "#!/usr/bin/env bash" in text
        assert "set -eu" in text

    run_text = (SCRIPTS / "ai_run_gemma_512.sh").read_text(encoding="utf-8")
    benchmark_text = (SCRIPTS / "ai_benchmark_gemma.sh").read_text(encoding="utf-8")
    debloat_text = (SCRIPTS / "ai_safe_debloat.sh").read_text(encoding="utf-8")
    assert "require_real_pi" in run_text
    assert "require_real_pi" in benchmark_text
    assert "JIRI_CONFIRM_DEBLOAT" in debloat_text
    assert "SSH" in debloat_text


def test_ai_baseline_runs_in_wsl_without_modifying_system():
    result = subprocess.run([str(SCRIPTS / "ai_baseline.sh")], cwd=ROOT, check=True, text=True, capture_output=True)
    assert "host:" in result.stdout
    assert "mem_available_mb:" in result.stdout
    assert "top_memory_processes:" in result.stdout


def test_ai_safe_debloat_defaults_to_dry_run():
    result = subprocess.run([str(SCRIPTS / "ai_safe_debloat.sh")], cwd=ROOT, check=True, text=True, capture_output=True)
    assert "dry_run" in result.stdout
    assert "would_disable_if_present" in result.stdout


def test_ai_monitor_can_run_single_wsl_sample():
    result = subprocess.run(
        [str(SCRIPTS / "ai_monitor.sh")],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
        env={"JIRI_AI_MONITOR_SAMPLES": "1", "JIRI_AI_MONITOR_INTERVAL": "1", **__import__("os").environ},
    )
    assert "sample=1" in result.stdout
    assert "llama-server:" in result.stdout
