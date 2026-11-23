"""Direct sign-in to Claude / ChatGPT so the Pi can poll usage limits itself.

This is the Pi's *own* OAuth session, separate from the laptop tools: the
owner signs in once from the admin page (PKCE, paste-back flow) and the web
process's background worker polls the providers' usage endpoints every few
minutes, writing rows through `usage.record()`. The laptop push
(scripts/jiri_usage_push.py) keeps working alongside it; whichever wrote
last is the row the display shows.

Rules:
- stdlib urllib only, 10 s timeout on every request;
- tokens live in the SQLite settings table under `usage.account.<provider>.*`
  and are never logged, rendered or returned by status();
- nothing here runs in the display loop; `poll_all()` is for the web worker.

OAuth parameters were read from the clients installed on the dev machine
(Claude Code 2.1.330 bundle; OpenCode's bundled ChatGPT plugin, which mirrors
the Codex CLI). See the PROVIDERS table.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

from . import db, usage

log = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 300.0
REFRESH_MARGIN_SECONDS = 120.0
USER_AGENT = "jiri-usage/1"
MAX_ERROR_CHARS = 160

PROVIDERS: dict[str, dict[str, object]] = {
    "claude": {
        "title": "Claude",
        # Claude Code: CLAUDE_AI_AUTHORIZE_URL / TOKEN_URL / MANUAL_REDIRECT_URL / CLIENT_ID.
        "authorize_url": "https://claude.com/cai/oauth/authorize",
        "token_url": "https://platform.claude.com/v1/oauth/token",
        "redirect_uri": "https://platform.claude.com/oauth/code/callback",
        "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        "scope": "user:profile user:inference",
        "extra_authorize": {"code": "true"},
        "token_encoding": "json",
        "usage_url": "https://api.anthropic.com/api/oauth/usage",
        "paste_hint": "After signing in, the page shows a code like abc123#xyz. Paste the whole code.",
    },
    "chatgpt": {
        "title": "ChatGPT",
        # Codex CLI / OpenCode "Codex browser" login.
        "authorize_url": "https://auth.openai.com/oauth/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "redirect_uri": "http://localhost:1455/auth/callback",
        "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "scope": "openid profile email offline_access",
        "extra_authorize": {
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "originator": "opencode",
        },
        "token_encoding": "form",
        "usage_url": "https://chatgpt.com/backend-api/wham/usage",
        "paste_hint": (
            "After signing in, the browser tries to open localhost:1455 and shows an error page. "
            "That's expected: copy the full address from the address bar and paste it here."
        ),
    },
}
CLAUDE_OAUTH_BETA = "oauth-2025-04-20"
OPENAI_AUTH_CLAIM = "https://api.openai.com/auth"

_FIELDS = (
    "access_token",
    "refresh_token",
    "expires_at",
    "account_id",
    "email",
    "plan",
    "connected_at",
    "last_check_at",
    "last_ok_at",
    "last_error",
    "needs_reconnect",
)

# Tests replace this; production uses urllib directly.
_urlopen: Callable[..., object] = urllib.request.urlopen


class AuthError(Exception):
    """The provider rejected our credentials (401/403 or invalid_grant)."""


class ProviderError(Exception):
    """Anything else that went wrong talking to a provider. Message is safe to show."""


# ---------------------------------------------------------------- login flow


def start_login(provider: str) -> dict[str, str]:
    """New PKCE verifier + state and the authorize URL. The caller keeps
    `state` and `verifier` server-side (Flask session) until the paste."""
    spec = _spec(provider)
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _b64url(secrets.token_bytes(24))
    params: dict[str, str] = {}
    params.update(spec["extra_authorize"])  # type: ignore[arg-type]
    params.update(
        {
            "client_id": str(spec["client_id"]),
            "response_type": "code",
            "redirect_uri": str(spec["redirect_uri"]),
            "scope": str(spec["scope"]),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    url = f"{spec['authorize_url']}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
    return {"provider": provider, "state": state, "verifier": verifier, "url": url}


def parse_pasted(text: str) -> tuple[str, str | None]:
    """Accept a full redirect URL (`...?code=..&state=..`), a bare query
    string, Claude's `code#state`, or a bare code. Returns (code, state)."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Paste the code or the address you were sent to.")
    if "code=" in raw:
        query = urllib.parse.urlsplit(raw).query if "://" in raw else raw.lstrip("?")
        values = urllib.parse.parse_qs(query)
        if "error" in values:
            raise ValueError(f"The provider returned an error: {values.get('error_description', values['error'])[0][:120]}")
        code = (values.get("code") or [""])[0].strip()
        state = (values.get("state") or [None])[0]
        if not code:
            raise ValueError("No code found in what you pasted.")
        return code, state.strip() if state else None
    if "#" in raw:
        code, _, state = raw.partition("#")
        if not code or not state:
            raise ValueError("That doesn't look like the full code. Copy all of it, including the # in the middle.")
        return code.strip(), state.strip()
    if any(ch.isspace() for ch in raw):
        raise ValueError("That doesn't look like a code.")
    return raw, None


def complete_login(
    provider: str,
    pasted: str,
    *,
    expected_state: str,
    verifier: str,
    db_path: str | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Exchange the pasted code for tokens and store them. Raises ValueError
    with a message that is safe to show."""
    spec = _spec(provider)
    code, state = parse_pasted(pasted)
    if state is not None and not secrets.compare_digest(state, expected_state):
        raise ValueError("This code belongs to a different sign-in attempt. Click Connect again.")
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": str(spec["redirect_uri"]),
        "client_id": str(spec["client_id"]),
        "code_verifier": verifier,
    }
    if provider == "claude":
        body["state"] = expected_state
    try:
        data = _token_request(spec, body)
    except AuthError:
        raise ValueError("The provider rejected that code (it may have expired). Click Connect and try again.") from None
    except ProviderError as exc:
        raise ValueError(f"Sign-in failed: {exc}") from None
    now = time.time() if now is None else now
    values = _token_values(provider, data, now=now)
    if not values.get("refresh_token"):
        raise ValueError("Sign-in did not return a refresh token; JIRI can't keep the session alive.")
    values.update({"connected_at": str(now), "last_error": "", "needs_reconnect": "0"})
    _clear(provider, db_path)
    _save(provider, values, db_path)
    return status(provider, db_path=db_path)


def disconnect(provider: str, db_path: str | None = None) -> None:
    _spec(provider)
    _clear(provider, db_path)


# ---------------------------------------------------------------- status


def status(provider: str, db_path: str | None = None, *, now: float | None = None) -> dict[str, object]:
    """Display-safe view: never includes tokens."""
    spec = _spec(provider)
    values = _load(provider, db_path)
    connected = bool(values.get("refresh_token") or values.get("access_token"))
    needs_reconnect = connected and values.get("needs_reconnect") == "1"
    return {
        "provider": provider,
        "title": spec["title"],
        "connected": connected,
        "needs_reconnect": needs_reconnect,
        "email": values.get("email") or "",
        "plan": values.get("plan") or "",
        "connected_at": _float(values.get("connected_at")),
        "last_check_at": _float(values.get("last_check_at")),
        "last_ok_at": _float(values.get("last_ok_at")),
        "last_error": values.get("last_error") or "",
        "paste_hint": spec["paste_hint"],
    }


def statuses(db_path: str | None = None) -> dict[str, dict[str, object]]:
    return {provider: status(provider, db_path=db_path) for provider in PROVIDERS}


def is_connected(provider: str, db_path: str | None = None) -> bool:
    return bool(status(provider, db_path=db_path)["connected"])


# ---------------------------------------------------------------- polling


def check_now(provider: str, db_path: str | None = None, *, now: float | None = None) -> dict[str, object]:
    """Fetch usage once, store it via usage.record(), and record the outcome.
    Never raises; the result is the new status()."""
    _spec(provider)
    values = _load(provider, db_path)
    if not (values.get("refresh_token") or values.get("access_token")):
        return status(provider, db_path=db_path)
    now = time.time() if now is None else now
    outcome: dict[str, str] = {"last_check_at": str(now)}
    try:
        report = _fetch_with_refresh(provider, values, db_path, now=now)
        usage.record(report, db_path=db_path, now=now)
        outcome.update({"last_ok_at": str(now), "last_error": "", "needs_reconnect": "0"})
    except AuthError:
        outcome.update({"last_error": "reconnect needed: the provider rejected JIRI's sign-in", "needs_reconnect": "1"})
    except ProviderError as exc:
        outcome["last_error"] = str(exc)[:MAX_ERROR_CHARS]
    except Exception as exc:  # noqa: BLE001 - never crash the worker
        outcome["last_error"] = f"unexpected {exc.__class__.__name__}"
    _save(provider, outcome, db_path)
    if outcome.get("last_error"):
        log.info("usage poll %s: %s", provider, outcome["last_error"])  # never includes tokens
    return status(provider, db_path=db_path)


def poll_all(db_path: str | None = None) -> dict[str, str]:
    """Background-worker entry point. Skips providers that aren't connected or
    need a reconnect (no network, no writes). Never raises."""
    results: dict[str, str] = {}
    for provider in PROVIDERS:
        try:
            current = status(provider, db_path=db_path)
            if not current["connected"]:
                continue
            if current["needs_reconnect"]:
                results[provider] = "reconnect needed"
                continue
            after = check_now(provider, db_path=db_path)
            results[provider] = str(after["last_error"] or "ok")
        except Exception as exc:  # noqa: BLE001
            results[provider] = f"unexpected {exc.__class__.__name__}"
    return results


def _fetch_with_refresh(provider: str, values: dict[str, str], db_path: str | None, *, now: float) -> dict:
    spec = _spec(provider)
    access = values.get("access_token") or ""
    expires_at = _float(values.get("expires_at"))
    if not access or (expires_at is not None and expires_at - REFRESH_MARGIN_SECONDS <= now):
        access = _refresh(provider, values, db_path, now=now)
        values = _load(provider, db_path)
    try:
        payload = _usage_request(provider, spec, access, values)
    except AuthError:
        # Access token revoked early: one refresh, one retry.
        if not values.get("refresh_token"):
            raise
        access = _refresh(provider, values, db_path, now=now)
        values = _load(provider, db_path)
        payload = _usage_request(provider, spec, access, values)
    if provider == "claude":
        return parse_claude_usage(payload, label=values.get("plan") or "")
    return parse_chatgpt_usage(payload, label=values.get("plan") or "", now=now)


def _refresh(provider: str, values: dict[str, str], db_path: str | None, *, now: float) -> str:
    spec = _spec(provider)
    refresh_token = values.get("refresh_token") or ""
    if not refresh_token:
        raise AuthError("no refresh token")
    body = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": str(spec["client_id"])}
    if provider == "claude":
        body["scope"] = str(spec["scope"])
    data = _token_request(spec, body)
    new_values = _token_values(provider, data, now=now)
    # Keep identity fields we already know if the refresh response omits them.
    for key in ("account_id", "email", "plan"):
        if not new_values.get(key) and values.get(key):
            new_values.pop(key, None)
    if not new_values.get("refresh_token"):
        new_values.pop("refresh_token", None)  # provider kept the old one
    _save(provider, new_values, db_path)
    return str(new_values["access_token"])


def _usage_request(provider: str, spec: dict[str, object], access: str, values: dict[str, str]) -> dict:
    headers = {"Authorization": f"Bearer {access}", "Accept": "application/json", "User-Agent": USER_AGENT}
    if provider == "claude":
        headers["anthropic-beta"] = CLAUDE_OAUTH_BETA
        headers["Content-Type"] = "application/json"
    else:
        account_id = values.get("account_id") or ""
        if not account_id:
            raise AuthError("no ChatGPT account id")
        headers["ChatGPT-Account-Id"] = account_id
    return _http_json("GET", str(spec["usage_url"]), headers=headers)


# ---------------------------------------------------------------- parsing


def parse_claude_usage(payload: dict, *, label: str = "") -> dict:
    """{"five_hour": {"utilization": 23.0, "resets_at": "2026-..Z"},
        "seven_day": {...}} -> a usage push payload."""
    report: dict[str, object] = {"provider": "claude", "source": "claude-account", "label": label}
    for key, prefix in (("five_hour", "five_hour"), ("seven_day", "weekly")):
        window = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(window, dict):
            continue
        report[f"{prefix}_pct"] = _num(window.get("utilization"))
        report[f"{prefix}_resets_at"] = _epoch(window.get("resets_at"))
    return report


def parse_chatgpt_usage(payload: dict, *, label: str = "", now: float | None = None) -> dict:
    """wham/usage: {"plan_type": .., "rate_limit": {"primary_window": {
        "used_percent", "limit_window_seconds", "reset_after_seconds", "reset_at"},
        "secondary_window": {...}}} -> a usage push payload."""
    now = time.time() if now is None else now
    report: dict[str, object] = {"provider": "chatgpt", "source": "chatgpt-account"}
    plan = payload.get("plan_type") if isinstance(payload, dict) else None
    report["label"] = label or (str(plan) if plan else "")
    limits = payload.get("rate_limit") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return report
    for position, default in (("primary_window", "five_hour"), ("secondary_window", "weekly")):
        window = limits.get(position)
        if not isinstance(window, dict):
            continue
        seconds = _num(window.get("limit_window_seconds"))
        prefix = default
        if seconds is not None:
            prefix = "five_hour" if seconds <= 6 * 3600 else "weekly"
        reset = _num(window.get("reset_at"))
        if reset is None:
            after = _num(window.get("reset_after_seconds"))
            reset = None if after is None else now + after
        report[f"{prefix}_pct"] = _num(window.get("used_percent"))
        report[f"{prefix}_resets_at"] = reset
    return report


def _token_values(provider: str, data: dict, *, now: float) -> dict[str, str]:
    access = data.get("access_token")
    if not isinstance(access, str) or not access:
        raise ProviderError("token response had no access token")
    values = {"access_token": access}
    refresh = data.get("refresh_token")
    if isinstance(refresh, str) and refresh:
        values["refresh_token"] = refresh
    expires_in = _num(data.get("expires_in"))
    values["expires_at"] = str(now + (expires_in if expires_in is not None else 3600.0))
    if provider == "claude":
        account = data.get("account") if isinstance(data.get("account"), dict) else {}
        org = data.get("organization") if isinstance(data.get("organization"), dict) else {}
        values["account_id"] = str(account.get("uuid") or "")
        values["email"] = str(account.get("email_address") or "")
        values["plan"] = str(org.get("name") or "")
    else:
        claims = _jwt_claims(data.get("id_token")) or {}
        access_claims = _jwt_claims(access) or {}
        auth = claims.get(OPENAI_AUTH_CLAIM) or access_claims.get(OPENAI_AUTH_CLAIM) or {}
        if not isinstance(auth, dict):
            auth = {}
        values["account_id"] = str(auth.get("chatgpt_account_id") or claims.get("chatgpt_account_id") or "")
        values["email"] = str(claims.get("email") or "")
        values["plan"] = str(auth.get("chatgpt_plan_type") or "")
    return {key: value for key, value in values.items() if value != "" or key in {"access_token"}}


def _jwt_claims(token: object) -> dict | None:
    """Unverified JWT payload (we only read our own identity claims)."""
    if not isinstance(token, str) or token.count(".") < 2:
        return None
    try:
        part = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- HTTP


def _token_request(spec: dict[str, object], body: dict[str, str]) -> dict:
    if spec["token_encoding"] == "json":
        data = json.dumps(body).encode("utf-8")
        content_type = "application/json"
    else:
        data = urllib.parse.urlencode(body).encode("ascii")
        content_type = "application/x-www-form-urlencoded"
    headers = {"Content-Type": content_type, "Accept": "application/json", "User-Agent": USER_AGENT}
    try:
        return _http_json("POST", str(spec["token_url"]), headers=headers, data=data)
    except ProviderError as exc:
        # invalid_grant = refresh/code no longer valid -> reconnect.
        if "HTTP 400" in str(exc) and "invalid_grant" in str(getattr(exc, "detail", "")):
            raise AuthError("invalid_grant") from None
        raise


def _http_json(method: str, url: str, *, headers: dict[str, str], data: bytes | None = None) -> dict:
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    host = urllib.parse.urlsplit(url).netloc
    try:
        with _urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:  # type: ignore[attr-defined]
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AuthError(f"HTTP {exc.code}") from None
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", "replace")
        except Exception:
            pass
        error = ProviderError(f"{host} answered HTTP {exc.code}")
        error.detail = detail  # type: ignore[attr-defined]
        raise error from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ProviderError(f"{host} unreachable ({reason.__class__.__name__})") from None
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        raise ProviderError(f"{host} returned something that isn't JSON") from None
    if not isinstance(payload, dict):
        raise ProviderError(f"{host} returned an unexpected shape")
    return payload


# ---------------------------------------------------------------- storage


def _key(provider: str, field: str) -> str:
    return f"usage.account.{provider}.{field}"


def _load(provider: str, db_path: str | None) -> dict[str, str]:
    db.init_db(db_path)
    prefix = _key(provider, "")
    with db.connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE ?", (prefix + "%",)).fetchall()
    conn.close()
    return {str(row["key"])[len(prefix):]: str(row["value"]) for row in rows}


def _save(provider: str, values: dict[str, str], db_path: str | None) -> None:
    """One transaction, so a poll costs a single SD-card write."""
    clean = {field: str(value) for field, value in values.items() if field in _FIELDS}
    if not clean:
        return
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
            [(_key(provider, field), value) for field, value in clean.items()],
        )
    conn.close()


def _clear(provider: str, db_path: str | None) -> None:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.execute("DELETE FROM settings WHERE key LIKE ?", (_key(provider, "") + "%",))
    conn.close()


# ---------------------------------------------------------------- helpers


def _spec(provider: str) -> dict[str, object]:
    try:
        return PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"unknown provider {provider!r}") from None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _float(value: object) -> float | None:
    try:
        return None if value in (None, "") else float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _num(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _epoch(value: object) -> float | None:
    """ISO-8601 (with Z or offset, any fraction) or epoch seconds -> epoch."""
    number = _num(value)
    if number is not None:
        return number
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    # Python 3.10's fromisoformat wants 0, 3 or 6 fraction digits.
    if "." in text:
        head, _, rest = text.partition(".")
        digits = rest[: len(rest) - len(rest.lstrip("0123456789"))]
        tail = rest[len(digits):]
        text = f"{head}.{(digits + '000000')[:6]}{tail}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
