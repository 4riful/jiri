from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

from jiri import db, usage
from jiri.web import create_app
from conftest import login_client

ROOT = Path(__file__).resolve().parents[1]


def _load_push_script():
    spec = importlib.util.spec_from_file_location("jiri_usage_push", ROOT / "scripts" / "jiri_usage_push.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


push_script = _load_push_script()


def _report(**overrides):
    base = {
        "provider": "claude",
        "context_pct": 42.04,
        "five_hour_pct": 12.5,
        "five_hour_resets_at": 1_800_000_000,
        "weekly_pct": 33.3,
        "weekly_resets_at": 1_800_500_000,
        "label": "Opus 4.5",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- module


def test_record_latest_round_trip(tmp_path):
    path = str(tmp_path / "jiri.db")
    stored = usage.record(_report(), db_path=path, now=1000.0)
    usage.record(_report(provider="chatgpt", label="gpt-5-codex", context_pct=None), db_path=path, now=1001.0)

    reports = usage.latest(path)
    assert set(reports) == {"claude", "chatgpt"}
    assert reports["claude"] == stored
    assert reports["claude"].updated_at == 1000.0
    assert reports["claude"].five_hour_resets_at == 1_800_000_000.0
    assert reports["chatgpt"].context_pct is None
    assert reports["chatgpt"].label == "gpt-5-codex"

    usage.record(_report(weekly_pct=50), db_path=path, now=1002.0)
    assert usage.latest(path)["claude"].weekly_pct == 50.0
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM usage_reports").fetchone()[0] == 2


def test_record_clamps_and_rejects(tmp_path):
    path = str(tmp_path / "jiri.db")
    report = usage.record(_report(context_pct=140, five_hour_pct=-5, weekly_pct="7.5"), db_path=path)
    assert (report.context_pct, report.five_hour_pct, report.weekly_pct) == (100.0, 0.0, 7.5)
    with pytest.raises(ValueError):
        usage.record(_report(provider="gemini"), db_path=path)
    with pytest.raises(ValueError):
        usage.record(_report(weekly_pct="lots"), db_path=path)
    with pytest.raises(ValueError):
        usage.record(_report(label=123), db_path=path)


def test_latest_missing_db_and_table_is_empty_and_read_only(tmp_path):
    missing = tmp_path / "nope.db"
    assert usage.latest(str(missing)) == {}
    assert not missing.exists()  # read path never creates the file

    path = tmp_path / "other.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    assert usage.latest(str(path)) == {}
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "usage_reports" not in tables


def test_init_db_creates_usage_table(tmp_path):
    path = str(tmp_path / "jiri.db")
    db.init_db(path)
    assert usage.latest(path) == {}
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='usage_reports'").fetchone()


def test_record_if_changed_throttles_identical_recent_rows(tmp_path):
    path = str(tmp_path / "jiri.db")
    _, stored = usage.record_if_changed(_report(), db_path=path, now=1000.0)
    assert stored
    _, stored = usage.record_if_changed(_report(context_pct=42.01), db_path=path, now=1010.0)
    assert not stored  # same after rounding, < 30 s
    assert usage.latest(path)["claude"].updated_at == 1000.0
    _, stored = usage.record_if_changed(_report(context_pct=43), db_path=path, now=1011.0)
    assert stored  # changed
    _, stored = usage.record_if_changed(_report(context_pct=43), db_path=path, now=1045.0)
    assert stored  # unchanged but older than 30 s


# ---------------------------------------------------------------- endpoint


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_DISPLAY_DRIVER", "mock")
    monkeypatch.setenv("JIRI_WEATHER_FAKE", "true")
    monkeypatch.delenv("JIRI_USAGE_TOKEN", raising=False)
    app = create_app()
    return app.test_client()


def test_push_disabled_without_token_env(client):
    response = client.post("/api/usage", json=_report(), headers={"Authorization": "Bearer x"})
    assert response.status_code == 503
    assert response.get_json()["error"] == "usage push disabled"


def test_push_auth_and_throttle(client, monkeypatch):
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "s3cret-token")
    assert client.post("/api/usage", json=_report()).status_code == 401
    wrong = client.post("/api/usage", json=_report(), headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401

    good = {"Authorization": "Bearer s3cret-token"}
    first = client.post("/api/usage", json=_report(), headers=good)
    assert first.status_code == 200
    assert first.get_json()["stored"] is True
    again = client.post("/api/usage", json=_report(), headers=good)
    assert again.status_code == 200
    assert again.get_json()["stored"] is False

    bad = client.post("/api/usage", json=_report(provider="bard"), headers=good)
    assert bad.status_code == 400


def test_get_usage_requires_admin(client, monkeypatch):
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "s3cret-token")
    client.post("/api/usage", json=_report(), headers={"Authorization": "Bearer s3cret-token"})
    assert client.get("/api/usage").status_code == 302
    login_client(client, follow_redirects=False)
    data = client.get("/api/usage").get_json()
    assert data["claude"]["label"] == "Opus 4.5"
    assert data["claude"]["weekly_pct"] == 33.3


def test_screen_surface_does_not_expose_push(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRI_DB_PATH", str(tmp_path / "jiri.db"))
    monkeypatch.setenv("JIRI_USAGE_TOKEN", "s3cret-token")
    client = create_app(surface="screen").test_client()
    response = client.post("/api/usage", json=_report(), headers={"Authorization": "Bearer s3cret-token"})
    assert response.status_code == 404


# ---------------------------------------------------------------- laptop collector


def test_parse_claude_statusline_payload():
    payload = {
        "model": {"display_name": "Opus 4.5"},
        "context_window": {"used_percentage": 18.2, "total_input_tokens": 1, "context_window_size": 2},
        "rate_limits": {
            "five_hour": {"used_percentage": 7, "resets_at": 1_800_000_000},
            "seven_day": {"used_percentage": 41.5, "resets_at": 1_800_400_000},
        },
    }
    report = push_script.parse_claude_statusline(payload)
    assert report == {
        "provider": "claude",
        "context_pct": 18.2,
        "five_hour_pct": 7.0,
        "five_hour_resets_at": 1_800_000_000.0,
        "weekly_pct": 41.5,
        "weekly_resets_at": 1_800_400_000.0,
        "label": "Opus 4.5",
    }
    fallback = push_script.parse_claude_statusline(
        {"context_window": {"total_input_tokens": 50_000, "context_window_size": 200_000}}
    )
    assert fallback["context_pct"] == 25.0
    assert fallback["five_hour_pct"] is None and fallback["label"] == ""
    # The pushed shape is accepted by the Pi side.
    usage.validate(report)


def test_codex_parser_on_synthetic_rollout(tmp_path):
    day = tmp_path / "2026" / "11" / "23"
    day.mkdir(parents=True)
    old = day / "rollout-old.jsonl"
    old.write_text('{"payload":{"rate_limits":{"primary":{"used_percent":99,"window_minutes":300}}}}\n')
    os.utime(old, (1, 1))
    lines = [
        {"type": "turn_context", "payload": {"model": "gpt-5-codex"}},
        {"type": "event_msg", "payload": {"type": "token_count", "info": None, "rate_limits": {
            "primary": {"used_percent": 1.0, "window_minutes": 300, "resets_at": 1}}}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "hi"}},
        {"type": "event_msg", "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {"input_tokens": 90_000},
                "last_token_usage": {"input_tokens": 25_000},
                "model_context_window": 100_000,
            },
            "rate_limits": {
                "primary": {"used_percent": 12.0, "window_minutes": 299, "resets_at": 1_800_000_000},
                "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 1_800_500_000},
                "plan_type": "plus",
            },
        }},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "done"}},
    ]
    new = day / "rollout-new.jsonl"
    new.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    assert push_script.newest_rollout(tmp_path) == new
    report = push_script.collect_codex(tmp_path)
    assert report == {
        "provider": "chatgpt",
        "context_pct": 25.0,
        "five_hour_pct": 12.0,
        "five_hour_resets_at": 1_800_000_000.0,
        "weekly_pct": 40.0,
        "weekly_resets_at": 1_800_500_000.0,
        "label": "gpt-5-codex",
    }
    # Tiny chunks exercise the backwards line reassembly.
    event = push_script.last_rate_limit_event(new, chunk_size=7)
    assert push_script.parse_codex_event(event)["weekly_pct"] == 40.0
    usage.validate(report)


def test_codex_parser_tolerates_top_level_and_null_windows(tmp_path):
    path = tmp_path / "rollout-x.jsonl"
    path.write_text(json.dumps({
        "type": "token_count",
        "rate_limits": {"primary": {"used_percent": 3, "window_minutes": 10080, "resets_at": 5}, "secondary": None,
                         "plan_type": "plus"},
    }) + "\n")
    report = push_script.collect_codex(tmp_path)
    assert report["weekly_pct"] == 3.0
    assert report["five_hour_pct"] is None
    assert report["context_pct"] is None
    assert report["label"] == "Codex plus"


def test_statusline_passes_stdin_to_wrapped_command_without_jiri(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("JIRI_URL", raising=False)
    monkeypatch.delenv("JIRI_USAGE_TOKEN", raising=False)
    monkeypatch.setattr(push_script, "CACHE_DIR", tmp_path / "cache")
    raw = json.dumps({"model": {"display_name": "Opus"}}).encode()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
    cmd = f'{sys.executable} -c "import sys,json; print(json.load(sys.stdin)[\'model\'][\'display_name\'] + \' ok\')"'
    assert push_script.main(["claude-statusline", "--then", cmd]) == 0
    assert capsys.readouterr().out.strip() == "Opus ok"
    assert not (tmp_path / "cache").exists()  # no URL/token -> no push, no stamp


def test_statusline_spawns_detached_push_once_per_minute(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(push_script, "CACHE_DIR", tmp_path / "cache")
    spawned = []
    monkeypatch.setattr(push_script, "spawn_detached_push", lambda report, url, token: spawned.append(report))
    opencode_spawns = []
    monkeypatch.setattr(push_script, "spawn_detached_opencode", lambda url, token, *mode: opencode_spawns.append(url))
    raw = json.dumps({"rate_limits": {"five_hour": {"used_percentage": 9}}}).encode()
    for _ in range(2):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw)))
        assert push_script.main(["claude-statusline", "--url", "http://pi:5000", "--token", "t"]) == 0
    assert len(spawned) == 1
    assert opencode_spawns == ["http://pi:5000"]  # ChatGPT check, throttled to once per 5 min
    assert spawned[0]["five_hour_pct"] == 9.0
    assert capsys.readouterr().out == ""  # no --then prints nothing


# ---------------------------------------------------------------- OpenCode collector

NOW_MS = 1_795_450_000_000


def _opencode_db(tmp_path, *, session_age_s=60.0, catalog=True, legacy=False):
    """Synthetic OpenCode 2.x store mirroring the real tables/JSON shapes."""
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE session_v2 (id TEXT PRIMARY KEY, model TEXT, time_updated INTEGER NOT NULL);
        CREATE TABLE session_message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL,
            seq INTEGER NOT NULL, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, time_created INTEGER, time_updated INTEGER);
        CREATE TABLE account (id TEXT PRIMARY KEY, access_token TEXT NOT NULL);
        """
    )
    conn.execute("INSERT INTO account VALUES ('a', 'must-never-be-read')")
    updated = NOW_MS - int(session_age_s * 1000)

    def assistant(sid, seq, model, provider, tokens):
        data = {"time": {"created": updated - 1000 + seq}, "agent": "build",
                "model": {"id": model, "providerID": provider}, "content": [], "finish": "stop",
                "cost": 0, "tokens": tokens}
        conn.execute("INSERT INTO session_message VALUES (?,?,?,?,?,?,?)",
                     (f"m{sid}{seq}", sid, "assistant", seq, updated - 1000 + seq, updated, json.dumps(data)))

    full = {"input": 342, "output": 324, "reasoning": 190, "cache": {"read": 173_568, "write": 0}}
    empty = {"input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}}
    # Newest session uses a non-OpenAI model and must be skipped.
    conn.execute("INSERT INTO session_v2 VALUES ('s2', ?, ?)",
                 (json.dumps({"id": "muse-spark", "providerID": "opencode"}), updated + 5))
    assistant("s2", 1, "muse-spark", "opencode", full)
    conn.execute("INSERT INTO session_v2 VALUES ('s1', ?, ?)",
                 (json.dumps({"id": "gpt-6.2-sol", "providerID": "openai"}), updated))
    conn.execute("INSERT INTO session_message VALUES ('u1','s1','user',1,?,?,?)",
                 (updated - 2000, updated, json.dumps({"text": "hi"})))
    assistant("s1", 2, "gpt-6.2-sol", "openai", {"input": 10, "output": 5, "cache": {"read": 90, "write": 0}})
    assistant("s1", 3, "gpt-6.2-sol", "openai", full)
    assistant("s1", 4, "gpt-6.2-sol", "openai", empty)  # in-flight turn, no usage yet
    if catalog:
        body = {"openai": {"id": "openai", "models": {"gpt-6.2-sol": {
            "id": "gpt-6.2-sol", "limit": {"context": 1_050_000, "input": 922_000, "output": 128_000}}}}}
        conn.execute("INSERT INTO kv VALUES ('models-dev:v2:catalog', ?, 0, 0)",
                     (json.dumps({"updatedAt": NOW_MS, "digest": "x", "body": json.dumps(body)}),))
    conn.commit()
    conn.close()
    return path


def test_opencode_collector_reads_latest_openai_turn(tmp_path):
    path = _opencode_db(tmp_path)
    before = path.read_bytes()
    report = push_script.collect_opencode(path, now=NOW_MS / 1000)
    assert report["provider"] == "chatgpt"
    assert report["label"] == "gpt-6.2-sol"
    assert report["context_pct"] == pytest.approx((342 + 173_568) / 1_050_000 * 100)
    # No rate-limit windows exist locally: never invented.
    for field in ("five_hour_pct", "five_hour_resets_at", "weekly_pct", "weekly_resets_at"):
        assert report[field] is None
    assert path.read_bytes() == before  # opened read-only
    usage.validate(report)  # matches the server's schema


def test_opencode_collector_skips_stale_sessions(tmp_path):
    path = _opencode_db(tmp_path, session_age_s=7 * 3600)
    assert push_script.collect_opencode(path, now=NOW_MS / 1000) is None
    assert push_script.collect_opencode(tmp_path / "missing.db") is None


def test_opencode_collector_falls_back_to_known_windows(tmp_path):
    path = _opencode_db(tmp_path, catalog=False)
    report = push_script.collect_opencode(path, now=NOW_MS / 1000)
    assert report["context_pct"] == pytest.approx((342 + 173_568) / 1_050_000 * 100)
    assert push_script._fallback_context("gpt-5.2-codex") == 400_000
    assert push_script._fallback_context("claude-opus") is None


def test_opencode_dry_run_prints_without_pushing(tmp_path, monkeypatch, capsys):
    path = _opencode_db(tmp_path, session_age_s=0)
    monkeypatch.setattr(push_script.time, "time", lambda: NOW_MS / 1000)
    monkeypatch.setattr(push_script, "push", lambda *a, **k: pytest.fail("dry run must not push"))
    assert push_script.main(["opencode", "--db", str(path), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["label"] == "gpt-6.2-sol"


# ---------------------------------------------------------------- OpenCode rate-limit windows


@pytest.fixture(autouse=True)
def _no_real_limits_file(tmp_path, monkeypatch):
    """Never let tests pick up the developer's real plugin snapshot."""
    monkeypatch.setattr(push_script, "OPENCODE_LIMITS_FILE", tmp_path / "no-such-limits.json")


NOW_S = NOW_MS / 1000


def _write_limits(tmp_path, **overrides):
    data = {
        "version": 1,
        "captured_at": NOW_S - 30,
        "source": "http",
        "model": "gpt-6.2-sol",
        "plan_type": "plus",
        "primary": {"used_percent": 23, "window_minutes": 300, "reset_at": NOW_S + 3600},
        "secondary": {"used_percent": 41, "window_minutes": 10080, "reset_at": NOW_S + 86400},
    }
    data.update(overrides)
    path = tmp_path / "opencode-limits.json"
    path.write_text(json.dumps(data))
    return path


def _add_429_turn(db_path, *, created_ms, primary=100, secondary=16, legacy=False):
    """OpenCode stores x-codex-* headers only inside a failed turn's error."""
    headers = {
        "X-Codex-Plan-Type": "plus",
        "X-Codex-Primary-Used-Percent": str(primary),
        "X-Codex-Primary-Window-Minutes": "300",
        "X-Codex-Primary-Reset-At": str(int(created_ms / 1000 + 2300)),
        "X-Codex-Secondary-Used-Percent": str(secondary),
        "X-Codex-Secondary-Window-Minutes": "10080",
        "X-Codex-Secondary-Reset-After-Seconds": "589102",
        "X-Codex-Turn-State": "opaque-must-not-be-copied",
    }
    conn = sqlite3.connect(db_path)
    if legacy:
        conn.execute("CREATE TABLE IF NOT EXISTS message (id TEXT PRIMARY KEY, session_id TEXT, "
                     "time_created INTEGER, data TEXT)")
        data = {"role": "assistant", "modelID": "gpt-5.6-sol", "providerID": "openai", "time": {"created": created_ms},
                "error": {"name": "APIError", "data": {"responseHeaders": {k.lower(): v for k, v in headers.items()}}}}
        conn.execute("INSERT INTO message VALUES ('old', 's0', ?, ?)", (created_ms, json.dumps(data)))
    else:
        body = {"type": "error", "error": {"type": "usage_limit_reached"}, "status_code": 429, "headers": headers}
        data = {"time": {"created": created_ms, "completed": created_ms + 400},
                "model": {"id": "gpt-5.6-sol", "providerID": "openai"}, "content": [], "finish": "error",
                "error": {"type": "provider.quota", "message": "limit", "response": {"body": json.dumps(body)}}}
        conn.execute("INSERT INTO session_message VALUES ('e1','s9','assistant',1,?,?,?)",
                     (created_ms, created_ms, json.dumps(data)))
    conn.commit()
    conn.close()


def test_parse_codex_headers_is_case_insensitive_and_copies_only_windows():
    snap = push_script.parse_codex_headers({
        "x-codex-primary-used-percent": "7.5", "X-Codex-Primary-Window-Minutes": "300",
        "x-codex-primary-reset-after-seconds": "60", "x-codex-turn-state": "secret-ish",
        "x-codex-plan-type": "pro",
    }, captured_at=1000.0)
    assert snap["primary"] == {"used_percent": 7.5, "window_minutes": 300.0, "reset_at": 1060.0}
    assert "secondary" not in snap and snap["plan_type"] == "pro"
    assert "secret-ish" not in json.dumps(snap)
    assert push_script.parse_codex_headers({"date": "x"}, 1.0) is None


def test_limit_fields_drop_windows_that_already_reset():
    snap = {"captured_at": NOW_S - 10,
            "primary": {"used_percent": 100.0, "window_minutes": 300.0, "reset_at": NOW_S - 1},
            "secondary": {"used_percent": 40.0, "window_minutes": 10080.0, "reset_at": NOW_S + 50}}
    fields = push_script.limit_fields(snap, NOW_S)
    assert fields["five_hour_pct"] is None and fields["five_hour_resets_at"] is None
    assert fields["weekly_pct"] == 40.0 and fields["weekly_resets_at"] == NOW_S + 50
    undated = {"captured_at": NOW_S - 7200, "primary": {"used_percent": 5.0, "window_minutes": 300.0, "reset_at": None}}
    assert push_script.limit_fields(undated, NOW_S)["five_hour_pct"] is None


def test_opencode_collector_uses_plugin_limits_file(tmp_path):
    db_path = _opencode_db(tmp_path)
    limits = _write_limits(tmp_path)
    report = push_script.collect_opencode(db_path, now=NOW_S, limits_file=limits)
    assert report["label"] == "gpt-6.2-sol"
    assert report["context_pct"] == pytest.approx((342 + 173_568) / 1_050_000 * 100)
    assert report["five_hour_pct"] == 23 and report["five_hour_resets_at"] == NOW_S + 3600
    assert report["weekly_pct"] == 41 and report["weekly_resets_at"] == NOW_S + 86400
    usage.validate(report)


def test_opencode_collector_pushes_limits_even_when_session_idle(tmp_path):
    db_path = _opencode_db(tmp_path, session_age_s=7 * 3600)
    report = push_script.collect_opencode(db_path, now=NOW_S, limits_file=_write_limits(tmp_path))
    assert report["context_pct"] is None
    assert report["five_hour_pct"] == 23
    assert report["label"] == "gpt-6.2-sol"  # from the snapshot
    usage.validate(report)


def test_opencode_collector_ignores_bad_limits_file(tmp_path):
    db_path = _opencode_db(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    report = push_script.collect_opencode(db_path, now=NOW_S, limits_file=bad)
    assert report["five_hour_pct"] is None
    assert push_script.read_limits_file(_write_limits(tmp_path, version=2)) is None


@pytest.mark.parametrize("legacy", [False, True])
def test_opencode_collector_falls_back_to_last_429_headers(tmp_path, legacy):
    db_path = _opencode_db(tmp_path)
    _add_429_turn(db_path, created_ms=NOW_MS - 600_000, legacy=legacy)
    before_db = db_path.read_bytes()
    report = push_script.collect_opencode(db_path, now=NOW_S)
    assert db_path.read_bytes() == before_db
    assert report["five_hour_pct"] == 100.0
    assert report["five_hour_resets_at"] == int((NOW_MS - 600_000) / 1000 + 2300)
    assert report["weekly_pct"] == 16.0
    assert report["label"] == "gpt-6.2-sol"  # the live session still names the model
    # Once the 5-hour window has reset, the stale 100 % is dropped, not shown.
    later = push_script.collect_opencode(db_path, now=NOW_S + 3000)
    assert later["five_hour_pct"] is None and later["weekly_pct"] == 16.0


def test_opencode_collector_prefers_newest_snapshot(tmp_path):
    db_path = _opencode_db(tmp_path)
    _add_429_turn(db_path, created_ms=NOW_MS - 600_000)
    report = push_script.collect_opencode(db_path, now=NOW_S, limits_file=_write_limits(tmp_path))
    assert report["five_hour_pct"] == 23  # plugin file (30 s old) beats the 10 min old 429
    stale = _write_limits(tmp_path, captured_at=NOW_S - 3600)
    assert push_script.collect_opencode(db_path, now=NOW_S, limits_file=stale)["five_hour_pct"] == 100.0


def test_opencode_plugin_file_exists_and_is_dependency_free():
    plugin = ROOT / "integrations" / "opencode" / "jiri-usage" / "index.js"
    source = plugin.read_text()
    assert '"http.response"' in source and "opencode-limits.json" in source
    imports = [line for line in source.splitlines() if line.startswith("import ")]
    assert imports and all('from "node:' in line for line in imports)
    assert "fetch(" not in source  # observes OpenCode's responses, never calls anything itself


# --- codex-live (OpenAI's codex app-server: account/rateLimits/read) --------

def _fake_codex(tmp_path, result=None, error=None):
    import json as _json
    import stat

    reply = {"id": 2, "error": error} if error else {"id": 2, "result": result}
    script = tmp_path / "codex"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('id') == 1:\n"
        "        print(json.dumps({'id': 1, 'result': {}}), flush=True)\n"
        "    elif msg.get('id') == 2:\n"
        f"        print({_json.dumps(_json.dumps(reply))}, flush=True)\n"
        "        break\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_codex_live_matches_the_codex_app_popover(tmp_path):
    push = _load_push_script()
    result = {"rateLimits": {"planType": "plus",
                             "primary": {"usedPercent": 14, "windowDurationMins": 300, "resetsAt": 1795470000},
                             "secondary": {"usedPercent": 11, "windowDurationMins": 10080, "resetsAt": 1796000000}}}
    report = push.parse_rate_limits_response(push.query_codex_rate_limits(_fake_codex(tmp_path, result)))
    assert report["five_hour_pct"] == 14 and report["weekly_pct"] == 11     # 86% / 89% left
    assert report["five_hour_resets_at"] == 1795470000 and report["label"] == "Plus plan"


def test_codex_live_explains_missing_login(tmp_path):
    push = _load_push_script()
    codex = _fake_codex(tmp_path, error={"code": -32600, "message": "codex account authentication required to read rate limits"})
    try:
        push.query_codex_rate_limits(codex)
    except push.CodexLiveError as exc:
        assert "codex login" in str(exc)
    else:
        raise AssertionError("expected CodexLiveError")
