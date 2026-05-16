from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from jiri import db, telegram
from jiri.config import AppConfig, TelegramConfig, WeatherConfig
from jiri.runtime import JiriRuntime


class FakeTelegramClient:
    def __init__(self, updates=None, me=None):
        self.updates = updates or []
        self.me = me or {"id": 99, "username": "jiri_test_bot"}
        self.sent = []

    def get_me(self):
        return self.me

    def get_updates(self, offset=None, timeout=25, limit=100, allowed_updates=None):
        self.last_offset = offset
        self.last_timeout = timeout
        self.last_allowed_updates = allowed_updates
        return self.updates

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}


def test_poll_once_processes_allowed_commands_and_persists_offset(tmp_path):
    runtime = _runtime(tmp_path, allowed_chat_ids=(123456789,))
    telegram.save_settings(
        enabled=True,
        bot_token="123456:test-token",
        allowed_chat_ids="123456789",
        command_chat_id="123456789",
        polling_timeout_seconds=1,
        db_path=runtime.db_path,
        config=runtime.config,
    )
    client = FakeTelegramClient(
        [
            _message_update(10, 123456789, "/todo add Buy milk"),
            _message_update(11, 123456789, "/todos"),
        ]
    )

    result = telegram.poll_once(runtime, client=client, now=datetime(2026, 5, 15, 14, 0))

    assert result["processed"] == 2
    assert result["replies"] == 2
    assert db.get_setting(telegram.OFFSET_KEY, db_path=runtime.db_path) == "12"
    assert runtime.list_todos()[0].title == "Buy milk"
    assert client.sent[0] == (123456789, "Added todo #1: Buy milk")
    assert "#1 p2 Buy milk" in client.sent[1][1]


def test_poll_once_sends_due_persona_nudge_when_idle(tmp_path):
    runtime = _runtime(tmp_path, allowed_chat_ids=(123456789,))
    telegram.save_settings(
        enabled=True,
        bot_token="123456:test-token",
        allowed_chat_ids="123456789",
        command_chat_id="123456789",
        polling_timeout_seconds=1,
        db_path=runtime.db_path,
        config=runtime.config,
    )
    client = FakeTelegramClient([])

    result = telegram.poll_once(runtime, client=client, now=datetime(2026, 5, 15, 14, 0))

    assert result["persona_replies"] == 1
    assert client.sent[0][0] == 123456789
    assert "Water check" in client.sent[0][1]


def test_poll_once_ignores_unauthorized_chats(tmp_path):
    runtime = _runtime(tmp_path, allowed_chat_ids=(123456789,))
    telegram.save_settings(
        enabled=True,
        bot_token="123456:test-token",
        allowed_chat_ids="123456789",
        polling_timeout_seconds=1,
        db_path=runtime.db_path,
        config=runtime.config,
    )
    client = FakeTelegramClient([_message_update(7, 111, "/todo add blocked")])

    result = telegram.poll_once(runtime, client=client)

    assert result["processed"] == 1
    assert result["replies"] == 0
    assert runtime.list_todos() == []
    assert client.sent == []
    assert db.get_setting(telegram.LAST_UNAUTHORIZED_CHAT_KEY, db_path=runtime.db_path) == "111"
    assert db.get_setting(telegram.OFFSET_KEY, db_path=runtime.db_path) == "8"


def test_dispatch_commands_cover_notes_focus_water_and_help(tmp_path):
    runtime = _runtime(tmp_path, allowed_chat_ids=(123456789,))
    telegram.save_settings(
        enabled=True,
        bot_token="123456:test-token",
        allowed_chat_ids="123456789",
        polling_timeout_seconds=1,
        db_path=runtime.db_path,
        config=runtime.config,
    )

    assert "/todo add" in telegram.dispatch_command(runtime, "/help")
    assert "Added note #1" in telegram.dispatch_command(runtime, "/note add Plan | Keep it small")
    assert "Recent notes" in telegram.dispatch_command(runtime, "/notes")
    assert "Started focus #1" in telegram.dispatch_command(runtime, "/focus start 1 Telegram test")
    assert "Focus #1" in telegram.dispatch_command(runtime, "/focus status")
    assert "Paused focus #1" in telegram.dispatch_command(runtime, "/focus pause")
    assert "Resumed focus #1" in telegram.dispatch_command(runtime, "/focus resume")
    assert "Cancelled focus #1" in telegram.dispatch_command(runtime, "/focus stop")
    assert "Added water" in telegram.dispatch_command(runtime, "/water add 250")
    assert "250ml" in telegram.dispatch_command(runtime, "/water")


def test_extract_chat_candidates_finds_private_group_and_channel():
    updates = [
        _message_update(1, 123, "/start", chat={"id": 123, "type": "private", "first_name": "Ada"}),
        _message_update(2, -100555, "/help", chat={"id": -100555, "type": "supergroup", "title": "JIRI Lab"}),
        {"update_id": 3, "channel_post": {"chat": {"id": -100777, "type": "channel", "title": "JIRI Channel"}, "text": "test"}},
    ]

    chats = telegram.extract_chat_candidates(updates)

    assert [chat["id"] for chat in chats] == ["123", "-100555", "-100777"]
    assert chats[0]["title"] == "Ada"
    assert chats[2]["source"] == "channel_post"


def test_binding_status_reports_config_and_runtime_state(tmp_path):
    runtime = _runtime(tmp_path, allowed_chat_ids=(123456789, -1001234567890))
    telegram.save_settings(
        enabled=True,
        bot_token="123456:test-token",
        allowed_chat_ids="123456789,-1001234567890",
        polling_timeout_seconds=5,
        db_path=runtime.db_path,
        config=runtime.config,
    )
    db.set_setting(telegram.OFFSET_KEY, "42", db_path=runtime.db_path)
    telegram.update_bot_identity(username="jiri_bot", bot_id=99, db_path=runtime.db_path, config=runtime.config)

    status = telegram.binding_status(config=runtime.config, db_path=runtime.db_path)

    assert status["configured"] is True
    assert status["token_configured"] is True
    assert status["allowed_chat_count"] == 2
    assert status["update_offset"] == 42
    assert status["token_preview"].startswith("123456")
    assert status["bot_username"] == "jiri_bot"


def test_telegram_settings_crud(tmp_path):
    runtime = _runtime(tmp_path, allowed_chat_ids=())
    settings = telegram.save_settings(
        enabled=False,
        bot_token="abc",
        allowed_chat_ids="123456789",
        command_chat_id="123456789",
        polling_timeout_seconds=10,
        db_path=runtime.db_path,
        config=runtime.config,
    )
    assert settings.allowed_chat_ids == (123456789,)
    assert telegram.get_allowed_chat_ids(db_path=runtime.db_path, config=runtime.config) == (123456789,)

    settings = telegram.add_allowed_chat(-100222, db_path=runtime.db_path, config=runtime.config)
    assert settings.allowed_chat_ids == (123456789, -100222)

    settings = telegram.remove_allowed_chat(123456789, db_path=runtime.db_path, config=runtime.config)
    assert settings.allowed_chat_ids == (-100222,)

    settings = telegram.toggle_enabled(True, db_path=runtime.db_path, config=runtime.config)
    assert settings.enabled is True

    settings = telegram.update_polling_timeout(12, db_path=runtime.db_path, config=runtime.config)
    assert settings.polling_timeout_seconds == 12

    settings = telegram.clear_token(db_path=runtime.db_path, config=runtime.config)
    assert settings.bot_token == ""
    assert settings.enabled is False


def _runtime(tmp_path, allowed_chat_ids):
    cfg = replace(
        AppConfig(),
        weather=replace(WeatherConfig(), fake=True),
        telegram=TelegramConfig(bot_token="", allowed_chat_ids=allowed_chat_ids, polling_timeout_seconds=1),
    )
    return JiriRuntime.load(config=cfg, db_path=str(tmp_path / "jiri.db"))


def _message_update(update_id, chat_id, text, chat=None):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": chat or {"id": chat_id, "type": "private", "first_name": "User"},
            "text": text,
        },
    }
