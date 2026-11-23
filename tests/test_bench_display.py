from __future__ import annotations

import importlib.util
import math
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_display.py"


def _load():
    spec = importlib.util.spec_from_file_location("bench_display", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bench_runs_every_screen_for_one_simulated_second():
    bench = _load()
    results = bench.run_bench(seconds=1.0, fps=12.0)
    assert [r["screen"] for r in results] == list(bench.SCREENS)
    for r in results:
        assert r["frames"] == 12
        assert math.isfinite(r["render"]["mean"]) and r["render"]["max"] >= r["render"]["mean"] >= 0
        assert 0 <= r["bands_mean"] <= 320 // bench.output.BAND_ROWS
        assert r["bytes"]["bands"] <= r["bytes"]["span"] <= r["bytes"]["full"]
    text = bench.report(results, 12.0, 12.0, 0.8)
    assert "32MHz" in text and "splash" in text
