"""Background AI refill worker.

A single daemon thread in the long-running web process that calls
`runtime.ai_refill()` every N minutes. It is the only automatic trigger for
network AI work (see docs/AI_SPEC.md §"Refill trigger"):

- never runs on the pygame UI thread (the UI process does not start it);
- never raises out of the loop: every failure is logged once and swallowed,
  the cache and deterministic strings keep serving;
- stoppable via an Event, so tests and shutdown do not hang.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable

log = logging.getLogger(__name__)

# First run waits briefly so the web server is listening before any network
# work starts, and so a crash-looping service does not hammer the provider.
INITIAL_DELAY_SECONDS = 30.0


class AiRefillWorker:
    def __init__(
        self,
        refill: Callable[[], object],
        *,
        interval_seconds: float,
        initial_delay_seconds: float = INITIAL_DELAY_SECONDS,
    ) -> None:
        self._refill = refill
        self._interval = max(1.0, float(interval_seconds))
        self._initial_delay = max(0.0, float(initial_delay_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.runs = 0
        # In-memory run telemetry for the admin page. Nothing here touches disk.
        self.last_started_at: datetime | None = None
        self.last_finished_at: datetime | None = None
        self.last_duration_s: float | None = None
        self.last_result: object = None
        self.last_error: str | None = None
        self.next_run_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> "AiRefillWorker":
        if self.running:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jiri-ai-refill", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def run_once(self) -> object:
        self.runs += 1
        self.last_started_at = datetime.now()
        started = time.monotonic()
        try:
            result = self._refill()
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            log.warning("Background task %s failed: %s", getattr(self._refill, "__name__", "?"), exc.__class__.__name__)
            self.last_error = exc.__class__.__name__
            self.last_result = None
            self.last_finished_at = datetime.now()
            self.last_duration_s = round(time.monotonic() - started, 2)
            return None
        self.last_error = None
        self.last_result = result
        self.last_finished_at = datetime.now()
        self.last_duration_s = round(time.monotonic() - started, 2)
        if isinstance(result, dict) and result.get("calls"):
            log.info("AI refill: calls=%s stored=%s", result.get("calls"), result.get("stored"))
        return result

    def _loop(self) -> None:
        self.next_run_at = datetime.now() + timedelta(seconds=self._initial_delay)
        if self._stop.wait(self._initial_delay):
            return
        while not self._stop.is_set():
            self.run_once()
            self.next_run_at = datetime.now() + timedelta(seconds=self._interval)
            if self._stop.wait(self._interval):
                return

    def snapshot(self) -> dict[str, object]:
        """Run telemetry for the admin page (JSON-safe)."""
        result = self.last_result if isinstance(self.last_result, dict) else {}
        def iso(value: datetime | None) -> str | None:
            return value.isoformat(timespec="seconds") if value else None
        return {
            "running": self.running,
            "interval_minutes": round(self._interval / 60, 1),
            "runs": self.runs,
            "last_started_at": iso(self.last_started_at),
            "last_finished_at": iso(self.last_finished_at),
            "last_duration_s": self.last_duration_s,
            "last_error": self.last_error,
            "last_calls": result.get("calls"),
            "last_stored": result.get("stored"),
            "last_skipped": result.get("skipped"),
            "next_run_at": iso(self.next_run_at) if self.running else None,
            "next_run_in_s": (
                max(0, int((self.next_run_at - datetime.now()).total_seconds()))
                if self.running and self.next_run_at else None
            ),
        }


# The refill worker of this process, if one was started. Read by the admin
# page (same process) so it can show when the worker last ran and what it did.
_refill_worker: AiRefillWorker | None = None


def refill_worker_status() -> dict[str, object] | None:
    worker = _refill_worker
    return worker.snapshot() if worker is not None else None


def start_for_runtime(runtime) -> AiRefillWorker | None:
    """Start the worker for a JiriRuntime, or return None if disabled."""
    minutes = int(getattr(runtime.config.ai, "refill_interval_minutes", 0) or 0)
    if minutes <= 0:
        return None
    global _refill_worker
    _refill_worker = AiRefillWorker(runtime.ai_refill, interval_seconds=minutes * 60).start()
    return _refill_worker


TICK_INTERVAL_SECONDS = 60.0


def start_background(runtime) -> list[AiRefillWorker]:
    """Start every background loop the web process owns.

    - `tick_background` every minute: weather refresh (network), finishing
      expired focus sessions, water day rollover, persona events. The display
      path is read-only, so without this tick the face would go stale.
    - AI wording refill every `refill_interval_minutes`.
    - Usage-limit poll for directly signed-in accounts every 5 min (no-op,
      no network and no writes when no account is connected).
    """
    from jiri import usage_accounts

    db_path = runtime.db_path

    def usage_poll() -> object:
        return usage_accounts.poll_all(db_path)

    workers = [
        AiRefillWorker(runtime.tick_background, interval_seconds=TICK_INTERVAL_SECONDS, initial_delay_seconds=5.0).start(),
        AiRefillWorker(
            usage_poll, interval_seconds=usage_accounts.POLL_INTERVAL_SECONDS, initial_delay_seconds=20.0
        ).start(),
    ]
    refill = start_for_runtime(runtime)
    if refill is not None:
        workers.append(refill)
    return workers
