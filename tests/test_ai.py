"""Gate 1 tests for the AI wording layer.

Each test cites the invariant it enforces from docs/AI_SPEC.md §3.
No test in this file may make a real network call.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from jiri import ai, db, messages, persona
from jiri.config import AiConfig, AiProviderConfig
from jiri.models import Todo


def _db(tmp_path):
    path = str(tmp_path / "jiri.db")
    db.init_db(path)
    ai.ensure_schema(path)
    return path


def _todo(title="Buy milk", angry_level=0):
    return Todo(
        id=1, title=title, description=None, due_at=None, status="pending",
        priority=2, created_at="2026-08-04T10:00:00", updated_at="2026-08-04T10:00:00",
        completed_at=None, angry_level=angry_level,
    )


# --- I8: sanitizer rejects or folds hostile output -------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Here is a line for you", None),          # preamble
        ("Sure! Bold strategy.", None),            # preamble
        ("**Bold** strategy.", "Bold strategy."),  # markdown stripped
        ('"Fully wrapped."', "Fully wrapped."),    # wrapping quotes
        ("He said \"no\" here.", 'He said "no" here.'),  # inner quotes kept
        ("Bold — strategy…", "Bold - strategy..."),      # ascii fold
        ("Café risk ☃", None),          # non-ascii after fold
        ("​Here is a line", None),            # zero-width hiding preamble
        ("a", None),                               # too short
        ("x" * 400, None),                         # too long
        ("", None),
        ("   ", None),
    ],
)
def test_sanitize_rejects_or_folds(raw, expected):
    assert ai.sanitize(raw, max_chars=160) == expected


def test_sanitize_rejects_unknown_slots():
    assert ai.sanitize("{task} is late", max_chars=160, allowed_slots=("task",)) == "{task} is late"
    assert ai.sanitize("{wat} is late", max_chars=160, allowed_slots=("task",)) is None


def test_sanitize_strips_bidi_and_tag_block():
    # Unicode tag block is the classic invisible-payload smuggling vector.
    assert ai.sanitize("Fine line.\U000E0041\U000E0042", max_chars=160) == "Fine line."
    assert ai.sanitize("‮Fine line.", max_chars=160) == "Fine line."


# --- I6: no rendered line can exceed the display cap -----------------------

def test_worst_case_length_accounts_for_slots():
    # 2 slots x 32-char budget + literal text.
    assert ai.worst_case_length("{task} is {minutes} late.") == len(" is  late.") + 64


def test_render_returns_none_on_missing_slot():
    assert ai.render("{task} is late", {"task": "X"}) == "X is late"
    assert ai.render("{nope} is late", {"task": "X"}) is None


# --- I5: taxonomy is demand-driven, never duplicated -----------------------

def test_module_declares_no_category_list():
    """The drift that broke this once was a hardcoded list. Keep it gone."""
    assert not hasattr(ai, "CATEGORIES")


def test_cache_miss_records_demand(tmp_path):
    path = _db(tmp_path)
    assert ai.line("todo_rage", "rage", db_path=path) is None
    assert ai.line("water", "alert", db_path=path) is None
    assert ai.line("todo_rage", "rage", db_path=path) is None
    wanted = ai.wanted_buckets(db_path=path)
    # Most-missed first.
    assert wanted[0] == ("todo_rage", "rage")
    assert ("water", "alert") in wanted


def test_every_persona_category_has_slots_defined(tmp_path):
    """I5: a category persona can emit must resolve to a usable bucket."""
    for category in ai.known_categories():
        assert isinstance(ai.slots_for(category), tuple)
        assert ai.brief_for(category, "alert")


def test_unknown_category_degrades_instead_of_failing():
    assert ai.slots_for("brand_new_category") == ()
    assert "brand_new_category" in ai.brief_for("brand_new_category", "alert")


# --- Cache behaviour --------------------------------------------------------

def test_cache_rotates_least_recently_used(tmp_path):
    path = _db(tmp_path)
    ai.store_lines("ambient", "idle", 0, ["Line A.", "Line B."],
                   provider="test", model="m", db_path=path)
    first = ai.line("ambient", "idle", db_path=path)
    second = ai.line("ambient", "idle", db_path=path)
    assert {first, second} == {"Line A.", "Line B."}
    assert first != second


def test_store_lines_deduplicates(tmp_path):
    path = _db(tmp_path)
    ai.store_lines("ambient", "idle", 0, ["Same."], provider="t", model="m", db_path=path)
    added = ai.store_lines("ambient", "idle", 0, ["Same."], provider="t", model="m", db_path=path)
    assert added == 0


def test_prune_bounds_bucket_size(tmp_path):
    path = _db(tmp_path)
    ai.store_lines("ambient", "idle", 0, [f"Line {i}." for i in range(20)],
                   provider="t", model="m", db_path=path)
    ai.prune(5, db_path=path)
    assert ai.bucket_counts(db_path=path)[("ambient", "idle", 0)] == 5


# --- I7: caps and breaker hold across restarts ------------------------------

def test_daily_cap_blocks_refill(tmp_path):
    path = _db(tmp_path)
    cfg = AiConfig(daily_request_cap=1,
                   providers=(AiProviderConfig(name="groq", model="m"),))
    for _ in range(1):
        ai.bump_usage(db_path=path)
    result = ai.refill(config=cfg, db_path=path)
    assert result["skipped"] == "daily-cap"
    assert result["calls"] == 0


def test_breaker_opens_after_consecutive_failures(tmp_path):
    path = _db(tmp_path)
    for _ in range(ai.BREAKER_FAILURE_THRESHOLD):
        ai.record_failure("groq", db_path=path)
    assert ai.breaker_state("groq", db_path=path)["open"] is True
    ai.record_success("groq", db_path=path)
    assert ai.breaker_state("groq", db_path=path)["open"] is False


def test_refill_skips_when_all_providers_are_disabled(tmp_path):
    path = _db(tmp_path)
    config = AiConfig(providers=(AiProviderConfig(name="groq", enabled=False),))
    assert ai.refill(config=config, db_path=path)["skipped"] == "no-providers"


# --- I1 / I4: render path never needs the network ---------------------------

def test_messages_fall_back_with_no_cache(tmp_path):
    """I4: with an empty cache, wording is byte-identical to the built-ins."""
    path = _db(tmp_path)
    assert messages.reminder_message(_todo(), 0, db_path=path) == "Reminder: Buy milk"
    assert messages.message_for_mood("rage", db_path=path) == messages.MOOD_MESSAGES["rage"]


def test_messages_use_cached_template_when_present(tmp_path):
    path = _db(tmp_path)
    ai.store_lines("reminder", "angry", 0, ["{task} is {minutes} min late. Noted."],
                   provider="t", model="m", db_path=path)
    out = messages.reminder_message(_todo(), 4, db_path=path)
    assert out == "Buy milk is 60 min late. Noted."


def test_render_path_survives_dead_network(tmp_path, monkeypatch):
    """I1: no network call is reachable from the render path."""
    path = _db(tmp_path)

    def explode(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("render path attempted a network call")

    monkeypatch.setattr(ai.requests, "post", explode)
    monkeypatch.setattr(ai.requests, "get", explode)

    assert messages.reminder_message(_todo(), 3, db_path=path)
    assert messages.message_for_mood("idle", db_path=path)
    assert persona.screen_moment(db_path=path) is not None


def test_line_never_raises_on_broken_db(tmp_path):
    """A corrupt cache and a cache miss must look identical to the caller."""
    broken = str(tmp_path / "not-a-database.db")
    (tmp_path / "not-a-database.db").write_text("garbage", encoding="utf-8")
    assert ai.line("ambient", "idle", db_path=broken) is None


# --- Prompt construction ----------------------------------------------------

def test_prompt_pins_slots_and_avoids_recent_lines():
    msgs = ai.build_messages(
        "todo_late", "annoyed",
        personality="funny_sarcastic", max_chars=160, count=3,
        avoid=("Bold strategy.",),
    )
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert "{task}, {minutes}" in system
    assert "no emoji" in system.lower()
    assert "Bold strategy." in user
    assert "Do not reuse" in user


def test_prompt_omits_avoid_block_when_cache_empty():
    msgs = ai.build_messages("ambient", "idle", personality="dry", max_chars=160, count=2)
    assert "Do not reuse" not in msgs[1]["content"]


# --- Provider resolution ----------------------------------------------------

def test_provider_requires_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("JIRI_GROQ_API_KEY", raising=False)
    with pytest.raises(ai.AiError, match="GROQ_API_KEY"):
        ai.resolve_provider(AiProviderConfig(name="groq", model="m"))


def test_provider_accepts_either_env_spelling(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("JIRI_GROQ_API_KEY", "secret")
    _, _, key = ai.resolve_provider(AiProviderConfig(name="groq", model="m"))
    assert key == "secret"


def test_provider_falls_back_to_preset_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    base, model, _ = ai.resolve_provider(AiProviderConfig(name="gemini"))
    assert model == ai.PROVIDER_PRESETS["gemini"]["default_model"]
    assert base.endswith("/openai")


def test_ollama_needs_no_key():
    _, _, key = ai.resolve_provider(AiProviderConfig(name="ollama", model="llama3.1:8b"))
    assert key == ""


# --- Persona tone policy (docs/AI_SPEC.md §8) -------------------------------

def test_failure_categories_get_no_humour_angles():
    """Categories commenting on a user shortfall must not be given joke angles."""
    for category in sorted(ai.HUMOUR_FREE_CATEGORIES):
        user = ai.build_messages(
            category, "angry", personality="funny_sarcastic",
            max_chars=160, count=4,
        )[1]["content"]
        assert "angles" not in user
        assert "No jokes" in user


def test_neutral_categories_keep_personality():
    user = ai.build_messages(
        "ambient", "idle", personality="funny_sarcastic", max_chars=160, count=4,
    )[1]["content"]
    assert "angles" in user
    assert "never the user" in user


def test_reminder_text_flattens_as_it_escalates(tmp_path):
    """Escalation reduces length; the face carries the intensity instead."""
    path = _db(tmp_path)
    lengths = [
        len(messages.reminder_message(_todo(), level, db_path=path))
        for level in (2, 3, 4, 5)
    ]
    # Non-increasing: severity must never make the message longer.
    assert all(a >= b for a, b in zip(lengths, lengths[1:])), lengths
    # And the top of the ladder is drastically terser than the bottom.
    assert lengths[-1] * 2 < lengths[0], lengths


def test_no_reminder_text_targets_the_user(tmp_path):
    path = _db(tmp_path)
    banned = ("you", "your", "procrastinat", "rage mode", "judgment")
    for level in range(0, 6):
        text = messages.reminder_message(_todo(), level, db_path=path).lower()
        assert not any(word in text for word in banned), (level, text)


# --- Persona corpus (charming with AI off) ---------------------------------

def test_builtin_line_pools_are_large_enough():
    """Research: repeats become invisible only with real corpus depth.

    These pools are what JIRI speaks with providers unavailable or offline, so they carry
    the personality on their own.
    """
    assert len(messages.IDLE_MESSAGES) >= 10
    assert len(messages.CELEBRATE_MESSAGES) >= 6
    assert len(messages.FOCUS_MESSAGES) >= 3


def test_builtin_lines_fit_the_display_and_stay_plain():
    pools = (
        messages.IDLE_MESSAGES
        + messages.CELEBRATE_MESSAGES
        + messages.FOCUS_MESSAGES
        + messages.FOCUS_MILESTONE_MESSAGES
        + list(messages.MOOD_MESSAGES.values())
    )
    for text in pools:
        assert 4 <= len(text) <= 160, text
        assert text.isascii(), text
        assert "\n" not in text


def test_seeded_pick_is_stable_and_varied():
    """Same moment keeps its line; different moments differ."""
    a = messages.idle_message(seed="event-1")
    assert a == messages.idle_message(seed="event-1")
    seen = {messages.idle_message(seed=f"e{i}") for i in range(40)}
    assert len(seen) > 1


def test_water_keeps_warmth_but_todo_escalation_does_not():
    """Hydration is a light nudge; overdue tasks are a shortfall report."""
    assert "water" not in ai.HUMOUR_FREE_CATEGORIES
    assert "todo_rage" in ai.HUMOUR_FREE_CATEGORIES
