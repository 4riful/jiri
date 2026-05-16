from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import argparse
import sys
import time
from typing import TYPE_CHECKING

import requests

from . import db, persona
from .config import AppConfig, load_config

if TYPE_CHECKING:
    from .runtime import JiriRuntime


OFFSET_KEY = "telegram.update_offset"
LAST_POLL_KEY = "telegram.last_poll_at"
LAST_UPDATE_KEY = "telegram.last_update_at"
LAST_ERROR_KEY = "telegram.last_error"
LAST_UNAUTHORIZED_CHAT_KEY = "telegram.last_unauthorized_chat_id"
SETTINGS_INITIALIZED_KEY = "telegram.settings_initialized"
ENABLED_KEY = "telegram.enabled"
BOT_TOKEN_KEY = "telegram.bot_token"
ALLOWED_CHAT_IDS_KEY = "telegram.allowed_chat_ids"
COMMAND_CHAT_ID_KEY = "telegram.command_chat_id"
POLLING_TIMEOUT_KEY = "telegram.polling_timeout_seconds"
BOT_USERNAME_KEY = "telegram.bot_username"
BOT_ID_KEY = "telegram.bot_id"


class TelegramError(RuntimeError):
    """Raised when Telegram polling or sending fails."""


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool
    bot_token: str
    allowed_chat_ids: tuple[int, ...]
    command_chat_id: int | None
    polling_timeout_seconds: int
    bot_username: str = ""
    bot_id: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.bot_token and self.allowed_chat_ids)


@dataclass(frozen=True)
class TelegramClient:
    token: str
    request_timeout_seconds: int = 30
    base_url: str = "https://api.telegram.org"

    def get_me(self) -> dict[str, object]:
        return self._request("getMe")

    def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 25,
        limit: int = 100,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, object]]:
        payload: dict[str, object] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        result = self._request("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramError("Telegram getUpdates returned an unexpected response")
        return [item for item in result if isinstance(item, dict)]

    def send_message(self, chat_id: int, text: str) -> dict[str, object]:
        return self._request("sendMessage", {"chat_id": chat_id, "text": text})

    def delete_webhook(self) -> dict[str, object]:
        return self._request("deleteWebhook")

    def _request(self, method: str, payload: dict[str, object] | None = None) -> object:
        if not self.token.strip():
            raise TelegramError("Telegram bot token is not configured")
        url = f"{self.base_url}/bot{self.token}/{method}"
        try:
            response = requests.post(url, json=payload or {}, timeout=self.request_timeout_seconds)
        except requests.RequestException as exc:
            raise TelegramError(f"Telegram request failed: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramError("Telegram returned non-JSON response") from exc
        if not isinstance(data, dict) or not data.get("ok"):
            description = data.get("description") if isinstance(data, dict) else response.text
            raise TelegramError(f"Telegram API error: {description}")
        return data.get("result")


def ensure_settings(db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    cfg = config or load_config()
    if db.get_setting(SETTINGS_INITIALIZED_KEY, db_path=db_path) != "1":
        db.set_setting(ENABLED_KEY, _bool_to_setting(cfg.telegram.enabled), db_path=db_path)
        db.set_setting(BOT_TOKEN_KEY, cfg.telegram.bot_token.strip(), db_path=db_path)
        db.set_setting(ALLOWED_CHAT_IDS_KEY, _format_chat_ids(cfg.telegram.allowed_chat_ids), db_path=db_path)
        db.set_setting(COMMAND_CHAT_ID_KEY, "" if cfg.telegram.command_chat_id is None else str(cfg.telegram.command_chat_id), db_path=db_path)
        db.set_setting(POLLING_TIMEOUT_KEY, str(cfg.telegram.polling_timeout_seconds), db_path=db_path)
        db.set_setting(SETTINGS_INITIALIZED_KEY, "1", db_path=db_path)
    return get_settings(db_path=db_path, config=cfg)


def get_settings(db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    cfg = config or load_config()
    db.init_db(db_path)
    if db.get_setting(SETTINGS_INITIALIZED_KEY, db_path=db_path) != "1":
        return ensure_settings(db_path=db_path, config=cfg)
    return TelegramSettings(
        enabled=_setting_bool(db.get_setting(ENABLED_KEY, db_path=db_path), cfg.telegram.enabled),
        bot_token=(db.get_setting(BOT_TOKEN_KEY, db_path=db_path) or "").strip(),
        allowed_chat_ids=_parse_chat_ids(db.get_setting(ALLOWED_CHAT_IDS_KEY, db_path=db_path) or ""),
        command_chat_id=_parse_optional_chat_id(db.get_setting(COMMAND_CHAT_ID_KEY, db_path=db_path) or ""),
        polling_timeout_seconds=_setting_int(
            db.get_setting(POLLING_TIMEOUT_KEY, db_path=db_path),
            cfg.telegram.polling_timeout_seconds,
            minimum=1,
            maximum=50,
        ),
        bot_username=db.get_setting(BOT_USERNAME_KEY, db_path=db_path) or "",
        bot_id=db.get_setting(BOT_ID_KEY, db_path=db_path) or "",
    )


def save_settings(
    *,
    enabled: bool,
    bot_token: str,
    allowed_chat_ids: str,
    command_chat_id: str = "",
    polling_timeout_seconds: int = 25,
    db_path: str | None = None,
    config: AppConfig | None = None,
) -> TelegramSettings:
    ensure_settings(db_path=db_path, config=config)
    clean_token = bot_token.strip()
    chats = _parse_chat_ids(allowed_chat_ids)
    command_chat = _parse_optional_chat_id(command_chat_id)
    if polling_timeout_seconds < 1 or polling_timeout_seconds > 50:
        raise ValueError("Polling timeout must be between 1 and 50 seconds")
    if enabled and not clean_token:
        raise ValueError("Telegram bot token is required when Telegram is enabled")
    if enabled and not chats:
        raise ValueError("At least one allowed chat ID is required when Telegram is enabled")
    db.set_setting(ENABLED_KEY, _bool_to_setting(enabled), db_path=db_path)
    db.set_setting(BOT_TOKEN_KEY, clean_token, db_path=db_path)
    db.set_setting(ALLOWED_CHAT_IDS_KEY, _format_chat_ids(chats), db_path=db_path)
    db.set_setting(COMMAND_CHAT_ID_KEY, "" if command_chat is None else str(command_chat), db_path=db_path)
    db.set_setting(POLLING_TIMEOUT_KEY, str(polling_timeout_seconds), db_path=db_path)
    db.set_setting(SETTINGS_INITIALIZED_KEY, "1", db_path=db_path)
    return get_settings(db_path=db_path, config=config)


def clear_token(db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    ensure_settings(db_path=db_path, config=config)
    db.set_setting(BOT_TOKEN_KEY, "", db_path=db_path)
    db.set_setting(ENABLED_KEY, "0", db_path=db_path)
    db.delete_setting(BOT_USERNAME_KEY, db_path=db_path)
    db.delete_setting(BOT_ID_KEY, db_path=db_path)
    return get_settings(db_path=db_path, config=config)


def update_bot_identity(username: str | None = None, bot_id: str | int | None = None, db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    current = ensure_settings(db_path=db_path, config=config)
    if username:
        db.set_setting(BOT_USERNAME_KEY, str(username).strip(), db_path=db_path)
    if bot_id is not None and str(bot_id).strip():
        db.set_setting(BOT_ID_KEY, str(bot_id).strip(), db_path=db_path)
    return get_settings(db_path=db_path, config=config)


def toggle_enabled(enabled: bool, db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    current = ensure_settings(db_path=db_path, config=config)
    if enabled and not current.bot_token:
        raise ValueError("Telegram bot token is required when enabling Telegram")
    if enabled and not current.allowed_chat_ids:
        raise ValueError("At least one allowed chat ID is required when enabling Telegram")
    db.set_setting(ENABLED_KEY, _bool_to_setting(enabled), db_path=db_path)
    return get_settings(db_path=db_path, config=config)


def update_polling_timeout(seconds: int, db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    current = ensure_settings(db_path=db_path, config=config)
    if seconds < 1 or seconds > 50:
        raise ValueError("Polling timeout must be between 1 and 50 seconds")
    db.set_setting(POLLING_TIMEOUT_KEY, str(seconds), db_path=db_path)
    return get_settings(db_path=db_path, config=config)


def reset_runtime_state(db_path: str | None = None) -> None:
    for key in (OFFSET_KEY, LAST_POLL_KEY, LAST_UPDATE_KEY, LAST_ERROR_KEY, LAST_UNAUTHORIZED_CHAT_KEY):
        db.delete_setting(key, db_path=db_path)


def add_allowed_chat(chat_id: int | str, db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    current = ensure_settings(db_path=db_path, config=config)
    parsed = _parse_optional_chat_id(str(chat_id))
    if parsed is None:
        raise ValueError("Chat ID is required")
    chats = tuple(dict.fromkeys((*current.allowed_chat_ids, parsed)))
    return save_settings(
        enabled=current.enabled,
        bot_token=current.bot_token,
        allowed_chat_ids=_format_chat_ids(chats),
        command_chat_id="" if current.command_chat_id is None else str(current.command_chat_id),
        polling_timeout_seconds=current.polling_timeout_seconds,
        db_path=db_path,
        config=config,
    )


def remove_allowed_chat(chat_id: int | str, db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    current = ensure_settings(db_path=db_path, config=config)
    parsed = _parse_optional_chat_id(str(chat_id))
    if parsed is None:
        raise ValueError("Chat ID is required")
    chats = tuple(chat for chat in current.allowed_chat_ids if chat != parsed)
    return save_settings(
        enabled=current.enabled and bool(chats),
        bot_token=current.bot_token,
        allowed_chat_ids=_format_chat_ids(chats),
        command_chat_id="" if current.command_chat_id is None else str(current.command_chat_id),
        polling_timeout_seconds=current.polling_timeout_seconds,
        db_path=db_path,
        config=config,
    )


def set_allowed_chat_ids(chat_ids: str, db_path: str | None = None, config: AppConfig | None = None) -> TelegramSettings:
    current = ensure_settings(db_path=db_path, config=config)
    return save_settings(
        enabled=current.enabled,
        bot_token=current.bot_token,
        allowed_chat_ids=chat_ids,
        command_chat_id="" if current.command_chat_id is None else str(current.command_chat_id),
        polling_timeout_seconds=current.polling_timeout_seconds,
        db_path=db_path,
        config=config,
    )


def get_allowed_chat_ids(db_path: str | None = None, config: AppConfig | None = None) -> tuple[int, ...]:
    return get_settings(db_path=db_path, config=config).allowed_chat_ids


def _bool_to_setting(value: bool) -> str:
    return "1" if value else "0"


def _setting_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip() in {"1", "true", "yes", "on"}


def _setting_int(value: str | None, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


def _parse_chat_ids(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    items = []
    for part in value.replace(";", ",").split(","):
        clean = part.strip()
        if not clean:
            continue
        try:
            items.append(int(clean))
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram chat ID: {clean}") from exc
    return tuple(dict.fromkeys(items))


def _parse_optional_chat_id(value: str) -> int | None:
    clean = value.strip()
    if not clean:
        return None
    try:
        return int(clean)
    except ValueError as exc:
        raise ValueError(f"Invalid Telegram chat ID: {clean}") from exc


def _format_chat_ids(chat_ids: tuple[int, ...]) -> str:
    return ",".join(str(chat_id) for chat_id in chat_ids)


def binding_status(config: AppConfig | None = None, db_path: str | None = None) -> dict[str, object]:
    settings = ensure_settings(db_path=db_path, config=config)
    token = settings.bot_token
    allowed = settings.allowed_chat_ids
    return {
        "enabled": settings.enabled,
        "configured": settings.configured,
        "bot_token": token,
        "token_configured": bool(token),
        "token_preview": _token_preview(token),
        "allowed_chat_ids": tuple(str(chat_id) for chat_id in allowed),
        "allowed_chat_count": len(allowed),
        "allowed_chat_ids_text": _format_chat_ids(allowed),
        "command_chat_id": "" if settings.command_chat_id is None else str(settings.command_chat_id),
        "polling_timeout_seconds": settings.polling_timeout_seconds,
        "bot_username": settings.bot_username,
        "bot_id": settings.bot_id,
        "mode": "polling",
        "webhook_required": False,
        "settings_source": "sqlite",
        "update_offset": get_update_offset(db_path=db_path),
        "last_poll_at": db.get_setting(LAST_POLL_KEY, db_path=db_path),
        "last_update_at": db.get_setting(LAST_UPDATE_KEY, db_path=db_path),
        "last_error": db.get_setting(LAST_ERROR_KEY, db_path=db_path),
        "last_unauthorized_chat_id": db.get_setting(LAST_UNAUTHORIZED_CHAT_KEY, db_path=db_path),
    }


def check_bot(config: AppConfig | None = None, client: TelegramClient | None = None) -> dict[str, object]:
    settings = get_settings(config=config)
    bot = client or TelegramClient(settings.bot_token)
    result = bot.get_me()
    if not isinstance(result, dict):
        raise TelegramError("Telegram getMe returned an unexpected response")
    return result


def check_bot_for_db(db_path: str | None = None, config: AppConfig | None = None, client: TelegramClient | None = None) -> dict[str, object]:
    settings = get_settings(db_path=db_path, config=config)
    bot = client or TelegramClient(settings.bot_token)
    result = bot.get_me()
    if not isinstance(result, dict):
        raise TelegramError("Telegram getMe returned an unexpected response")
    if result.get("username"):
        db.set_setting(BOT_USERNAME_KEY, str(result["username"]), db_path=db_path)
    if result.get("id"):
        db.set_setting(BOT_ID_KEY, str(result["id"]), db_path=db_path)
    db.set_setting(LAST_ERROR_KEY, "", db_path=db_path)
    return result


def discover_chats(config: AppConfig | None = None, client: TelegramClient | None = None, db_path: str | None = None) -> list[dict[str, object]]:
    settings = get_settings(db_path=db_path, config=config)
    bot = client or TelegramClient(settings.bot_token)
    updates = bot.get_updates(offset=get_update_offset(db_path=db_path), timeout=1, allowed_updates=["message", "channel_post"])
    return extract_chat_candidates(updates)


def extract_chat_candidates(updates: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[int] = set()
    chats: list[dict[str, object]] = []
    for update in updates:
        source, message = _message_from_update(update)
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict) or "id" not in chat:
            continue
        chat_id = int(chat["id"])
        if chat_id in seen:
            continue
        seen.add(chat_id)
        title = chat.get("title") or chat.get("username") or chat.get("first_name") or "private chat"
        chats.append(
            {
                "id": str(chat_id),
                "type": str(chat.get("type") or "unknown"),
                "title": str(title),
                "source": source,
            }
        )
    return chats


def get_update_offset(db_path: str | None = None) -> int | None:
    value = db.get_setting(OFFSET_KEY, db_path=db_path)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def set_update_offset(offset: int, db_path: str | None = None) -> None:
    db.set_setting(OFFSET_KEY, str(offset), db_path=db_path)


def poll_once(runtime: "JiriRuntime", client: TelegramClient | None = None, now: datetime | None = None) -> dict[str, object]:
    settings = get_settings(config=runtime.config, db_path=runtime.db_path)
    if not settings.configured:
        raise TelegramError("Telegram requires bot token and allowed chat IDs")
    bot = client or TelegramClient(settings.bot_token)
    offset = get_update_offset(db_path=runtime.db_path)
    db.set_setting(LAST_POLL_KEY, _now_iso(), db_path=runtime.db_path)
    updates = bot.get_updates(
        offset=offset,
        timeout=settings.polling_timeout_seconds,
        allowed_updates=["message", "channel_post"],
    )
    processed = 0
    replies = 0
    persona_replies = 0
    try:
        for update in updates:
            update_id = int(update.get("update_id", -1))
            if update_id < 0:
                continue
            reply = handle_update(runtime, update)
            set_update_offset(update_id + 1, db_path=runtime.db_path)
            db.set_setting(LAST_UPDATE_KEY, _now_iso(), db_path=runtime.db_path)
            processed += 1
            if reply is not None:
                bot.send_message(reply.chat_id, reply.text)
                replies += 1
        if not updates:
            moment = persona.due_telegram_moment(now=now, db_path=runtime.db_path)
            if moment is not None:
                target = settings.command_chat_id or (settings.allowed_chat_ids[0] if settings.allowed_chat_ids else None)
                if target is not None:
                    bot.send_message(target, f"{moment.headline}\n{moment.subheadline}")
                    persona.mark_telegram_sent(moment.cooldown_key or moment.category, now=now, db_path=runtime.db_path)
                    persona_replies += 1
        db.set_setting(LAST_ERROR_KEY, "", db_path=runtime.db_path)
    except Exception as exc:
        db.set_setting(LAST_ERROR_KEY, str(exc), db_path=runtime.db_path)
        raise
    return {
        "updates": len(updates),
        "processed": processed,
        "replies": replies,
        "persona_replies": persona_replies,
        "offset": get_update_offset(db_path=runtime.db_path),
    }


def run_polling(runtime: "JiriRuntime" | None = None, client: TelegramClient | None = None, sleep_seconds: float = 1.0) -> None:
    from .runtime import JiriRuntime

    rt = runtime or JiriRuntime.load()
    while True:
        try:
            poll_once(rt, client=client)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            db.set_setting(LAST_ERROR_KEY, str(exc), db_path=rt.db_path)
            time.sleep(max(1.0, sleep_seconds))


@dataclass(frozen=True)
class TelegramReply:
    chat_id: int
    text: str


def handle_update(runtime: "JiriRuntime", update: dict[str, object]) -> TelegramReply | None:
    settings = get_settings(config=runtime.config, db_path=runtime.db_path)
    _, message = _message_from_update(update)
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat:
        return None
    chat_id = int(chat["id"])
    if chat_id not in set(settings.allowed_chat_ids):
        db.set_setting(LAST_UNAUTHORIZED_CHAT_KEY, str(chat_id), db_path=runtime.db_path)
        return None
    text = str(message.get("text") or "").strip()
    if not text:
        return TelegramReply(chat_id, "Send /help for JIRI commands.")
    try:
        return TelegramReply(chat_id, dispatch_command(runtime, text))
    except (ValueError, RuntimeError) as exc:
        return TelegramReply(chat_id, f"Error: {exc}")


def dispatch_command(runtime: "JiriRuntime", text: str) -> str:
    command, arg = _split_command(text)
    if command in {"/start", "/help"}:
        return _help_text()
    if command == "/status":
        return _status_text(runtime)
    if command in {"/todos", "/todo"}:
        return _todo_command(runtime, command, arg)
    if command in {"/notes", "/note"}:
        return _note_command(runtime, command, arg)
    if command == "/weather":
        return _weather_text(runtime)
    if command == "/focus":
        return _focus_command(runtime, arg)
    if command == "/water":
        return _water_command(runtime, arg)
    return "Unknown command. Send /help for supported commands."


def _todo_command(runtime: "JiriRuntime", command: str, arg: str) -> str:
    if command == "/todos" or not arg or arg == "list":
        rows = runtime.list_todos(include_done=False)[:8]
        if not rows:
            return "No pending todos."
        return "Pending todos:\n" + "\n".join(f"#{todo.id} p{todo.priority} {todo.title}" for todo in rows)
    sub, rest = _split_word(arg)
    if sub == "add":
        todo = runtime.add_todo(rest)
        return f"Added todo #{todo.id}: {todo.title}"
    if sub == "done":
        todo = runtime.mark_todo_done(_parse_positive_int(rest, "todo id"))
        return f"Done todo #{todo.id}: {todo.title}"
    return "Usage: /todos, /todo add <title>, /todo done <id>"


def _note_command(runtime: "JiriRuntime", command: str, arg: str) -> str:
    if command == "/notes" or not arg or arg == "list":
        rows = runtime.list_notes()[:5]
        if not rows:
            return "No notes."
        return "Recent notes:\n" + "\n".join(f"#{note.id} {note.title}" for note in rows)
    sub, rest = _split_word(arg)
    if sub == "add":
        title, body = _split_note(rest)
        note = runtime.add_note(title, body)
        return f"Added note #{note.id}: {note.title}"
    return "Usage: /notes, /note add <title> | <body>"


def _focus_command(runtime: "JiriRuntime", arg: str) -> str:
    sub, rest = _split_word(arg or "status")
    if sub == "status":
        snap = runtime.focus_snapshot()
        if not snap.get("active"):
            return str(snap.get("message") or "No active focus session.")
        return f"Focus #{snap.get('id')}: {snap.get('title')}\n{snap.get('status')} · {snap.get('remaining_text')} left"
    if sub == "start":
        minutes_text, title = _split_word(rest)
        minutes = int(minutes_text) if minutes_text else runtime.config.focus.default_minutes
        session = runtime.start_focus(minutes=minutes, title=title or "Telegram focus")
        return f"Started focus #{session.id}: {session.title} ({session.duration_seconds // 60}m)"
    if sub == "pause":
        session = runtime.pause_focus()
        return f"Paused focus #{session.id}: {session.title}"
    if sub == "resume":
        session = runtime.resume_focus()
        return f"Resumed focus #{session.id}: {session.title}"
    if sub == "complete":
        session = runtime.complete_focus()
        return f"Completed focus #{session.id}: {session.title}"
    if sub in {"stop", "cancel"}:
        session = runtime.cancel_focus()
        return f"Cancelled focus #{session.id}: {session.title}"
    return "Usage: /focus status|start [minutes] [title]|pause|resume|complete|stop"


def _water_command(runtime: "JiriRuntime", arg: str) -> str:
    sub, rest = _split_word(arg or "status")
    if sub == "status":
        snap = runtime.water_snapshot()
        return f"Water: {snap['progress_ml']}ml / {snap['goal_ml']}ml ({snap['percent']}%). {snap['remaining_ml']}ml left."
    if sub == "add":
        snap = runtime.add_water(_parse_positive_int(rest, "water amount"))
        return f"Added water. {snap['progress_ml']}ml / {snap['goal_ml']}ml ({snap['percent']}%)."
    return "Usage: /water or /water add <ml>"


def _status_text(runtime: "JiriRuntime") -> str:
    snap = runtime.dashboard_snapshot(panel="system")
    focus_text = snap.focus.get("remaining_text") if snap.focus.get("active") else "none"
    return "\n".join(
        [
            f"JIRI status: {'healthy' if snap.health.get('database_writable') else 'issues'}",
            f"Todos pending: {snap.screen.pending_count}",
            f"Focus: {focus_text}",
            f"Weather: {snap.weather.get('condition') or 'unavailable'}",
            f"Water: {snap.water.get('progress_ml')}ml / {snap.water.get('goal_ml')}ml",
        ]
    )


def _weather_text(runtime: "JiriRuntime") -> str:
    weather = runtime.dashboard_snapshot(panel="weather").weather
    if not weather.get("available"):
        return str(weather.get("message") or "Weather unavailable.")
    temp = weather.get("temperature_c")
    feels = weather.get("feels_like_c")
    rain = weather.get("rain_chance")
    wind = weather.get("wind_kmh")
    return "\n".join(
        [
            f"Weather: {weather.get('location')}",
            f"{weather.get('condition')} · {temp}C, feels {feels}C",
            f"Rain {rain}% · wind {wind} km/h",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "JIRI Telegram commands:",
            "/status",
            "/todos",
            "/todo add <title>",
            "/todo done <id>",
            "/notes",
            "/note add <title> | <body>",
            "/weather",
            "/focus status|start|pause|resume|complete|stop",
            "/water",
            "/water add <ml>",
        ]
    )


def _split_command(text: str) -> tuple[str, str]:
    first, rest = _split_word(text.strip())
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def _split_word(text: str) -> tuple[str, str]:
    clean = text.strip()
    if not clean:
        return "", ""
    parts = clean.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0].lower(), ""
    return parts[0].lower(), parts[1].strip()


def _split_note(value: str) -> tuple[str, str]:
    if "|" in value:
        title, body = value.split("|", 1)
        return title.strip(), body.strip()
    clean = value.strip()
    return clean[:40].strip(), clean


def _parse_positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Invalid {label}") from exc
    if parsed <= 0:
        raise ValueError(f"Invalid {label}")
    return parsed


def _message_from_update(update: dict[str, object]) -> tuple[str, dict[str, object] | None]:
    for key in ("message", "channel_post", "edited_message", "edited_channel_post"):
        value = update.get(key)
        if isinstance(value, dict):
            return key, value
    return "", None


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _token_preview(token: str) -> str:
    if not token:
        return "not set"
    if len(token) <= 10:
        return "set"
    return f"{token[:6]}...{token[-4:]}"


def main(argv: list[str] | None = None) -> int:
    from .runtime import JiriRuntime

    parser = argparse.ArgumentParser(prog="python -m jiri.telegram", description="JIRI Telegram polling worker")
    parser.add_argument("command", choices=("poll", "once", "check", "discover"))
    args = parser.parse_args(argv)
    try:
        runtime = JiriRuntime.load()
        if args.command == "poll":
            run_polling(runtime)
            return 0
        if args.command == "once":
            print(poll_once(runtime))
            return 0
        if args.command == "check":
            me = check_bot(config=runtime.config)
            print(f"Telegram bot: @{me.get('username') or 'unknown'} id={me.get('id')}")
            return 0
        if args.command == "discover":
            chats = discover_chats(config=runtime.config, db_path=runtime.db_path)
            if not chats:
                print("No recent Telegram chats found. Send /start to the bot, then retry.")
                return 0
            for chat in chats:
                print(f"{chat['id']} [{chat['type']}] {chat['title']} via {chat['source']}")
            return 0
    except (ValueError, RuntimeError, TelegramError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
