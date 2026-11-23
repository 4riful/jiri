"""AI call log, activity summary, and the admin AI usage surface.

No test here makes a real network call: `requests.post` is replaced.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from jiri import ai, ai_worker, db
from jiri.config import AiConfig, AiProviderConfig
from jiri.web import create_app

from conftest import login_client


def _db(tmp_path):
    path = str(tmp_path / "jiri.db")
    db.init_db(path)
    ai.ensure_schema(path)
    return path


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
        self.headers = {}


OK_BODY = (
    '{"choices":[{"message":{"content":"The desk is suspiciously calm.\\nNothing is on fire yet."}}],'
    '"usage":{"prompt_tokens":321,"completion_tokens":45,"total_tokens":366}}'
)


@pytest.fixture
def freellm_env(monkeypatch):
    for name in ("FREELLM_BASE_URL", "FREELLM_API_KEY", "FREELLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"JIRI_{name}", raising=False)
    monkeypatch.setenv("FREELLM_BASE_URL", "https://llm.example.test/")
    monkeypatch.setenv("FREELLM_API_KEY", "test-key")
    return monkeypatch


def test_successful_call_is_logged_with_tokens(tmp_path, freellm_env, monkeypatch):
    path = _db(tmp_path)
    monkeypatch.setattr(ai.requests, "post", lambda url, **kw: _Resp(OK_BODY))
    cfg = AiConfig(providers=(AiProviderConfig(name="freellm"),))
    result = ai.generate("ambient", "idle", config=cfg, personality="p", db_path=path)
    assert result["ok"]

    calls = ai.recent_calls(db_path=path)
    assert len(calls) == 1
    row = calls[0]
    assert row["ok"] == 1
    assert row["provider"] == "freellm"
    assert row["model"] == "qwen3.8-27b"
    assert (row["category"], row["mood"]) == ("ambient", "idle")
    assert row["returned"] == 2
    assert row["accepted"] == result["accepted"]
    assert row["stored"] == result["stored"] == 2
    assert row["prompt_tokens"] == 321
    assert row["completion_tokens"] == 45
    assert row["error"] is None
    assert row["latency_ms"] >= 0

    summary = ai.calls_summary(db_path=path)
    assert summary["attempts_today"] == 1
    assert summary["success_rate"] == 100
    assert summary["tokens_today"] == 366


def test_failed_attempts_are_logged_and_failover_logged(tmp_path, freellm_env, monkeypatch):
    path = _db(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "g")

    def fake_post(url, **kwargs):
        if "llm.example.test" in url:
            return _Resp("upstream exploded", status=502)
        # No usage block: tokens must stay NULL, not 0.
        return _Resp('{"choices":[{"message":{"content":"Quiet desk, loud thoughts."}}]}')

    monkeypatch.setattr(ai.requests, "post", fake_post)
    cfg = AiConfig(providers=(AiProviderConfig(name="freellm"), AiProviderConfig(name="groq")))
    result = ai.generate("ambient", "idle", config=cfg, personality="p", db_path=path)
    assert result["provider"] == "groq"

    calls = list(reversed(ai.recent_calls(db_path=path)))
    assert [c["provider"] for c in calls] == ["freellm"] * ai.MAX_ATTEMPTS_PER_PROVIDER + ["groq"]
    for failed in calls[:-1]:
        assert failed["ok"] == 0
        assert "HTTP 502" in failed["error"]
        assert len(failed["error"]) <= ai.CALL_ERROR_MAX_CHARS
        assert failed["stored"] == 0
    assert calls[-1]["ok"] == 1
    assert calls[-1]["prompt_tokens"] is None
    assert calls[-1]["completion_tokens"] is None

    summary = ai.calls_summary(db_path=path)
    assert summary["attempts_today"] == len(calls)
    assert summary["failed_today"] == ai.MAX_ATTEMPTS_PER_PROVIDER
    assert summary["tokens_today"] is None


def test_call_log_is_pruned_to_newest_rows(tmp_path, monkeypatch):
    path = _db(tmp_path)
    monkeypatch.setattr(ai, "CALL_LOG_KEEP", 5)
    for i in range(12):
        ai.log_call(provider="p", model="m", category=f"c{i}", mood="idle", ok=True, db_path=path)
    with db.connect(path) as conn:
        cats = [r["category"] for r in conn.execute("SELECT category FROM ai_calls ORDER BY id")]
    assert cats == [f"c{i}" for i in range(7, 12)]


def test_bucket_overview_flags_empty_wanted_buckets(tmp_path):
    path = _db(tmp_path)
    with db.connect(path) as conn:
        ai._record_demand(conn, "reminder", "rage", datetime.now())
    ai.store_lines("ambient", "idle", 0, ["Old line.", "New line."], provider="p", model="m", db_path=path)
    buckets = ai.bucket_overview(db_path=path)
    assert buckets[0]["category"] == "reminder" and buckets[0]["lines"] == 0
    ambient = next(b for b in buckets if b["category"] == "ambient")
    assert ambient["lines"] == 2
    assert ambient["newest"] in {"Old line.", "New line."}


def test_worker_snapshot_reports_last_run():
    worker = ai_worker.AiRefillWorker(lambda: {"calls": 2, "stored": 5}, interval_seconds=600)
    worker.run_once()
    snap = worker.snapshot()
    assert snap["last_calls"] == 2
    assert snap["last_stored"] == 5
    assert snap["last_finished_at"]
    assert snap["last_error"] is None


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    return create_app()


def test_ai_page_renders_usage(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    path = app.jiri_runtime.db_path  # type: ignore[attr-defined]
    ai.ensure_schema(path)
    ai.log_call(provider="freellm", model="qwen3.8-27b", category="ambient", mood="idle", ok=True,
                latency_ms=2300, returned=6, accepted=4, stored=3, prompt_tokens=400, completion_tokens=80,
                db_path=path)
    ai.log_call(provider="gemini", model="g", category="ambient", mood="idle", ok=False,
                latency_ms=10000, error="ReadTimeout: timed out", db_path=path)
    ai.store_lines("ambient", "idle", 0, ["Desk check: still a desk."], provider="freellm",
                   model="qwen3.8-27b", db_path=path)
    with db.connect(path) as conn:
        ai._record_demand(conn, "reminder", "rage", datetime.now())

    client = app.test_client()
    login_client(client)
    page = client.get("/admin/ai")
    assert page.status_code == 200
    html = page.data.decode()
    for text in ("Recent AI calls", "What JIRI can say", "Recently generated lines",
                 "How JIRI uses AI", "ReadTimeout: timed out", "Desk check: still a desk.",
                 "qwen3.8-27b", "built-in", "Generate now", "480", "50%"):
        assert text in html, text


def test_activity_json_requires_admin(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    resp = client.get("/api/ai/activity")
    assert resp.status_code == 401

    login_client(client)
    resp = client.get("/api/ai/activity")
    assert resp.status_code == 200
    data = resp.get_json()
    for key in ("status", "summary", "calls", "buckets", "recent_lines", "worker"):
        assert key in data


def test_generate_bucket_rejects_unknown_bucket(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = app.test_client()
    login_client(client)
    resp = client.post("/admin/ai/generate", data={"category": "nope", "mood": "x"})
    assert resp.status_code == 302
    assert "error=" in resp.headers["Location"]
