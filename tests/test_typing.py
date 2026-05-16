from __future__ import annotations

from datetime import datetime, timedelta

from jiri.ui.typing import MAX_MESSAGE_LENGTH, type_text, typing_duration_seconds


def test_type_text_starts_empty():
    started = datetime(2026, 5, 15, 10, 0, 0)
    result = type_text("Hello world", started_at=started, now=started)
    assert result.visible == ""
    assert result.complete is False
    assert result.total_length == 11
    assert result.visible_length == 0


def test_type_text_partial():
    started = datetime(2026, 5, 15, 10, 0, 0)
    now = started + timedelta(milliseconds=250)
    result = type_text("Hello world", started_at=started, now=now, speed_cps=10)
    assert result.visible == "He"
    assert result.complete is False
    assert result.visible_length == 2


def test_type_text_complete():
    started = datetime(2026, 5, 15, 10, 0, 0)
    now = started + timedelta(seconds=2)
    result = type_text("Hello", started_at=started, now=now, speed_cps=10)
    assert result.visible == "Hello"
    assert result.complete is True
    assert result.visible_length == 5


def test_type_text_empty_string():
    started = datetime(2026, 5, 15, 10, 0, 0)
    result = type_text("", started_at=started, now=started)
    assert result.visible == ""
    assert result.complete is True
    assert result.total_length == 0


def test_type_text_truncates_at_max_length():
    started = datetime(2026, 5, 15, 10, 0, 0)
    long_text = "A" * 300
    result = type_text(long_text, started_at=started, now=started + timedelta(seconds=100), speed_cps=10)
    assert result.total_length == MAX_MESSAGE_LENGTH
    assert result.visible == "A" * MAX_MESSAGE_LENGTH
    assert result.complete is True


def test_type_text_speed_variation():
    started = datetime(2026, 5, 15, 10, 0, 0)
    now = started + timedelta(seconds=1)

    fast = type_text("Hello world test", started_at=started, now=now, speed_cps=30)
    slow = type_text("Hello world test", started_at=started, now=now, speed_cps=10)

    assert fast.visible_length > slow.visible_length


def test_typing_duration_seconds():
    assert typing_duration_seconds("Hello", speed_cps=10) == 0.5
    assert typing_duration_seconds("", speed_cps=10) == 0.0


def test_typing_duration_respects_max_length():
    long_text = "A" * 300
    duration = typing_duration_seconds(long_text, speed_cps=10)
    assert duration == MAX_MESSAGE_LENGTH / 10.0


def test_type_text_negative_elapsed():
    started = datetime(2026, 5, 15, 10, 0, 5)
    now = datetime(2026, 5, 15, 10, 0, 0)
    result = type_text("Hello", started_at=started, now=now, speed_cps=10)
    assert result.visible == ""
    assert result.complete is False
