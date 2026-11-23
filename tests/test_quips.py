from __future__ import annotations

import pytest

from jiri import ai, quips

CATEGORIES = (
    "thought_late", "thought_soon", "thought_tasks_clear", "thought_tasks_some",
    "thought_water_low", "thought_water_good", "thought_water_done",
    "thought_weather_hot", "thought_weather_rain", "thought_weather_nice",
    "thought_weather_cold", "thought_focus", "thought_usage_high",
    "thought_usage_ok", "thought_night", "thought_morning",
)


def test_fallback_covers_exactly_the_thought_categories():
    assert set(quips.FALLBACK) == set(CATEGORIES)


@pytest.mark.parametrize("category", CATEGORIES)
def test_fallback_lines_follow_the_voice_rules(category):
    lines = quips.FALLBACK[category]
    assert len(lines) >= 6
    assert len(set(lines)) == len(lines)
    for line in lines:
        assert 0 < len(line) <= quips.MAX_CHARS, line
        assert not any(ch.isdigit() for ch in line), line
        assert "{" not in line and "}" not in line, line
        assert line.isascii(), line
        # Same normalisation the AI sanitizer applies: a fallback must be a
        # line the generated cache could also have produced.
        assert ai.sanitize(line, max_chars=quips.MAX_CHARS) == line, line


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_has_an_ai_brief_and_no_slots(category):
    assert category in ai.known_categories()
    assert ai.slots_for(category) == ()
    assert "Category '" not in ai.brief_for(category, "thought")
    assert ai.max_chars_for(category, 160) == 60


def test_thought_prompt_uses_thought_angles_and_short_aim():
    system, user = ai.build_messages(
        "thought_late", "thought", personality="playful_joyful", max_chars=60, count=4,
    )
    assert "never over 60" in system["content"]
    assert "40 to 70" not in system["content"]
    assert "sincere and warm" in user["content"]
    assert "no numbers" in user["content"]


def test_pick_is_deterministic_and_seed_sensitive():
    a = quips.quip("thought_focus", "2026-11-23T10:00")
    assert a == quips.quip("thought_focus", "2026-11-23T10:00")
    assert a in quips.FALLBACK["thought_focus"]
    picks = {quips.quip("thought_focus", seed) for seed in range(50)}
    assert len(picks) > 1


def test_lookup_overrides_fallback():
    seen = []

    def lookup(category, seed):
        seen.append((category, seed))
        return "Cached line."

    assert quips.quip("thought_night", 7, lookup) == "Cached line."
    assert seen == [("thought_night", 7)]


@pytest.mark.parametrize("result", [None, ""])
def test_lookup_miss_falls_back(result):
    assert quips.quip("thought_night", 7, lambda c, s: result) == quips.quip("thought_night", 7)


def test_lookup_exception_falls_back():
    def boom(category, seed):
        raise RuntimeError("db locked")

    assert quips.quip("thought_morning", "x", boom) in quips.FALLBACK["thought_morning"]


def test_unknown_category_gets_a_generic_line():
    line = quips.quip("thought_unheard_of", 1)
    assert line in quips.GENERIC
    assert len(line) <= quips.MAX_CHARS


def test_ai_pick_as_lookup_reads_cache(tmp_path):
    db_path = str(tmp_path / "jiri.db")
    ai.ensure_schema(db_path)
    ai.store_lines("thought_soon", "thought", 0, ["Almost there, champ."], provider="t", model="m", db_path=db_path)

    def lookup(category, seed):
        return ai.pick(category, "thought", seed, db_path=db_path)

    assert quips.quip("thought_soon", 3, lookup) == "Almost there, champ."
    # Empty bucket: miss -> fallback.
    assert quips.quip("thought_late", 3, lookup) in quips.FALLBACK["thought_late"]


def test_eval_voice_parses_judge_rows():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "eval_voice.py"
    spec = importlib.util.spec_from_file_location("eval_voice", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    raw = "1 5 4 5 5 5\n2. 2 3 1 5 4\nnoise\n9 5 5 5 5 5\n3 5 5"
    assert mod.parse_scores(raw, 3) == {1: (5, 4, 5, 5, 5), 2: (2, 3, 1, 5, 4)}
