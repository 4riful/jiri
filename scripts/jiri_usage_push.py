#!/usr/bin/env python3
"""Push Claude Code / OpenCode (ChatGPT) usage from the laptop to JIRI.

Runs on the laptop where Claude Code and OpenCode live, not on the Pi.
Stdlib only. Configure with env vars or flags:

    JIRI_URL          e.g. http://jiri.local:5000   (--url)
    JIRI_USAGE_TOKEN  shared secret, same as the Pi's .env (--token)

Modes:

    claude-statusline [--then "<cmd>"]
        Use as Claude Code's statusLine.command. Reads the statusline JSON on
        stdin, pushes a summary to JIRI from a detached background process (at
        most once per 60 s), then pipes the same stdin to --then and prints
        its output so the existing statusline keeps working. Never blocks,
        never fails the statusline. Also starts a detached `opencode` push at
        most once per 2 min, so the ChatGPT card follows along.

    opencode [--loop SECONDS] [--db PATH] [--dry-run]
        Default ChatGPT source. Reads OpenCode's local SQLite store read-only
        (~/.local/share/opencode/opencode.db): context % from the last
        assistant turn of the newest OpenAI session (if active in the last
        6 h). The 5-hour and weekly windows come from
        ~/.cache/jiri/opencode-limits.json, written by the JIRI OpenCode
        plugin (integrations/opencode/jiri-usage), or else from the
        x-codex-* headers OpenCode stored with its last 429. A window whose
        reset time has passed is left empty, never guessed. Never touches
        OpenCode's auth/account/credential data.

    codex [--loop SECONDS] [--sessions DIR] [--dry-run]
        Reads the newest ~/.codex/sessions/**/rollout-*.jsonl, finds the last
        rate_limits event and pushes it once (or every SECONDS with --loop).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

PUSH_TIMEOUT_SECONDS = 3.0
STATUSLINE_THROTTLE_SECONDS = 60.0
OPENCODE_THROTTLE_SECONDS = 120.0
CODEX_LIVE_THROTTLE_SECONDS = 300.0
CODEX_LIVE_TIMEOUT_SECONDS = 25.0
OPENCODE_STALE_SECONDS = 6 * 3600.0
THEN_TIMEOUT_SECONDS = 5.0
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "jiri"


# --------------------------------------------------------------------------
# Claude Code statusline payload


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_claude_statusline(payload: dict) -> dict:
    """Map a Claude Code statusline payload to a JIRI usage report."""
    window = payload.get("context_window") or {}
    context = _num(window.get("used_percentage"))
    if context is None:
        size = _num(window.get("context_window_size"))
        used = _num(window.get("total_input_tokens"))
        if size and used is not None:
            context = used / size * 100
    limits = payload.get("rate_limits") or {}
    five = limits.get("five_hour") or {}
    week = limits.get("seven_day") or {}
    model = payload.get("model") or {}
    return {
        "provider": "claude",
        "context_pct": context,
        "five_hour_pct": _num(five.get("used_percentage")),
        "five_hour_resets_at": _num(five.get("resets_at")),
        "weekly_pct": _num(week.get("used_percentage")),
        "weekly_resets_at": _num(week.get("resets_at")),
        "label": str(model.get("display_name") or "") if isinstance(model, dict) else "",
    }


# --------------------------------------------------------------------------
# Codex rollout files


def newest_rollout(sessions_dir: Path) -> Path | None:
    newest = None
    newest_mtime = -1.0
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest, newest_mtime = path, mtime
    return newest


def _find_key(obj, key, depth=0):
    """First dict value for `key`, searching nested dicts breadth-first-ish."""
    if depth > 4 or not isinstance(obj, dict):
        return None
    if key in obj:
        return obj[key]
    for value in obj.values():
        if isinstance(value, dict):
            found = _find_key(value, key, depth + 1)
            if found is not None:
                return found
    return None


def last_rate_limit_event(path: Path, chunk_size: int = 65536) -> dict | None:
    """Scan the file backwards for the last JSON line mentioning rate_limits."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        tail = b""
        while position > 0:
            step = min(chunk_size, position)
            position -= step
            handle.seek(position)
            tail = handle.read(step) + tail
            lines = tail.split(b"\n")
            # lines[0] may be partial unless we reached the start of the file.
            complete = lines if position == 0 else lines[1:]
            for raw in reversed(complete):
                if b"rate_limits" not in raw:
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(_find_key(event, "rate_limits"), dict):
                    return event
            tail = lines[0] if position > 0 else b""
    return None


def parse_codex_event(event: dict) -> dict:
    limits = _find_key(event, "rate_limits") or {}
    report = {
        "provider": "chatgpt",
        "context_pct": None,
        "five_hour_pct": None,
        "five_hour_resets_at": None,
        "weekly_pct": None,
        "weekly_resets_at": None,
        "label": "",
    }
    for name in ("primary", "secondary"):
        window = limits.get(name)
        if not isinstance(window, dict):
            continue
        minutes = _num(window.get("window_minutes"))
        used = _num(window.get("used_percent"))
        resets = _num(window.get("resets_at"))
        if resets is None and _num(window.get("resets_in_seconds")) is not None:
            resets = time.time() + float(window["resets_in_seconds"])
        if minutes is None:
            continue
        if 200 <= minutes <= 400:  # ~5 hours
            report["five_hour_pct"], report["five_hour_resets_at"] = used, resets
        elif 9000 <= minutes <= 11000:  # ~7 days
            report["weekly_pct"], report["weekly_resets_at"] = used, resets
    info = _find_key(event, "info")
    if isinstance(info, dict):
        window_size = _num(info.get("model_context_window"))
        last = info.get("last_token_usage") or {}
        used_tokens = _num(last.get("input_tokens")) if isinstance(last, dict) else None
        if window_size and used_tokens is not None:
            report["context_pct"] = min(100.0, used_tokens / window_size * 100)
    model = _find_key(event, "model")
    if isinstance(model, str):
        report["label"] = model
    plan = limits.get("plan_type")
    if not report["label"] and isinstance(plan, str) and plan:
        report["label"] = f"Codex {plan}"
    return report


def _rollout_model(path: Path) -> str:
    """Model name from the session's turn_context lines, if any (best effort)."""
    model = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"model"' not in line:
                    continue
                try:
                    found = _find_key(json.loads(line), "model")
                except ValueError:
                    continue
                if isinstance(found, str) and found:
                    model = found
    except OSError:
        pass
    return model


def collect_codex(sessions_dir: Path) -> dict | None:
    path = newest_rollout(sessions_dir)
    if path is None:
        return None
    event = last_rate_limit_event(path)
    if event is None:
        return None
    report = parse_codex_event(event)
    model = _rollout_model(path)
    if model:
        report["label"] = model
    return report


# --------------------------------------------------------------------------
# OpenCode local store (sst/opencode, used with a ChatGPT subscription)
#
# OpenCode 2.x keeps everything in one SQLite file. Only these tables/columns
# are read (never account/control_account/credential or auth.json):
#   session_v2(id, model JSON {"id","providerID"}, time_updated ms)
#   session_message(session_id, type='assistant', seq, data JSON):
#       data.model {"id","providerID"}, data.time.created (ms),
#       data.tokens {"input","output","reasoning","cache":{"read","write"}}
#       data.error.response.body -> JSON string whose "headers" hold the
#       X-Codex-* rate-limit headers, but only for failed (429) turns
#   kv(key='models-dev:v2:catalog', value JSON {"body": "<models.dev JSON>"})
#       body[provider]["models"][model]["limit"]["context"]
# Older 1.x builds used session/message with data.modelID/providerID (and
# data.error.data.responseHeaders); that is read as a fallback.
#
# Live 5-hour / weekly windows come from the JIRI OpenCode plugin
# (integrations/opencode/jiri-usage), which copies the x-codex-* response
# headers of every ChatGPT turn to ~/.cache/jiri/opencode-limits.json. Without
# the plugin only the snapshot from the last 429 is available.

OPENCODE_DB = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "opencode" / "opencode.db"

# Fallback context windows (tokens) when OpenCode's models.dev cache lacks the
# model. Values as listed by models.dev for OpenAI; longest prefix wins.
OPENAI_CONTEXT_WINDOWS = {
    "gpt-5": 400_000,
    "gpt-5.5": 1_050_000,
    "gpt-6": 1_050_000,
}


def _is_openai_model(provider: str, model: str) -> bool:
    return provider == "openai" or model.lower().startswith("gpt-")


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=2)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _json(text) -> dict:
    try:
        value = json.loads(text) if isinstance(text, (str, bytes)) else None
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _prompt_tokens(tokens: dict) -> float | None:
    """Prompt size of one turn: fresh input + cached input."""
    if not isinstance(tokens, dict):
        return None
    cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
    parts = [_num(tokens.get("input")), _num(cache.get("read")), _num(cache.get("write"))]
    if all(p is None for p in parts):
        return None
    return sum(p or 0.0 for p in parts)


def _latest_openai_turn(conn: sqlite3.Connection, tables: set[str]):
    """(model_id, provider_id, prompt_tokens, last_activity_seconds) or None."""
    if {"session_v2", "session_message"} <= tables:
        sessions = conn.execute(
            "SELECT id, time_updated FROM session_v2 ORDER BY time_updated DESC LIMIT 25"
        ).fetchall()
        query = (
            "SELECT data, time_created FROM session_message WHERE session_id = ? AND type = 'assistant' "
            "ORDER BY seq DESC LIMIT 20"
        )

        def model_of(data):
            model = data.get("model") if isinstance(data.get("model"), dict) else {}
            return str(model.get("id") or ""), str(model.get("providerID") or "")

    elif {"session", "message"} <= tables:
        sessions = conn.execute("SELECT id, time_updated FROM session ORDER BY time_updated DESC LIMIT 25").fetchall()
        query = (
            "SELECT data, time_created FROM message WHERE session_id = ? "
            "AND data LIKE '%\"role\":\"assistant\"%' ORDER BY time_created DESC LIMIT 20"
        )

        def model_of(data):
            return str(data.get("modelID") or ""), str(data.get("providerID") or "")

    else:
        return None
    for session_id, session_updated in sessions:
        for raw, created in conn.execute(query, (session_id,)):
            data = _json(raw)
            model_id, provider_id = model_of(data)
            if not _is_openai_model(provider_id, model_id):
                continue
            prompt = _prompt_tokens(data.get("tokens"))
            if not prompt:  # in-flight turn: no usage yet, look further back
                continue
            last_ms = max(_num(session_updated) or 0.0, _num(created) or 0.0)
            return model_id, provider_id, prompt, last_ms / 1000.0
    return None


def _catalog_context(conn: sqlite3.Connection, tables: set[str], provider: str, model: str) -> float | None:
    if "kv" not in tables:
        return None
    row = conn.execute("SELECT value FROM kv WHERE key = 'models-dev:v2:catalog'").fetchone()
    if not row:
        return None
    body = _json(row[0]).get("body")
    catalog = _json(body) if isinstance(body, str) else (body if isinstance(body, dict) else {})
    for provider_id in (provider, "openai"):
        entry = (((catalog.get(provider_id) or {}).get("models") or {}).get(model)) or {}
        limit = entry.get("limit") if isinstance(entry, dict) else None
        if isinstance(limit, dict) and _num(limit.get("context")):
            return _num(limit.get("context"))
    return None


def _fallback_context(model: str) -> float | None:
    best = ""
    for prefix in OPENAI_CONTEXT_WINDOWS:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return float(OPENAI_CONTEXT_WINDOWS[best]) if best else None


OPENCODE_LIMITS_FILE = Path(os.environ.get("JIRI_OPENCODE_LIMITS") or CACHE_DIR / "opencode-limits.json")
LIMIT_WINDOWS = ("primary", "secondary")
# A window with no reset time is trusted this long after capture.
LIMIT_UNDATED_MAX_AGE_SECONDS = 3600.0


def _limit_window(entry) -> dict | None:
    if not isinstance(entry, dict):
        return None
    used = _num(entry.get("used_percent"))
    if used is None:
        return None
    return {
        "used_percent": max(0.0, min(100.0, used)),
        "window_minutes": _num(entry.get("window_minutes")),
        "reset_at": _num(entry.get("reset_at")),
    }


def _limit_snapshot(raw, captured_at, source: str) -> dict | None:
    """Normalise {primary, secondary, plan_type, model} into a snapshot."""
    if not isinstance(raw, dict):
        return None
    snapshot = {"captured_at": _num(captured_at), "source": source}
    for name in LIMIT_WINDOWS:
        window = _limit_window(raw.get(name))
        if window:
            snapshot[name] = window
    if not any(name in snapshot for name in LIMIT_WINDOWS):
        return None
    for key in ("plan_type", "model"):
        if isinstance(raw.get(key), str) and raw[key]:
            snapshot[key] = raw[key][:40]
    return snapshot


def parse_codex_headers(headers: dict, captured_at: float | None) -> dict | None:
    """x-codex-{primary,secondary}-* response headers (any case) -> snapshot.
    Only the numeric window fields and the plan type are looked at."""
    if not isinstance(headers, dict):
        return None
    lower = {str(k).lower(): v for k, v in headers.items()}
    raw: dict = {}
    for name in LIMIT_WINDOWS:
        prefix = f"x-codex-{name}-"
        reset = _num(lower.get(prefix + "reset-at"))
        after = _num(lower.get(prefix + "reset-after-seconds"))
        if reset is None and after is not None and captured_at is not None:
            reset = captured_at + after
        raw[name] = {
            "used_percent": lower.get(prefix + "used-percent"),
            "window_minutes": lower.get(prefix + "window-minutes"),
            "reset_at": reset,
        }
    if isinstance(lower.get("x-codex-plan-type"), str):
        raw["plan_type"] = lower["x-codex-plan-type"]
    return _limit_snapshot(raw, captured_at, "opencode-429")


def read_limits_file(path: Path = OPENCODE_LIMITS_FILE) -> dict | None:
    """Snapshot written by the JIRI OpenCode plugin, or None."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    return _limit_snapshot(data, data.get("captured_at"), "opencode-plugin")


def _find_codex_headers(obj, depth: int = 0):
    """Dict holding x-codex-primary-used-percent, searching nested dicts,
    lists and JSON-encoded strings (OpenCode 2.x stores the 429 body as text)."""
    if depth > 6:
        return None
    if isinstance(obj, str):
        text = obj.strip()
        if text.startswith("{") and "primary-used-percent" in text.lower():
            try:
                return _find_codex_headers(json.loads(text), depth + 1)
            except ValueError:
                return None
        return None
    if isinstance(obj, dict):
        if any(str(k).lower() == "x-codex-primary-used-percent" for k in obj):
            return obj
        values = obj.values()
    elif isinstance(obj, list):
        values = obj
    else:
        return None
    for value in values:
        found = _find_codex_headers(value, depth + 1)
        if found is not None:
            return found
    return None


def _db_limit_snapshot(conn: sqlite3.Connection, tables: set[str]) -> dict | None:
    """Newest rate-limit headers OpenCode persisted with a failed (429) turn."""
    queries = []
    if "session_message" in tables:
        queries.append(
            "SELECT data, time_created FROM session_message WHERE type = 'assistant' "
            "AND data LIKE '%primary-used-percent%' ORDER BY time_created DESC LIMIT 5"
        )
    if "message" in tables:
        queries.append(
            "SELECT data, time_created FROM message "
            "WHERE data LIKE '%primary-used-percent%' ORDER BY time_created DESC LIMIT 5"
        )
    best = None
    for query in queries:
        for raw, created in conn.execute(query):
            data = _json(raw)
            headers = _find_codex_headers(data.get("error"))
            if headers is None:
                continue
            time_info = data.get("time") if isinstance(data.get("time"), dict) else {}
            captured_ms = _num(time_info.get("completed")) or _num(time_info.get("created")) or _num(created)
            snapshot = parse_codex_headers(headers, captured_ms / 1000.0 if captured_ms else None)
            if snapshot and (best is None or (snapshot["captured_at"] or 0) > (best["captured_at"] or 0)):
                model = data.get("model") if isinstance(data.get("model"), dict) else {}
                model_id = model.get("id") or data.get("modelID")
                if isinstance(model_id, str) and model_id:
                    snapshot["model"] = model_id[:40]
                best = snapshot
            break  # rows are newest first within each table
    return best


def limit_fields(snapshot: dict | None, now: float) -> dict:
    """Map a snapshot's windows onto the report's 5-hour / weekly fields.
    A window whose reset time has passed is dropped: it has rolled over and
    the current usage is unknown, so it is never reported as stale or zero."""
    fields = {"five_hour_pct": None, "five_hour_resets_at": None, "weekly_pct": None, "weekly_resets_at": None}
    if not snapshot:
        return fields
    captured = snapshot.get("captured_at")
    for name in LIMIT_WINDOWS:
        window = snapshot.get(name)
        if not window:
            continue
        minutes, reset = window["window_minutes"], window["reset_at"]
        if reset is not None:
            if reset <= now:
                continue
        elif captured is None or now - captured > min(LIMIT_UNDATED_MAX_AGE_SECONDS, (minutes or 60) * 60):
            continue
        if minutes is not None:
            slot = "five_hour" if 200 <= minutes <= 400 else "weekly" if 9000 <= minutes <= 11000 else None
        else:
            slot = "five_hour" if name == "primary" else "weekly"
        if slot and fields[f"{slot}_pct"] is None:
            fields[f"{slot}_pct"], fields[f"{slot}_resets_at"] = window["used_percent"], reset
    return fields


def collect_opencode(db_path: Path, *, now: float | None = None,
                     max_age: float = OPENCODE_STALE_SECONDS,
                     limits_file: Path | None = None) -> dict | None:
    """ChatGPT report from OpenCode: context % from the newest OpenAI session
    (if active within `max_age` s) plus the 5-hour / weekly windows from the
    JIRI plugin's file or OpenCode's last 429. None when there is neither."""
    now = time.time() if now is None else now
    context_pct = None
    label = ""
    db_snapshot = None
    if Path(db_path).is_file():
        conn = _open_ro(Path(db_path))
        try:
            tables = _tables(conn)
            turn = _latest_openai_turn(conn, tables)
            if turn is not None and now - turn[3] <= max_age:
                model_id, provider_id, prompt, _ = turn
                window = _catalog_context(conn, tables, provider_id, model_id) or _fallback_context(model_id)
                context_pct = min(100.0, prompt / window * 100) if window else None
                label = model_id
            db_snapshot = _db_limit_snapshot(conn, tables)
        finally:
            conn.close()
    snapshots = [s for s in (read_limits_file(limits_file or OPENCODE_LIMITS_FILE), db_snapshot) if s]
    snapshot = max(snapshots, key=lambda s: s.get("captured_at") or 0.0) if snapshots else None
    limits = limit_fields(snapshot, now)
    if not label and context_pct is None and all(v is None for v in limits.values()):
        return None
    if not label and snapshot:
        plan = snapshot.get("plan_type")
        label = snapshot.get("model") or (f"ChatGPT {plan.title()}" if plan else "")
    return {"provider": "chatgpt", "context_pct": context_pct, **limits, "label": label}


# --------------------------------------------------------------------------
# Transport


# --- codex-live: ask OpenAI's own codex CLI, like the Codex app's usage popover -

class CodexLiveError(RuntimeError):
    pass


def _epoch(value) -> float | None:
    v = _num(value)
    if v is None or v <= 0:
        return None
    return v / 1000.0 if v > 1e12 else v


def parse_rate_limits_response(result: dict, *, now: float | None = None) -> dict:
    """`account/rateLimits/read` result -> UsageReport fields.

    The same numbers the Codex desktop app shows as "5-hour limit / Weekly
    limit — N% left" (we store % used; the display shows both).
    """
    snap = result.get("rateLimits") or {}
    out = {"provider": "chatgpt", "five_hour_pct": None, "five_hour_resets_at": None,
           "weekly_pct": None, "weekly_resets_at": None}
    for key in ("primary", "secondary"):
        window = snap.get(key) or {}
        used = _num(window.get("usedPercent"))
        minutes = _num(window.get("windowDurationMins"))
        if used is None:
            continue
        slot = "five_hour" if (minutes is None and key == "primary") or (minutes is not None and minutes <= 360) else "weekly"
        out[f"{slot}_pct"] = max(0.0, min(100.0, used))
        out[f"{slot}_resets_at"] = _epoch(window.get("resetsAt"))
    plan = snap.get("planType") or ""
    out["label"] = f"{str(plan).title()} plan" if plan else "ChatGPT"
    return out


def query_codex_rate_limits(codex_bin: str = "codex", timeout: float = CODEX_LIVE_TIMEOUT_SECONDS) -> dict:
    """Run `codex app-server` and ask `account/rateLimits/read` over JSON-RPC.

    codex reads (and refreshes) its own login; this script never sees a token.
    Raises CodexLiveError with a human message on failure.
    """
    import shutil
    import threading

    exe = shutil.which(codex_bin) or codex_bin
    try:
        proc = subprocess.Popen(
            [exe, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
    except OSError as exc:
        raise CodexLiveError(f"codex CLI not found ({exc}); install it or pass --codex") from exc
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for message in (
            {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "jiri", "title": None, "version": "2.0"}, "capabilities": None}},
            {"method": "initialized"},
            {"id": 2, "method": "account/rateLimits/read"},
        ):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") != 2:
                continue
            if "error" in msg:
                text = str((msg.get("error") or {}).get("message") or msg["error"])
                if "auth" in text.lower():
                    raise CodexLiveError("codex is not signed in: run `codex login` once")
                raise CodexLiveError(f"codex said: {text}")
            return msg.get("result") or {}
        raise CodexLiveError("codex app-server closed without an answer (timed out?)")
    finally:
        timer.cancel()
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.kill()
        proc.wait(timeout=5)


def collect_codex_live(codex_bin: str = "codex", *, opencode_db: Path | None = None) -> dict:
    report = parse_rate_limits_response(query_codex_rate_limits(codex_bin))
    # Context % isn't part of plan limits; take it from the newest GPT session
    # if there is one (read-only), so the card keeps its ctx bar.
    report["context_pct"] = None
    try:
        recent = collect_opencode(opencode_db or OPENCODE_DB)
        if recent and recent.get("context_pct") is not None:
            report["context_pct"] = recent["context_pct"]
    except Exception:
        pass
    return report


def push(report: dict, url: str, token: str, timeout: float = PUSH_TIMEOUT_SECONDS) -> dict:
    body = json.dumps(report).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/api/usage",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def _throttled(stamp: Path, interval: float) -> bool:
    try:
        return time.time() - stamp.stat().st_mtime < interval
    except OSError:
        return False


def _touch(stamp: Path) -> None:
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    os.utime(stamp, None)


def spawn_detached_push(report: dict, url: str, token: str) -> None:
    """Fire-and-forget: a new session the statusline never waits on."""
    env = dict(os.environ, JIRI_URL=url, JIRI_USAGE_TOKEN=token)
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "_push", "--payload", json.dumps(report)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=env,
    )


def spawn_detached_opencode(url: str, token: str, mode: str = "codex-live") -> None:
    """Collect + push ChatGPT usage in a process the statusline never waits on."""
    env = dict(os.environ, JIRI_URL=url, JIRI_USAGE_TOKEN=token)
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), mode, "--quiet"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=env,
    )


def run_claude_statusline(args) -> int:
    raw = sys.stdin.buffer.read()
    try:
        url, token = _settings(args)
        if url and token:
            stamp = CACHE_DIR / "usage-claude.stamp"
            if not _throttled(stamp, STATUSLINE_THROTTLE_SECONDS):
                payload = json.loads(raw.decode("utf-8") or "{}")
                if isinstance(payload, dict):
                    report = {**parse_claude_statusline(payload), "source": "claude-statusline"}
                    _touch(stamp)
                    spawn_detached_push(report, url, token)
            chatgpt_stamp = CACHE_DIR / "usage-chatgpt.stamp"
            if not _throttled(chatgpt_stamp, CODEX_LIVE_THROTTLE_SECONDS):
                _touch(chatgpt_stamp)
                spawn_detached_opencode(url, token, "codex-live")
    except Exception:
        pass  # the statusline must never break because JIRI is unreachable
    if args.then:
        try:
            result = subprocess.run(
                args.then,
                shell=True,
                input=raw,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=THEN_TIMEOUT_SECONDS,
            )
            sys.stdout.buffer.write(result.stdout)
            sys.stdout.flush()
        except Exception:
            pass
    return 0


def run_codex(args) -> int:
    sessions = Path(args.sessions).expanduser()
    return _run_collector(
        args, lambda: collect_codex(sessions), f"no rate_limits found under {sessions}", source="codex"
    )


def run_opencode(args) -> int:
    path = Path(args.db).expanduser()
    return _run_collector(
        args,
        lambda: collect_opencode(path, limits_file=Path(args.limits).expanduser()),
        f"no OpenAI session active in the last {OPENCODE_STALE_SECONDS / 3600:g} h in {path} "
        f"and no current limit snapshot; nothing pushed",
        source="opencode",
    )


def run_codex_live(args) -> int:
    def collect():
        try:
            return collect_codex_live(args.codex)
        except CodexLiveError as exc:
            if not getattr(args, "quiet", False):
                print(f"jiri-usage: {exc}", file=sys.stderr)
            return None
    return _run_collector(args, collect, "no ChatGPT limits from codex; nothing pushed", source="codex-live")


def _run_collector(args, collect, empty_message: str, *, source: str = "") -> int:
    url, token = _settings(args)
    quiet = getattr(args, "quiet", False)
    while True:
        try:
            report = collect()
            if report is not None and source:
                # Tells the Pi's /admin/usage which collector this came from.
                report = {**report, "source": source}
        except (sqlite3.Error, OSError) as exc:
            report = None
            if not quiet:
                print(f"jiri-usage: could not read usage: {exc}", file=sys.stderr)
        if report is None:
            if not quiet:
                print(f"jiri-usage: {empty_message}", file=sys.stderr)
        elif args.dry_run:
            print(json.dumps(report, indent=2))
        elif not (url and token):
            print("jiri-usage: set JIRI_URL and JIRI_USAGE_TOKEN (or --url/--token)", file=sys.stderr)
            return 2
        else:
            try:
                result = push(report, url, token)
                if not quiet:
                    print(f"jiri-usage: pushed chatgpt (stored={result.get('stored')})")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                if not quiet:
                    print(f"jiri-usage: push failed: {exc}", file=sys.stderr)
                if not args.loop:
                    return 1
        if not args.loop:
            return 0
        time.sleep(max(10.0, float(args.loop)))


def run_internal_push(args) -> int:
    url, token = _settings(args)
    try:
        push(json.loads(args.payload), url, token)
    except Exception:
        return 1
    return 0


CONFIG_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "jiri" / "usage.env"


def _config_file() -> dict[str, str]:
    """KEY=VALUE lines from ~/.config/jiri/usage.env (keeps the token out of
    settings.json and shell history). Missing file -> {}."""
    values: dict[str, str] = {}
    try:
        for line in CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.removeprefix("export ").partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


def _settings(args) -> tuple[str, str]:
    file_values = _config_file()
    url = (getattr(args, "url", None) or os.environ.get("JIRI_URL") or file_values.get("JIRI_URL") or "").strip()
    token = (
        getattr(args, "token", None) or os.environ.get("JIRI_USAGE_TOKEN") or file_values.get("JIRI_USAGE_TOKEN") or ""
    ).strip()
    return url, token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--url", help="JIRI base URL (default $JIRI_URL)")
    common.add_argument("--token", help="push token (default $JIRI_USAGE_TOKEN)")
    sub = parser.add_subparsers(dest="mode", required=True)

    claude = sub.add_parser("claude-statusline", parents=[common], help="Claude Code statusLine.command wrapper")
    claude.add_argument("--then", default="", help="statusline command to run with the same stdin")
    claude.set_defaults(func=run_claude_statusline)

    opencode = sub.add_parser("opencode", parents=[common], help="push OpenCode ChatGPT usage (default)")
    opencode.add_argument("--loop", type=float, default=0, help="repeat every SECONDS (min 10)")
    opencode.add_argument("--db", default=str(OPENCODE_DB), help="OpenCode SQLite store (opened read-only)")
    opencode.add_argument("--limits", default=str(OPENCODE_LIMITS_FILE),
                          help="rate-limit snapshot written by the JIRI OpenCode plugin")
    opencode.add_argument("--dry-run", action="store_true", help="print the report instead of pushing")
    opencode.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    opencode.set_defaults(func=run_opencode)

    codex = sub.add_parser("codex", parents=[common], help="push Codex CLI rate limits (legacy)")
    codex.add_argument("--loop", type=float, default=0, help="repeat every SECONDS (min 10)")
    codex.add_argument("--sessions", default=str(Path.home() / ".codex" / "sessions"))
    codex.add_argument("--dry-run", action="store_true", help="print the report instead of pushing")
    codex.set_defaults(func=run_codex)

    live = sub.add_parser("codex-live", parents=[common],
                          help="ChatGPT plan limits via OpenAI's codex CLI (what the Codex app shows)")
    live.add_argument("--codex", default="codex", help="codex binary (default: codex on PATH)")
    live.add_argument("--loop", type=float, default=0, help="repeat every SECONDS (min 10)")
    live.add_argument("--dry-run", action="store_true", help="print the report instead of pushing")
    live.add_argument("--quiet", action="store_true", help=argparse.SUPPRESS)
    live.set_defaults(func=run_codex_live)

    internal = sub.add_parser("_push", parents=[common])
    internal.add_argument("--payload", required=True)
    internal.set_defaults(func=run_internal_push)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
