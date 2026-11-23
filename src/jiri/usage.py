"""Claude Code / ChatGPT (Codex) usage limits pushed from the owner's laptop.

The usage data lives on the laptop where Claude Code and Codex CLI run; a
small collector (scripts/jiri_usage_push.py) POSTs a summary to /api/usage and
this module keeps exactly one row per provider. The display only ever calls
`visible_latest()` (or `latest()`), which are read-only and never raise.

Alongside the per-provider row, the newest report from each *source*
(Claude Code statusline, OpenCode, legacy Codex logs) is kept in
`usage_sources` so the admin page can show which laptop collector is alive.
The push token lives in the `usage.push_token` setting (admin-generated);
`JIRI_USAGE_TOKEN` from the environment is still accepted for older setups.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import math
import os
import secrets
import sqlite3
import time
from urllib.parse import quote

from . import db

PROVIDERS = frozenset({"claude", "chatgpt"})
MAX_LABEL_CHARS = 40
PERCENT_FIELDS = ("context_pct", "five_hour_pct", "weekly_pct")
EPOCH_FIELDS = ("five_hour_resets_at", "weekly_resets_at")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS usage_reports (
    provider TEXT PRIMARY KEY,
    context_pct REAL,
    five_hour_pct REAL,
    five_hour_resets_at REAL,
    weekly_pct REAL,
    weekly_resets_at REAL,
    updated_at REAL NOT NULL,
    label TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS usage_sources (
    source TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    context_pct REAL,
    five_hour_pct REAL,
    five_hour_resets_at REAL,
    weekly_pct REAL,
    weekly_resets_at REAL,
    updated_at REAL NOT NULL,
    label TEXT NOT NULL DEFAULT ''
);
"""

# Laptop collectors, in display order. A push that names no source (older
# copies of jiri_usage_push.py) is attributed to its provider's default.
SOURCES: tuple[dict[str, str], ...] = (
    {"id": "claude-statusline", "provider": "claude", "title": "Claude", "via": "Claude Code statusline"},
    {"id": "opencode", "provider": "chatgpt", "title": "ChatGPT", "via": "OpenCode plugin"},
    {"id": "codex", "provider": "chatgpt", "title": "ChatGPT", "via": "Codex logs (legacy)"},
    # The Pi's own sign-in (usage_accounts.py), polled by the web worker.
    {"id": "claude-account", "provider": "claude", "title": "Claude", "via": "Direct sign-in (Pi polls)"},
    {"id": "chatgpt-account", "provider": "chatgpt", "title": "ChatGPT", "via": "Direct sign-in (Pi polls)"},
)
SOURCE_IDS = frozenset(source["id"] for source in SOURCES)
DEFAULT_SOURCE = {"claude": "claude-statusline", "chatgpt": "opencode"}
FRESH_SECONDS = 15 * 60.0

TOKEN_SETTING = "usage.push_token"
TOKEN_ENV = "JIRI_USAGE_TOKEN"
SHOW_SETTING = "usage.show.{provider}"

_COLUMNS = (
    "provider",
    "context_pct",
    "five_hour_pct",
    "five_hour_resets_at",
    "weekly_pct",
    "weekly_resets_at",
    "updated_at",
    "label",
)


@dataclass(frozen=True)
class UsageReport:
    provider: str  # "claude" | "chatgpt"
    context_pct: float | None
    five_hour_pct: float | None
    five_hour_resets_at: float | None  # epoch seconds
    weekly_pct: float | None
    weekly_resets_at: float | None  # epoch seconds
    updated_at: float  # epoch seconds when the Pi received it
    label: str = ""  # e.g. model name "Opus 4.5" / "gpt-5-codex"


def latest(db_path: str | None = None) -> dict[str, UsageReport]:
    """Return the newest report per provider. Read-only; {} on any problem."""
    try:
        path = db.get_db_path(db_path)
        # mode=ro: never creates the file, never writes, never runs DDL.
        conn = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=1)
    except Exception:
        return {}
    try:
        rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM usage_reports").fetchall()
    except Exception:  # missing table, locked db, corrupt file...
        return {}
    finally:
        conn.close()
    reports: dict[str, UsageReport] = {}
    for row in rows:
        try:
            report = _row_to_report(row)
        except Exception:
            continue
        reports[report.provider] = report
    return reports


def validate(report: dict, *, now: float | None = None) -> UsageReport:
    """Turn an untrusted push payload into a UsageReport. Raises ValueError."""
    if not isinstance(report, dict):
        raise ValueError("usage report must be a JSON object")
    provider = str(report.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of {sorted(PROVIDERS)}")
    values: dict[str, float | None] = {}
    for field in PERCENT_FIELDS:
        number = _number(report.get(field), field)
        values[field] = None if number is None else min(100.0, max(0.0, number))
    for field in EPOCH_FIELDS:
        number = _number(report.get(field), field)
        values[field] = number if number is not None and number > 0 else None
    label = report.get("label") or ""
    if not isinstance(label, str):
        raise ValueError("label must be a string")
    label = " ".join(label.split())[:MAX_LABEL_CHARS]
    return UsageReport(
        provider=provider,
        context_pct=values["context_pct"],
        five_hour_pct=values["five_hour_pct"],
        five_hour_resets_at=values["five_hour_resets_at"],
        weekly_pct=values["weekly_pct"],
        weekly_resets_at=values["weekly_resets_at"],
        updated_at=float(time.time() if now is None else now),
        label=label,
    )


def record(report: dict, *, db_path: str | None = None, now: float | None = None) -> UsageReport:
    """Validate and upsert one row per provider."""
    clean = validate(report, now=now)
    _write(clean, db_path, source_of(report, clean.provider))
    return clean


def source_of(report: object, provider: str) -> str:
    """The collector that sent a push; unknown/missing -> provider default."""
    raw = report.get("source") if isinstance(report, dict) else None
    source = str(raw or "").strip().lower()
    known = {item["id"]: item["provider"] for item in SOURCES}
    if known.get(source) == provider:
        return source
    return DEFAULT_SOURCE[provider]


def record_if_changed(
    report: dict,
    *,
    db_path: str | None = None,
    now: float | None = None,
    min_interval: float = 30.0,
) -> tuple[UsageReport, bool]:
    """Like record(), but skip the SD-card write for a recent, unchanged row.

    Returns (report, stored). A row is skipped when the same provider was
    written less than `min_interval` seconds ago and every value is equal
    after rounding to one decimal.
    """
    clean = validate(report, now=now)
    previous = latest(db_path).get(clean.provider)
    if (
        previous is not None
        and 0 <= clean.updated_at - previous.updated_at < min_interval
        and _fingerprint(previous) == _fingerprint(clean)
    ):
        return previous, False
    _write(clean, db_path, source_of(report, clean.provider))
    return clean, True


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _write(report: UsageReport, db_path: str | None, source: str | None = None) -> None:
    values = tuple(getattr(report, column) for column in _COLUMNS)
    placeholders = ", ".join("?" * len(_COLUMNS))
    with db.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(f"INSERT OR REPLACE INTO usage_reports({', '.join(_COLUMNS)}) VALUES({placeholders})", values)
        if source:
            conn.execute(
                f"INSERT OR REPLACE INTO usage_sources(source, {', '.join(_COLUMNS)}) VALUES(?, {placeholders})",
                (source, *values),
            )
    conn.close()


# ------------------------------------------------------------ display filter


def shown_providers(db_path: str | None = None) -> dict[str, bool]:
    """Admin toggles `usage.show.<provider>` (default on). Read-only."""
    shown = {provider: True for provider in PROVIDERS}
    conn = _connect_ro(db_path)
    if conn is None:
        return shown
    try:
        for provider in PROVIDERS:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (SHOW_SETTING.format(provider=provider),)).fetchone()
            if row is not None:
                shown[provider] = _truthy(row[0])
    except Exception:
        pass
    finally:
        conn.close()
    return shown


def visible_latest(db_path: str | None = None) -> dict[str, UsageReport]:
    """latest() minus the providers the admin hid. Read-only; never raises."""
    reports = latest(db_path)
    if not reports:
        return reports
    shown = shown_providers(db_path)
    return {provider: report for provider, report in reports.items() if shown.get(provider, True)}


def set_shown(provider: str, shown: bool, db_path: str | None = None) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    db.set_setting(SHOW_SETTING.format(provider=provider), "1" if shown else "0", db_path=db_path)


# ------------------------------------------------------------ admin monitor


def source_reports(db_path: str | None = None) -> dict[str, UsageReport]:
    """Newest report per source. Read-only; {} on any problem."""
    conn = _connect_ro(db_path)
    if conn is None:
        return {}
    try:
        rows = conn.execute(f"SELECT source, {', '.join(_COLUMNS)} FROM usage_sources").fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    reports: dict[str, UsageReport] = {}
    for row in rows:
        try:
            reports[str(row[0])] = _row_to_report(row[1:])
        except Exception:
            continue
    return reports


def sources_status(db_path: str | None = None, *, now: float | None = None) -> list[dict[str, object]]:
    """One entry per known collector, for the admin page and its JSON API.
    Never includes the push token."""
    now = time.time() if now is None else now
    reports = source_reports(db_path)
    providers = latest(db_path)
    shown = shown_providers(db_path)
    entries: list[dict[str, object]] = []
    for source in SOURCES:
        report = reports.get(source["id"])
        provider_row = providers.get(source["provider"])
        if report is None:
            freshness, age = "never", None
        else:
            age = max(0.0, now - report.updated_at)
            freshness = "fresh" if age < FRESH_SECONDS else "stale"
        entries.append(
            {
                "id": source["id"],
                "provider": source["provider"],
                "title": source["title"],
                "via": source["via"],
                "shown_on_display": shown.get(source["provider"], True),
                "freshness": freshness,
                "last_push_at": None if report is None else report.updated_at,
                "age_seconds": None if age is None else round(age),
                # Is this source the one currently feeding the display row?
                "feeds_display": bool(
                    report is not None and provider_row is not None and provider_row.updated_at == report.updated_at
                ),
                "label": "" if report is None else report.label,
                "context_pct": None if report is None else report.context_pct,
                "five_hour_pct": None if report is None else report.five_hour_pct,
                "five_hour_resets_at": None if report is None else report.five_hour_resets_at,
                "five_hour_resets_in": _until(report and report.five_hour_resets_at, now),
                "weekly_pct": None if report is None else report.weekly_pct,
                "weekly_resets_at": None if report is None else report.weekly_resets_at,
                "weekly_resets_in": _until(report and report.weekly_resets_at, now),
            }
        )
    return entries


def clear(provider: str, db_path: str | None = None) -> int:
    """Delete everything stored for one provider (display row + its sources)."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    with db.connect(db_path) as conn:
        ensure_schema(conn)
        removed = conn.execute("DELETE FROM usage_reports WHERE provider = ?", (provider,)).rowcount
        removed += conn.execute("DELETE FROM usage_sources WHERE provider = ?", (provider,)).rowcount
    conn.close()
    return removed


# ------------------------------------------------------------ push token


def db_push_token(db_path: str | None = None) -> str | None:
    value = db.get_setting(TOKEN_SETTING, db_path=db_path)
    return value.strip() if value and value.strip() else None


def env_push_token() -> str | None:
    value = os.environ.get(TOKEN_ENV, "").strip()
    return value or None


def generate_push_token(db_path: str | None = None) -> str:
    """Create (or rotate) the DB push token. The old DB token stops working."""
    token = secrets.token_urlsafe(24)
    db.set_setting(TOKEN_SETTING, token, db_path=db_path)
    return token


def mask_token(token: str | None) -> str:
    if not token:
        return ""
    return "\u2022\u2022\u2022\u2022" + token[-4:]


def push_enabled(db_path: str | None = None) -> bool:
    return bool(db_push_token(db_path) or env_push_token())


def check_push_token(supplied: str, db_path: str | None = None) -> bool:
    """Constant-time match against the DB token and the legacy env token."""
    supplied_bytes = (supplied or "").strip().encode()
    ok = False
    for expected in (db_push_token(db_path), env_push_token()):
        if expected:
            # No short-circuit: both candidates are always compared.
            ok = hmac.compare_digest(supplied_bytes, expected.encode()) or ok
    return ok and bool(supplied_bytes)


def token_status(db_path: str | None = None) -> dict[str, object]:
    """Masked view of the push credentials, safe for templates and JSON."""
    token = db_push_token(db_path)
    env = env_push_token()
    return {
        "enabled": bool(token or env),
        "db_token_set": token is not None,
        "db_token_masked": mask_token(token),
        "env_token_set": env is not None,
        "env_token_masked": mask_token(env),
    }


def _connect_ro(db_path: str | None) -> sqlite3.Connection | None:
    try:
        path = db.get_db_path(db_path)
        return sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=1)
    except Exception:
        return None


def _truthy(value: object) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _until(epoch: float | None, now: float) -> float | None:
    if not epoch:
        return None
    return max(0.0, epoch - now)


def _fingerprint(report: UsageReport) -> tuple:
    def r(value: float | None) -> float | None:
        return None if value is None else round(value, 1)

    return (
        r(report.context_pct),
        r(report.five_hour_pct),
        r(report.five_hour_resets_at),
        r(report.weekly_pct),
        r(report.weekly_resets_at),
        report.label,
    )


def _number(value: object, field: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number") from None
    if not math.isfinite(number):
        return None
    return number


def _opt_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _row_to_report(row: tuple) -> UsageReport:
    data = dict(zip(_COLUMNS, row))
    return UsageReport(
        provider=str(data["provider"]),
        context_pct=_opt_float(data["context_pct"]),
        five_hour_pct=_opt_float(data["five_hour_pct"]),
        five_hour_resets_at=_opt_float(data["five_hour_resets_at"]),
        weekly_pct=_opt_float(data["weekly_pct"]),
        weekly_resets_at=_opt_float(data["weekly_resets_at"]),
        updated_at=float(data["updated_at"]),
        label=str(data["label"] or ""),
    )
