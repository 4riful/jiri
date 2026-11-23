"""Hosted-LLM wording layer.

Design contract, in priority order:

1. **The render path never touches the network.** `line()` is a single indexed
   SQLite read. The UI frame loop, `views.py`, and `persona.py` may call it
   freely. There is no timeout to tune because there is no request.
2. **All network work happens in `refill()`**, which is called only from
   background worker loops. It tops up a cache of pre-written lines.
3. **AI returns a string or nothing.** It cannot write state, run commands,
   touch todos, or influence timing. `persona.py` still decides what to say and
   when; this module only decides how it is worded.
4. **Every failure is silent and falls through** to the cache, then to the
   deterministic constants in `messages.py`.

Providers are any OpenAI-compatible `/v1/chat/completions` endpoint, which
covers Groq, Google Gemini's compat layer, xAI, OpenRouter, and a LAN Ollama
box. Provider choice is configuration, not code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
import random
import re
import threading
import time
import unicodedata
import zlib

import requests

from . import db
from .config import AiConfig, AiProviderConfig, AppConfig


# --- Tunables ---------------------------------------------------------------
# Circuit breaker: after N consecutive failures a provider is skipped entirely
# until the cooldown expires. This keeps a dead provider from burning the whole
# refill window on timeouts.
BREAKER_FAILURE_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 900

# Retry within a single provider attempt. Deliberately shallow: the failover
# chain is the primary resilience mechanism, retries are for one-off blips.
MAX_ATTEMPTS_PER_PROVIDER = 2
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CAP_SECONDS = 4.0

# Refill shaping.
DEFAULT_LINES_PER_CALL = 5
MAX_BUCKETS_PER_REFILL = 2

BREAKER_KEY_PREFIX = "ai.breaker."
USAGE_KEY_PREFIX = "ai.usage."
# Call log (`ai_calls`) keeps only the newest N attempts: enough for the admin
# page to show today's activity, small enough to never matter on the SD card.
CALL_LOG_KEEP = 500
CALL_ERROR_MAX_CHARS = 160

# `_chat` keeps its (text, limits, model) return shape; the token `usage`
# block of the last successful response is stashed here, per thread, for the
# call log. Only the background worker thread reads it.
_last_call = threading.local()

# Bumped whenever the prompt or the sanitizer changes meaningfully. There is no
# per-row version column: a bump is paired with a one-off purge of the affected
# buckets (see docs/AI_SPEC.md §7). v2 = playful voice everywhere, overdue lines
# escalate theatrically instead of going flat.
PROMPT_VERSION = 2

# The 480x320 face shows speech as two lines of ~50 mono characters. Anything
# longer is rejected at refill time, whatever `max_output_chars` allows.
SPEECH_MAX_CHARS = 90

# NOTE (spec invariant I5): this module deliberately holds NO list of persona
# categories. A duplicated list drifted out of sync with persona.py once
# already, and the failure was silent — buckets filled under names nothing
# looked up. Bucket keys are always derived from the PersonaMoment being
# worded. See docs/AI_SPEC.md §4.


# --- Provider presets -------------------------------------------------------
# base_url is the OpenAI-compatible chat-completions root (without /chat/...).
# `api_key_env` is the conventional name from each provider's own docs; JIRI
# also accepts a `JIRI_`-prefixed variant so all app secrets can share a prefix.
PROVIDER_PRESETS: dict[str, dict[str, object]] = {
    # PRIMARY. The owner's self-hosted OpenAI-compatible gateway (FreeLLMAPI),
    # shared with their other apps. Its URL is per-install, so it comes from the
    # environment (`base_url_env`) rather than being baked in; `/v1` is appended
    # when missing because `{base}/chat/completions` serves an HTML page with a
    # 200, which would otherwise look like a malformed success.
    #
    # Default model qwen3.8-27b: measured ~0.4s for a batch of clean plain-text
    # lines. Deliberately NOT `auto`: it routes to reasoning models that spend
    # max_tokens on hidden reasoning, return empty content, and take 25-60s.
    "freellm": {
        "base_url": "",
        "base_url_env": "FREELLM_BASE_URL",
        "base_url_suffix": "/v1",
        "api_key_env": "FREELLM_API_KEY",
        "default_model": "qwen3.8-27b",
        "model_env": "FREELLM_MODEL",
        "temperature": 0.9,
    },
    # PRIMARY. Best free-tier creative-writing quality by a wide margin
    # (EQ-Bench longform 71.8, slop 29.0) and the strongest instruction
    # following of the free candidates. Google's terms allow training on
    # free-tier prompts — acceptable here only because JIRI transmits no user
    # data at all (see module docstring and docs/AI_SPEC.md §1).
    #
    # Gemini 3.x is a thinking model: `thinking_level` low keeps it from
    # spending the response budget on internal monologue for a one-liner.
    # Google explicitly warns against lowering temperature below the 1.0
    # default on Gemini 3 — it can induce looping.
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.5-flash",
        "temperature": 1.0,
        "params": {"thinking_level": "minimal"},
    },
    # FALLBACK. Groq publishes exact free limits and contractually does not
    # train on inputs or outputs. Qwen is the strongest creative writer in
    # Groq's free catalogue; `reasoning_effort: none` disables thinking mode,
    # and presence_penalty is Qwen's own recommended anti-repetition setting.
    #
    # Deliberately NOT llama-3.1-8b-instant: it has the most generous free
    # quota and the worst repetition scores of any candidate (repetition 12.6,
    # slop 53.3). On an always-on device that reads as broken.
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "qwen/qwen3.6-27b",
        "temperature": 0.7,
        "params": {
            "reasoning_effort": "none",
            "top_p": 0.80,
            "presence_penalty": 1.5,
        },
    },
    # No standing free tier as of 2026 — credits only. Configure only if you
    # are willing to pay.
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "default_model": "grok-4.20-0309-non-reasoning",
    },
    # A LAN box. No key, no cost, but the machine must be reachable.
    "ollama": {
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_env": "",
        "default_model": "llama3.1:8b",
    },
}


class AiError(RuntimeError):
    """Raised inside refill paths only. Never escapes to a render path."""


# --- Schema -----------------------------------------------------------------

def ensure_schema(db_path: str | None = None) -> None:
    with db.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_cache (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                mood TEXT NOT NULL,
                angry_level INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(category, mood, angry_level, text)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_cache_bucket
                ON ai_cache(category, mood, angry_level, last_used_at);

            -- Demand log. `line()` records a miss here; `refill()` warms what
            -- was actually asked for. This is why no category list is
            -- duplicated anywhere (spec invariant I5): the render path is the
            -- authority on which buckets exist, because it is the only thing
            -- that asks for them.
            CREATE TABLE IF NOT EXISTS ai_wanted (
                category TEXT NOT NULL,
                mood TEXT NOT NULL,
                miss_count INTEGER NOT NULL DEFAULT 0,
                last_wanted_at TEXT NOT NULL,
                PRIMARY KEY (category, mood)
            );

            -- Call log: one row per provider attempt made by generate(),
            -- which only runs on background workers. Bounded to the newest
            -- CALL_LOG_KEEP rows so it cannot grow on the SD card.
            CREATE TABLE IF NOT EXISTS ai_calls (
                id INTEGER PRIMARY KEY,
                at TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL,
                mood TEXT NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                returned INTEGER NOT NULL DEFAULT 0,
                accepted INTEGER NOT NULL DEFAULT 0,
                stored INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER
            );
            """
        )


# --- Render path (no network, no exceptions) --------------------------------

def line(
    category: str,
    mood: str,
    angry_level: int = 0,
    *,
    db_path: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Return a cached AI line for this bucket, or None.

    Safe to call from the UI frame loop. Single indexed SELECT plus one UPDATE.
    Never raises, never blocks on network.
    """
    current = now or datetime.now()
    try:
        with db.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT id, text FROM ai_cache
                WHERE category = ? AND mood = ? AND angry_level = ?
                ORDER BY last_used_at IS NOT NULL, last_used_at ASC, use_count ASC
                LIMIT 1
                """,
                (category, mood, int(angry_level)),
            ).fetchone()
            if row is None:
                # Record the demand so refill() knows this bucket exists and is
                # wanted. One tiny upsert, same order of cost as the hit path's
                # UPDATE, and it is what keeps the taxonomy self-maintaining.
                _record_demand(conn, category, mood, current)
                return None
            conn.execute(
                "UPDATE ai_cache SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                (current.isoformat(timespec="seconds"), int(row["id"])),
            )
            return str(row["text"])
    except Exception:
        # A cache miss and a broken cache are the same thing to the caller.
        return None


def cached_lines(category: str, mood: str, *, db_path: str | None = None) -> tuple[str, ...]:
    """Every cached line for a bucket, in the order `pick` indexes them.

    Pure read, never raises. Used by the display's reader thread to pre-load
    lines so the frame loop can choose one without touching SQLite.
    """
    try:
        with db.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT text FROM ai_cache WHERE category = ? AND mood = ? AND angry_level = 0 ORDER BY id",
                (category, mood),
            ).fetchall()
        return tuple(str(r["text"]) for r in rows)
    except Exception:
        return ()


def pick(
    category: str,
    mood: str,
    seed: object,
    *,
    db_path: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Return a cached template chosen *stably* by `seed`, or None.

    The display re-reads its snapshot every second. `line()` rotates on every
    call (least-recently-used), which on the face means a different sentence
    every second. `pick()` maps the same seed to the same line, so the caller
    controls how often JIRI changes its mind (persona seeds by a 15-minute
    window). A hit is a pure read; only a miss writes, to log demand.
    Never raises, never touches the network.
    """
    try:
        with db.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT text FROM ai_cache
                WHERE category = ? AND mood = ? AND angry_level = 0
                ORDER BY id
                """,
                (category, mood),
            ).fetchall()
            if not rows:
                _record_demand(conn, category, mood, now or datetime.now())
                return None
            index = zlib.crc32(str(seed).encode("utf-8")) % len(rows)
            return str(rows[index]["text"])
    except Exception:
        return None


# Demand is logged at most once per bucket per window *per process*: the
# display misses an empty bucket every second, and AGENTS.md forbids a
# SQLite write per frame (SD-card wear). The worker only needs to know the
# bucket is wanted, not how many times a second.
DEMAND_LOG_SECONDS = 600
_demand_logged: dict[tuple[str, str], datetime] = {}


def _record_demand(conn, category: str, mood: str, current: datetime) -> None:
    last = _demand_logged.get((category, mood))
    if last is not None and (current - last).total_seconds() < DEMAND_LOG_SECONDS:
        return
    _demand_logged[(category, mood)] = current
    conn.execute(
        """
        INSERT INTO ai_wanted (category, mood, miss_count, last_wanted_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(category, mood) DO UPDATE SET
            miss_count = miss_count + 1,
            last_wanted_at = excluded.last_wanted_at
        """,
        (category, mood, current.isoformat(timespec="seconds")),
    )


def render(template: str, slots: dict[str, object]) -> str | None:
    """Fill `{slot}` placeholders. Returns None if any slot is missing."""
    try:
        return template.format(**slots)
    except (KeyError, IndexError, ValueError):
        return None


# --- Output validation ------------------------------------------------------

_MARKDOWN_CHARS = re.compile(r"[*_`#>\[\]]")
_WHITESPACE = re.compile(r"\s+")
_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

# Codepoints that are invisible, reorder text, or smuggle payloads. None of
# these can render on a 3.5-inch display, and several are the standard
# hidden-prompt-injection vectors. Stripped before anything else looks at the
# text.
_INVISIBLE = dict.fromkeys(
    [
        0x00AD, 0x180E, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
        0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xFEFF,
        *range(0x202A, 0x202F),   # bidi embedding / override
        *range(0x2066, 0x206A),   # bidi isolates
        *range(0xFE00, 0xFE10),   # variation selectors
        *range(0xE0000, 0xE0080), # Unicode tag block ("ASCII smuggler")
    ]
)

# Typographic characters a model reaches for that a small bitmap font usually
# lacks. Folding beats rejecting — the line is fine, only the glyph is not.
_ASCII_FOLD = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", "‒": "-",
    "…": "...", " ": " ", " ": " ", " ": " ",
    "×": "x", "′": "'", "″": '"',
})

# Model chatter that means the model ignored the format instruction.
_REJECT_PREFIXES = (
    "here is", "here's", "sure", "certainly", "of course", "okay", "ok,",
    "as an ai", "i cannot", "i can't", "i'm sorry", "sorry,", "output:",
    "response:", "rewritten:", "line:",
)


def sanitize(raw: str, *, max_chars: int, allowed_slots: tuple[str, ...] = ()) -> str | None:
    """Normalize one model line, or reject it.

    Rejection is cheap and always safe — the caller falls back. Prefer
    rejecting a borderline line over rendering something malformed on a
    160-character display.
    """
    if not raw:
        return None
    # Order matters: strip invisibles before anything inspects the text, or a
    # zero-width character hides a banned prefix from the checks below.
    text = raw.translate(_INVISIBLE)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_ASCII_FOLD).strip()

    # Models love wrapping single-line answers in quotes. Only unwrap a real
    # matched pair — stripping a lone leading quote leaves a stray partner
    # mid-line, which looks worse than the quotes did.
    while len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()

    text = _MARKDOWN_CHARS.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        return None

    lowered = text.lower()
    if lowered.startswith(_REJECT_PREFIXES):
        return None

    # Unknown slots would raise or render literally at display time.
    for slot in _SLOT.findall(text):
        if slot not in allowed_slots:
            return None

    # After folding, anything still non-ASCII is a glyph the 3.5-inch display's
    # font probably lacks. A tofu box is worse than the deterministic string,
    # and rejecting is free.
    if not text.isascii():
        return None
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return None

    # Models drift into all-lowercase "aesthetic" lines; the face reads them
    # as typos. Fold the case and close the sentence rather than reject.
    if text[0].islower():
        text = text[0].upper() + text[1:]
    if text[-1].isalnum() or text[-1] == "}":
        text += "."

    if len(text) < 4 or len(text) > max_chars:
        return None
    return text


def worst_case_length(template: str, slot_budget: int = 32) -> int:
    """Longest the template can render to, assuming each slot fills its budget."""
    slots = _SLOT.findall(template)
    bare = _SLOT.sub("", template)
    return len(bare) + len(slots) * slot_budget


# --- Prompting --------------------------------------------------------------

# Voice charter. Kept separate from the per-bucket brief so the persona stays
# identical across every category — persona drift between buckets is the most
# common way a generated character stops feeling like one character.
_SYSTEM_PROMPT = """\
You write one-line speech bubbles for JIRI, a tiny playful robot face on the \
user's desk. Voice: {personality}; cheeky, affectionate, a bit theatrical.

Rules:
- Funny and specific. Tease the situation or JIRI itself (tiny, pixels, \
dramatic), never the user. No insults, guilt or lectures.
- Late things make JIRI more theatrical, never meaner.
- The screen already shows the facts; add feeling, don't restate them.
- No emoji, hashtags, preamble, numbering, quotes or markdown. No "delve", \
"testament", "tapestry", "realm".
- One line per line, aim for {aim} chars, never over {max_chars}. Plain ASCII, \
sentence case, end with punctuation.
- Placeholders allowed (optional, once each): {slots}
- Invent no facts, numbers, times or names."""

# Distinct comedic angles. Enumerating them forces spread across a batch
# instead of hoping temperature produces it — RLHF'd models otherwise
# mode-collapse and return the same joke N times.
_ANGLES = (
    "delighted overreaction to something tiny",
    "absurd non-sequitur",
    "mock-clinical observation",
    "faux-ceremonial announcement",
    "self-deprecating aside about being a small robot",
    "affectionate remark about an inanimate desk object",
    "understated deadpan",
    "misplaced optimism",
    "tiny conspiracy theory about the room",
    "sincere and warm, a smile more than a joke",
)

# Overdue escalation angles: theatrical, never mean. The drama is JIRI's own;
# the user is always the hero who is about to fix it.
_OVERDUE_ANGLES = (
    "mock-panic about the deadline",
    "one long dramatic sigh",
    "tiny-robot melodrama",
    "faux-ceremonial announcement",
    "self-deprecating aside about being a small robot",
    "desk objects reacting to the situation",
    "the task as a sulking character waiting for attention",
    "absurd emergency procedure",
    "theatrical narration, like a nature documentary",
    "cheerleader confidence that it is one quick win away",
)

# Home-screen "thought" angles: half witty, half sincere. A thought sits under
# a fact line the owner reads all day, so pure gags wear thin; warmth carries.
_THOUGHT_ANGLES = (
    "sincere and warm, a smile more than a joke",
    "understated deadpan",
    "self-deprecating aside about being a small robot",
    "quiet encouragement, like a friend leaning over",
    "affectionate remark about an inanimate desk object",
    "delighted overreaction to something tiny",
    "gentle observation about the moment",
    "misplaced optimism",
    "cosy, content, a little proud of the user",
    "absurd but kind non-sequitur",
)

# Per-category writing brief and slot vocabulary, keyed by the category strings
# persona.py actually constructs. This is a *description* of known categories,
# not the authority on which categories exist — an unknown category still gets
# a generic brief and no slots, so persona.py can add one without breaking AI.
#
# HUMOUR POLICY (docs/AI_SPEC.md §4a): every category is playful. Categories
# that comment on something late escalate in *theatre*, not in hostility — the
# face gets more dramatic and so do the words, but the joke is always on the
# situation or on JIRI, never on the user. No guilt, no moralising, no mean
# sarcasm.
#
# Kept for API compatibility; nothing is humour-free any more.
HUMOUR_FREE_CATEGORIES: frozenset[str] = frozenset()

_OVERDUE_RULE = (
    " Escalate the theatre, never the meanness: no guilt, no lecturing, no "
    "insults. The user is the hero about to fix it. {task} is optional and "
    "often funnier without it."
)

THOUGHT_PREFIX = "thought_"
THOUGHT_MAX_CHARS = 60

_THOUGHT_RULE = (
    " Mix witty and sincere lines. Under 60 characters. The screen already "
    "shows the fact, so never restate it: no numbers, no times, no amounts, "
    "no task names, no placeholders. Never mean, never guilt."
)

_BUCKET_BRIEFS: dict[str, str] = {
    # Pet reflexes: tiny spoken reactions while the owner touches the device
    # or the data changes. Very short (under 40 characters), first person,
    # like a small creature reacting out loud. No placeholders.
    "pet_poked": "The owner just poked JIRI's face on the touchscreen. A tiny surprised reaction. Under 40 characters.",
    "pet_tickled": "The owner is tapping JIRI fast, like tickling. Giggly, delighted, begging them to stop (not really). Under 40 characters.",
    "pet_overpoked": "The owner keeps poking JIRI over and over. Mock-grumpy, theatrical, still fond. Under 40 characters.",
    "pet_wake": "JIRI was asleep and a tap just woke it. Groggy then pleased to see the owner. Under 40 characters.",
    "pet_yawn": "JIRI is yawning because it is tired. Sleepy, cute. Under 40 characters.",
    "pet_bored": "Nobody has touched JIRI in a long while and nothing is happening. Dramatically bored, hinting for attention. Under 40 characters.",
    "pet_saw_water": "JIRI just noticed the owner logged a drink of water. Proud, cheering. Under 40 characters.",
    "pet_saw_done": "JIRI just noticed a task disappeared from the list (done). Celebrating. Under 40 characters.",
    "pet_saw_new_task": "JIRI just noticed a new task appeared on the list. Curious, intrigued. Under 40 characters.",
    "pet_saw_usage": "JIRI noticed the owner's AI usage numbers moved (they are coding with an AI). Nosy, playful. Under 40 characters.",
    "pet_saw_change": "Something on JIRI's dashboard just changed. Curious. Under 40 characters.",
    # Home-screen thoughts: the display cycles (mood, FACT line, QUIP). The
    # fact line is computed from real data and shown separately ("Pay bill ·
    # 49m late"); the quip only reacts to it. Hence: no numbers, no task
    # names, no placeholders, never restating the fact. Max 60 characters
    # (THOUGHT_MAX_CHARS), enforced in generate().
    "thought_late": "A task is overdue; the screen shows which and by how much. React with gentle theatre or warm encouragement: it is one small win away." + _THOUGHT_RULE,
    "thought_soon": "A task is coming up soon; the screen shows which and when. Friendly heads-up energy, a little excited, never a warning." + _THOUGHT_RULE,
    "thought_tasks_clear": "The task list is completely empty. Delight, calm, a tiny celebration, or mild suspicion of all this peace." + _THOUGHT_RULE,
    "thought_tasks_some": "There are a few tasks on the list, none urgent. JIRI is cheerfully keeping an eye on them. Do not say the list is empty." + _THOUGHT_RULE,
    "thought_water_low": "The owner has drunk little water today. A soft, playful nudge to sip something; the joke is hydration, plants, or JIRI envying cups. Never guilt." + _THOUGHT_RULE,
    "thought_water_good": "The owner is on track with water today. Encouraging, pleased, a little proud." + _THOUGHT_RULE,
    "thought_water_done": "The owner hit today's water goal. Celebrate warmly: a tiny toast, a proud robot, a happy plant." + _THOUGHT_RULE,
    "thought_weather_hot": "It is hot outside. Playful, caring: shade, water, not melting, JIRI's pixels feeling toasty." + _THOUGHT_RULE,
    "thought_weather_rain": "Rain is likely today. Cosy and practical: umbrella, staying dry, rain sounds, warm drinks." + _THOUGHT_RULE,
    "thought_weather_nice": "The weather outside is pleasant. Light, cheerful: fresh air, a short walk, a stretch, a window." + _THOUGHT_RULE,
    "thought_weather_cold": "It is cold outside. Cosy and caring: layers, warm drinks, JIRI wishing it had a tiny scarf." + _THOUGHT_RULE,
    "thought_focus": "A focus session is running. JIRI is a quiet, loyal guard keeping distractions away. Calm, encouraging, whisper-level." + _THOUGHT_RULE,
    "thought_usage_high": "The owner has used a lot of their AI coding assistant today. Nosy, playful, impressed by the hustle; maybe suggest a stretch or a break. Never scold." + _THOUGHT_RULE,
    "thought_usage_ok": "The owner's AI coding assistant usage is moderate today. Easygoing, approving, curious what they are building." + _THOUGHT_RULE,
    "thought_night": "It is late at night. Sleepy, soft, cosy; a gentle hint that rest is lovely too. Whisper energy." + _THOUGHT_RULE,
    "thought_morning": "It is morning, the start of the day. Bright, hopeful, a little sleepy-cute, glad to see the owner." + _THOUGHT_RULE,
    # `reminder` is what messages.reminder_message() actually looks up; its
    # mood carries the urgency (alert, annoyed, angry, rage) — see
    # _REMINDER_MOOD_BRIEFS.
    "reminder": "A task has just come due. Cheerful heads-up, like a tiny butler ringing a bell." + _OVERDUE_RULE,
    "todo_due_soon": "A task is due in {minutes} minutes. Excited countdown energy, a heads-up not a warning. {task} is optional.",
    "water": "A playful nudge to drink water. {amount} is ml drunk today, {goal} is the daily goal in ml (both optional). Never about willpower - the joke is hydration itself, plants, or JIRI being jealous it cannot drink.",
    "weather_hot": "It is hot outside ({temp} is degrees C, {condition} is the sky, both optional). Playful practical advice: water, shade, not melting.",
    "weather_rain": "Rain is likely today ({temp} degrees C, {condition}, both optional). Playful practical advice: umbrella, staying dry.",
    "focus": "A focus session is running. JIRI is the user's tiny, very serious bodyguard keeping distractions away. Encouraging, not saccharine.",
    "celebrate": "The user just finished a task. Small, delighted celebration - a tiny parade, confetti made of pixels.",
    "ambient": "Nothing is pending at all. JIRI is bored, delighted by the calm, or mildly suspicious of it.",
    "watching": "There are tasks on the list but none are due yet. JIRI is cheerfully keeping watch. Do not claim the list is empty.",
    "sleep": "Quiet hours, late at night. Low-key, sleepy, cosy, barely awake, whispering.",
}

_REMINDER_MOOD_BRIEFS: dict[str, str] = {
    "alert": _BUCKET_BRIEFS["reminder"],
    "annoyed": "A task is 10 to 30 minutes overdue. Mild theatrics: one dramatic sigh, a raised pixel eyebrow, polite fidgeting." + _OVERDUE_RULE,
    "angry": "A task is 30 minutes to 2 hours overdue. Full melodrama: mock-panic, clutching imaginary pearls, staged fainting, writing memoirs about the wait." + _OVERDUE_RULE,
    "rage": "A task is over 2 hours overdue. Maximum tiny-robot opera: declaring a desk emergency, imaginary sirens, a dramatic collapse. Still affectionate." + _OVERDUE_RULE,
}

_BUCKET_SLOTS: dict[str, tuple[str, ...]] = {
    "reminder": ("task", "minutes"),
    "todo_due_soon": ("task", "minutes"),
    "water": ("amount", "goal"),
    "weather_hot": ("temp", "condition"),
    "weather_rain": ("temp", "condition"),
    "focus": (),
    "celebrate": (),
    "ambient": (),
    "watching": (),
    "sleep": (),
    "thought_late": (),
    "thought_soon": (),
    "thought_tasks_clear": (),
    "thought_tasks_some": (),
    "thought_water_low": (),
    "thought_water_good": (),
    "thought_water_done": (),
    "thought_weather_hot": (),
    "thought_weather_rain": (),
    "thought_weather_nice": (),
    "thought_weather_cold": (),
    "thought_focus": (),
    "thought_usage_high": (),
    "thought_usage_ok": (),
    "thought_night": (),
    "thought_morning": (),
}

# Categories whose briefs use the overdue (theatrical) angle set.
_OVERDUE_MOODS = frozenset({"annoyed", "angry", "rage"})

# Cold-start seed: the mood each tuned category is most often rendered with.
# Used ONLY when `ai_wanted` is empty (a fresh install whose screen has not
# rendered yet). Once the render path records demand, that list is
# authoritative again (spec invariant I5) and this map is ignored.
_SEED_MOODS: dict[str, str] = {
    "ambient": "idle",
    "reminder": "alert",
    "celebrate": "happy",
    "focus": "focused",
    "sleep": "sleeping",
}


def _is_humour_free(category: str, mood: str) -> bool:
    """Retained for compatibility. The playful policy has no humour-free buckets."""
    return category in HUMOUR_FREE_CATEGORIES


def seed_buckets() -> list[tuple[str, str]]:
    """Fallback demand for a fresh install. Only known categories, in seed order."""
    known = set(known_categories())
    return [(cat, mood) for cat, mood in _SEED_MOODS.items() if cat in known]


def slots_for(category: str) -> tuple[str, ...]:
    """Slots a template for this category may use. Unknown category -> none."""
    return _BUCKET_SLOTS.get(category, ())


def max_chars_for(category: str, configured: int = SPEECH_MAX_CHARS) -> int:
    """Longest line a bucket may store. Thoughts share the face with a fact line."""
    limit = min(int(configured), SPEECH_MAX_CHARS)
    if category.startswith(THOUGHT_PREFIX):
        limit = min(limit, THOUGHT_MAX_CHARS)
    return limit


def brief_for(category: str, mood: str) -> str:
    """Writing brief for a bucket. Unknown categories degrade, never fail."""
    if category == "reminder" and mood in _REMINDER_MOOD_BRIEFS:
        return _REMINDER_MOOD_BRIEFS[mood]
    known = _BUCKET_BRIEFS.get(category)
    if known:
        return known
    return f"Category '{category}', mood '{mood}'. Write in that tone."


def known_categories() -> tuple[str, ...]:
    """Categories with a tuned brief. Used by refill to choose what to warm."""
    return tuple(_BUCKET_BRIEFS)


def build_messages(
    category: str,
    mood: str,
    *,
    personality: str,
    max_chars: int,
    count: int,
    avoid: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Build the batch-generation prompt for one bucket.

    `avoid` is the lines already in the cache for this bucket. Feeding them
    back is the single most effective anti-repetition lever available — more
    effective than any sampling parameter, because it targets the actual
    duplicates rather than the distribution they came from.
    """
    allowed = slots_for(category)
    slot_text = ", ".join("{" + s + "}" for s in allowed) if allowed else "(none - use no placeholders)"
    system = _SYSTEM_PROMPT.format(
        personality=personality.replace("_", " "),
        aim="40 to 70" if max_chars >= 70 else f"25 to {max(10, max_chars - 8)}",
        max_chars=max_chars,
        slots=slot_text,
    )

    parts = [brief_for(category, mood), ""]
    if category.startswith(THOUGHT_PREFIX):
        pool = _THOUGHT_ANGLES
    elif category == "reminder" and mood in _OVERDUE_MOODS:
        pool = _OVERDUE_ANGLES
    else:
        pool = _ANGLES
    angles = ", ".join(pool[:count])
    parts.append(
        f"Write {count} lines, one from each of these angles, in this order: {angles}."
    )
    parts.append(
        "The joke's target is always the situation or JIRI itself, never the user."
    )
    if avoid:
        # Kept short on purpose: FreeLLMAPI may route to a ~1k-token model.
        listed = "\n".join(f"- {line}" for line in avoid[:12])
        parts += [
            "",
            "Already in use. Do not reuse these, and do not reuse their "
            "sentence structures or their opening words:",
            listed,
        ]
    parts += ["", f"Output exactly {count} lines and nothing else."]
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(parts)},
    ]


def recent_lines(
    category: str,
    mood: str,
    *,
    limit: int = 40,
    db_path: str | None = None,
) -> tuple[str, ...]:
    """Lines already cached for a bucket, newest first. Feeds `avoid`."""
    ensure_schema(db_path)
    try:
        with db.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT text FROM ai_cache
                WHERE category = ? AND mood = ?
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (category, mood, int(limit)),
            ).fetchall()
        return tuple(str(r["text"]) for r in rows)
    except Exception:
        return ()


# --- Provider plumbing ------------------------------------------------------

def _env(name: str) -> str:
    """Read `name`, accepting a JIRI_-prefixed variant first."""
    if not name:
        return ""
    return (os.environ.get(f"JIRI_{name}") or os.environ.get(name) or "").strip()


def resolve_provider(cfg: AiProviderConfig) -> tuple[str, str, str]:
    """Return (base_url, model, api_key). Raises AiError if unusable."""
    preset = PROVIDER_PRESETS.get(cfg.name, {})
    base_url = str(cfg.base_url or _env(str(preset.get("base_url_env", ""))) or preset.get("base_url", "")).rstrip("/")
    if not base_url:
        env_name = preset.get("base_url_env")
        hint = f" (set {env_name})" if env_name else ""
        raise AiError(f"Provider '{cfg.name}' has no base_url{hint}")
    suffix = str(preset.get("base_url_suffix", ""))
    if suffix and not base_url.endswith(suffix):
        base_url = f"{base_url}{suffix}"
    model = cfg.model or _env(str(preset.get("model_env", ""))) or str(preset.get("default_model", ""))
    if not model:
        raise AiError(f"Provider '{cfg.name}' has no model configured")
    key_env = cfg.api_key_env or preset.get("api_key_env", "")
    if not key_env:
        return base_url, model, ""
    # Accept the provider's conventional name or a JIRI_-prefixed variant.
    api_key = _env(str(key_env))
    if not api_key:
        raise AiError(f"Provider '{cfg.name}' needs {key_env} (or JIRI_{key_env}) in the environment")
    return base_url, str(model), api_key


def _chat(
    cfg: AiProviderConfig,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float,
    max_tokens: int,
    temperature: float | None = None,
) -> tuple[str, dict[str, str], str]:
    """One chat-completions call. Returns (content, rate-limit headers, model).

    Raises AiError on any HTTP error, malformed body, or empty content, so
    the caller's retry/breaker/failover logic treats them all as failures.
    """
    base_url, model, api_key = resolve_provider(cfg)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    preset = PROVIDER_PRESETS.get(cfg.name, {})
    # Per-provider tuning beats one global number: Gemini 3 must stay at its
    # 1.0 default (lowering it can induce looping), while Qwen wants 0.7 with
    # a presence penalty. An explicit config value still wins over both.
    if temperature is None:
        temperature = float(preset.get("temperature", 1.0))
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        # Groq deprecated `max_tokens` in favour of `max_completion_tokens`;
        # Gemini's compat layer silently ignores parameters it does not know.
        # Sending both is the only spelling that bounds output on every
        # provider — a silently-ignored cap means an unbounded response.
        "max_completion_tokens": max_tokens,
        "max_tokens": max_tokens,
        # Groq rewrites temperature 0 to 1e-8 and requires 0 < t <= 2.
        "temperature": temperature,
    }
    # Gemini's compat layer silently ignores parameters it does not recognise,
    # and Groq 400s on a few. Provider-specific keys therefore live in the
    # preset, never in the shared payload above.
    payload.update(preset.get("params", {}))
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout_seconds,
    )
    if resp.status_code == 429:
        raise AiError(f"{cfg.name}: rate limited, retry after {_retry_after(resp)}s")
    if resp.status_code >= 400:
        raise AiError(f"{cfg.name}: HTTP {resp.status_code} {resp.text[:160]}")
    try:
        # strict=False: some gateways (FreeLLMAPI) emit raw newlines inside JSON
        # strings, which `resp.json()` rejects. Multi-line content is exactly
        # what we ask for, so lenient parsing is required, and harmless for
        # providers that escape correctly.
        data = json.loads(resp.text, strict=False)
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiError(f"{cfg.name}: unexpected response shape") from exc
    _last_call.usage = data.get("usage") if isinstance(data, dict) else None
    text = str(content or "").strip()
    if not text:
        # Reasoning models can burn the whole token budget on hidden thinking
        # and return "". That is a failure, not a success with zero lines —
        # otherwise it resets the breaker and blocks failover.
        raise AiError(f"{cfg.name}: empty content")
    return text, rate_limit_headers(resp), model


def rate_limit_headers(resp: requests.Response) -> dict[str, str]:
    """Extract whatever rate-limit telemetry the provider volunteered.

    Groq sets these on every response; other providers may set none. Purely
    informational — surfaced on the admin page so a shrinking quota is visible
    before it turns into 429s.
    """
    keys = (
        "x-ratelimit-remaining-requests",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset-requests",
    )
    return {k: resp.headers[k] for k in keys if k in resp.headers}


def _retry_after(resp: requests.Response) -> int:
    raw = resp.headers.get("Retry-After", "")
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        return BREAKER_COOLDOWN_SECONDS


# --- Circuit breaker and quota ---------------------------------------------

def breaker_state(provider: str, *, db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now()
    raw = db.get_setting(f"{BREAKER_KEY_PREFIX}{provider}", db_path=db_path)
    if not raw:
        return {"failures": 0, "open_until": None, "open": False}
    try:
        data = json.loads(raw)
    except ValueError:
        return {"failures": 0, "open_until": None, "open": False}
    open_until = data.get("open_until")
    is_open = False
    if open_until:
        try:
            is_open = datetime.fromisoformat(str(open_until)) > current
        except ValueError:
            is_open = False
    return {"failures": int(data.get("failures", 0)), "open_until": open_until, "open": is_open}


def record_success(provider: str, *, db_path: str | None = None) -> None:
    db.set_setting(f"{BREAKER_KEY_PREFIX}{provider}", json.dumps({"failures": 0, "open_until": None}), db_path=db_path)


def record_failure(
    provider: str,
    *,
    db_path: str | None = None,
    now: datetime | None = None,
    cooldown_seconds: int = BREAKER_COOLDOWN_SECONDS,
) -> dict[str, object]:
    current = now or datetime.now()
    failures = int(breaker_state(provider, db_path=db_path, now=current)["failures"]) + 1
    open_until = None
    if failures >= BREAKER_FAILURE_THRESHOLD:
        open_until = (current + timedelta(seconds=cooldown_seconds)).isoformat(timespec="seconds")
    payload = {"failures": failures, "open_until": open_until}
    db.set_setting(f"{BREAKER_KEY_PREFIX}{provider}", json.dumps(payload), db_path=db_path)
    return payload


def usage_today(*, db_path: str | None = None, now: datetime | None = None) -> int:
    current = now or datetime.now()
    raw = db.get_setting(f"{USAGE_KEY_PREFIX}{current.date().isoformat()}", db_path=db_path)
    try:
        return int(raw or 0)
    except ValueError:
        return 0


def bump_usage(*, db_path: str | None = None, now: datetime | None = None) -> int:
    current = now or datetime.now()
    count = usage_today(db_path=db_path, now=current) + 1
    db.set_setting(f"{USAGE_KEY_PREFIX}{current.date().isoformat()}", str(count), db_path=db_path)
    return count


# --- Cache maintenance ------------------------------------------------------

def bucket_counts(*, db_path: str | None = None) -> dict[tuple[str, str, int], int]:
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT category, mood, angry_level, COUNT(*) AS n FROM ai_cache GROUP BY category, mood, angry_level"
        ).fetchall()
    return {(str(r["category"]), str(r["mood"]), int(r["angry_level"])): int(r["n"]) for r in rows}


def wanted_buckets(*, db_path: str | None = None) -> list[tuple[str, str]]:
    """Buckets the render path has actually asked for, most-missed first.

    This is the authoritative list of buckets — not a constant in this module.
    A category added to persona.py appears here the first time it renders.
    """
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT category, mood FROM ai_wanted ORDER BY miss_count DESC, last_wanted_at DESC"
        ).fetchall()
    return [(str(r["category"]), str(r["mood"])) for r in rows]


def store_lines(
    category: str,
    mood: str,
    angry_level: int,
    lines: list[str],
    *,
    provider: str,
    model: str,
    db_path: str | None = None,
    now: datetime | None = None,
) -> int:
    if not lines:
        return 0
    ensure_schema(db_path)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    inserted = 0
    with db.connect(db_path) as conn:
        for text in lines:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO ai_cache
                    (category, mood, angry_level, text, provider, model, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (category, mood, int(angry_level), text, provider, model, stamp),
            )
            inserted += cur.rowcount if cur.rowcount > 0 else 0
    return inserted


def prune(max_per_bucket: int, *, db_path: str | None = None) -> int:
    """Keep the newest N lines per bucket. Bounds the DB against the 50MB target."""
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        cur = conn.execute(
            """
            DELETE FROM ai_cache WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY category, mood, angry_level ORDER BY created_at DESC, id DESC
                    ) AS rn
                    FROM ai_cache
                ) WHERE rn > ?
            )
            """,
            (int(max_per_bucket),),
        )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def clear_cache(*, db_path: str | None = None) -> int:
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM ai_cache")
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


# --- Call log (written by the background worker only) -----------------------

def _model_name(cfg: AiProviderConfig) -> str:
    try:
        return resolve_provider(cfg)[1]
    except Exception:  # noqa: BLE001
        return str(cfg.model or "")


def _int_or_none(value) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def log_call(
    *,
    provider: str,
    model: str,
    category: str,
    mood: str,
    ok: bool,
    latency_ms: int = 0,
    returned: int = 0,
    accepted: int = 0,
    stored: int = 0,
    error: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    db_path: str | None = None,
    now: datetime | None = None,
) -> None:
    """Record one provider attempt. Never raises: logging must not break refill."""
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    short_error = None
    if error:
        short_error = _WHITESPACE.sub(" ", str(error)).strip()[:CALL_ERROR_MAX_CHARS]
    try:
        ensure_schema(db_path)
        with db.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO ai_calls
                    (at, provider, model, category, mood, ok, latency_ms,
                     returned, accepted, stored, error, prompt_tokens, completion_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (stamp, provider, model or "", category, mood, 1 if ok else 0, int(latency_ms),
                 int(returned), int(accepted), int(stored), short_error,
                 prompt_tokens, completion_tokens),
            )
            conn.execute(
                "DELETE FROM ai_calls WHERE id NOT IN (SELECT id FROM ai_calls ORDER BY id DESC LIMIT ?)",
                (CALL_LOG_KEEP,),
            )
    except Exception:  # noqa: BLE001 - the call log is observability, not state
        return


def recent_calls(limit: int = 50, *, db_path: str | None = None) -> list[dict[str, object]]:
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def calls_summary(*, db_path: str | None = None, now: datetime | None = None) -> dict[str, object]:
    """Today's attempts from the call log: count, success rate, latency, tokens."""
    current = now or datetime.now()
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n,
                   COALESCE(SUM(ok), 0) AS ok_n,
                   AVG(CASE WHEN ok = 1 THEN latency_ms END) AS avg_ok_ms,
                   SUM(prompt_tokens) AS p_tok,
                   SUM(completion_tokens) AS c_tok,
                   COALESCE(SUM(stored), 0) AS stored_n,
                   MAX(at) AS last_at
            FROM ai_calls WHERE substr(at, 1, 10) = ?
            """,
            (current.date().isoformat(),),
        ).fetchone()
        last = conn.execute("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 1").fetchone()
    attempts = int(row["n"] or 0)
    ok_n = int(row["ok_n"] or 0)
    p_tok, c_tok = row["p_tok"], row["c_tok"]
    return {
        "attempts_today": attempts,
        "ok_today": ok_n,
        "failed_today": attempts - ok_n,
        "success_rate": round(100.0 * ok_n / attempts) if attempts else None,
        "avg_latency_ms": int(row["avg_ok_ms"]) if row["avg_ok_ms"] is not None else None,
        "prompt_tokens_today": int(p_tok) if p_tok is not None else None,
        "completion_tokens_today": int(c_tok) if c_tok is not None else None,
        "tokens_today": (int(p_tok or 0) + int(c_tok or 0)) if (p_tok is not None or c_tok is not None) else None,
        "stored_today": int(row["stored_n"] or 0),
        "last_call": dict(last) if last else None,
    }


def bucket_overview(*, db_path: str | None = None) -> list[dict[str, object]]:
    """Every bucket the screen asked for or the cache holds, with its lines.

    A bucket with 0 lines is served by the built-in deterministic wording.
    """
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        cached = conn.execute(
            """
            SELECT c.category, c.mood, COUNT(*) AS n, MAX(c.last_used_at) AS last_used,
                   COALESCE(SUM(c.use_count), 0) AS uses,
                   (SELECT text FROM ai_cache n2 WHERE n2.category = c.category AND n2.mood = c.mood
                    AND n2.angry_level = 0 ORDER BY n2.created_at DESC, n2.id DESC LIMIT 1) AS newest
            FROM ai_cache c WHERE c.angry_level = 0
            GROUP BY c.category, c.mood
            """
        ).fetchall()
        wanted = conn.execute("SELECT category, mood, miss_count, last_wanted_at FROM ai_wanted").fetchall()
    buckets: dict[tuple[str, str], dict[str, object]] = {}
    for r in wanted:
        buckets[(r["category"], r["mood"])] = {
            "category": r["category"], "mood": r["mood"], "lines": 0, "newest": None,
            "last_used": None, "uses": 0, "misses": int(r["miss_count"]), "last_wanted": r["last_wanted_at"],
        }
    for r in cached:
        entry = buckets.setdefault((r["category"], r["mood"]), {
            "category": r["category"], "mood": r["mood"], "misses": 0, "last_wanted": None,
        })
        entry.update({"lines": int(r["n"]), "newest": r["newest"], "last_used": r["last_used"], "uses": int(r["uses"])})
    return sorted(buckets.values(), key=lambda b: (int(b["lines"]) > 0, b["category"], b["mood"]))


def recent_generated(limit: int = 20, *, db_path: str | None = None) -> list[dict[str, object]]:
    ensure_schema(db_path)
    with db.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT category, mood, text, provider, model, created_at, last_used_at, use_count
            FROM ai_cache ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def activity(
    *,
    config: AiConfig,
    db_path: str | None = None,
    now: datetime | None = None,
    calls_limit: int = 50,
    lines_limit: int = 20,
) -> dict[str, object]:
    """Everything the admin AI page shows. Read-only."""
    current = now or datetime.now()
    return {
        "status": status(config=config, db_path=db_path, now=current),
        "summary": calls_summary(db_path=db_path, now=current),
        "calls": recent_calls(calls_limit, db_path=db_path),
        "buckets": bucket_overview(db_path=db_path),
        "recent_lines": recent_generated(lines_limit, db_path=db_path),
    }


# --- Refill (background only) -----------------------------------------------

def _compact(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop the 'Already in use' history block from the user prompt."""
    out = []
    for m in messages:
        content = m["content"]
        if m["role"] == "user" and "Already in use" in content:
            head, _, rest = content.partition("Already in use")
            tail = rest[rest.find("Output exactly"):] if "Output exactly" in rest else ""
            content = head.rstrip() + "\n\n" + tail
        out.append({**m, "content": content})
    return out


def generate(
    category: str,
    mood: str,
    *,
    config: AiConfig,
    personality: str,
    count: int = DEFAULT_LINES_PER_CALL,
    db_path: str | None = None,
    now: datetime | None = None,
    sleep=None,
) -> dict[str, object]:
    """One bucket, one API call, through the failover chain.

    Returns a result dict. Never raises for provider problems — the caller is a
    background loop that must keep running.
    """
    current = now or datetime.now()
    allowed = slots_for(category)
    max_chars = max_chars_for(category, int(config.max_output_chars))
    # Over-generate and filter mechanically. Every model in this class busts
    # stated character limits and repeats itself; asking for more than we need
    # means the sanitizer can be strict without starving the bucket.
    ask_for = min(len(_ANGLES), max(count, count * 2))
    messages = build_messages(
        category, mood,
        personality=personality,
        max_chars=max_chars,
        count=ask_for,
        avoid=recent_lines(category, mood, db_path=db_path),
    )
    attempted: list[str] = []
    for provider in config.providers:
        if not provider.enabled:
            continue
        try:
            resolve_provider(provider)
        except AiError:
            # Not configured (e.g. no API key): not a failure, just not usable.
            attempted.append(f"{provider.name}:not-configured")
            continue
        state = breaker_state(provider.name, db_path=db_path, now=current)
        if state["open"]:
            attempted.append(f"{provider.name}:breaker-open")
            continue
        budget = config.max_tokens
        compacted = False
        for attempt in range(MAX_ATTEMPTS_PER_PROVIDER + 1):
            _last_call.usage = None
            started = time.monotonic()
            try:
                raw, limits, used_model = _chat(
                    provider, messages,
                    timeout_seconds=config.timeout_seconds,
                    max_tokens=budget,
                    temperature=config.temperature,
                )
            except (AiError, requests.RequestException) as exc:
                if "HTTP 413" in str(exc) and not compacted:
                    # The gateway routed us to a small-context model: drop the
                    # "already in use" history, shrink the output budget, retry.
                    log_call(
                        provider=provider.name, model=_model_name(provider),
                        category=category, mood=mood, ok=False,
                        latency_ms=int((time.monotonic() - started) * 1000),
                        error="HTTP 413: compacting prompt and retrying",
                        db_path=db_path, now=current,
                    )
                    messages = _compact(messages)
                    budget = min(budget, 160)
                    compacted = True
                    continue
                attempted.append(f"{provider.name}:{exc}")
                log_call(
                    provider=provider.name, model=_model_name(provider),
                    category=category, mood=mood, ok=False,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    error=f"{exc.__class__.__name__}: {exc}",
                    db_path=db_path, now=current,
                )
                if attempt + 1 < MAX_ATTEMPTS_PER_PROVIDER + (1 if compacted else 0):
                    delay = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2**attempt))
                    if sleep is not None:
                        sleep(delay + random.uniform(0, delay / 2))
                    continue
                record_failure(provider.name, db_path=db_path, now=current)
                break

            bump_usage(db_path=db_path, now=current)
            record_success(provider.name, db_path=db_path)
            candidates = [
                sanitize(part, max_chars=max_chars, allowed_slots=allowed)
                for part in raw.splitlines()
            ]
            clean = [c for c in candidates if c]
            # A template whose slots could overflow the display is rejected here,
            # not at render time when there is no way to recover.
            # Slots are budgeted at 24 chars: a long task title wraps onto the
            # second display line rather than overflowing it.
            clean = [c for c in clean if worst_case_length(c, 24) <= max_chars]
            if category.startswith(THOUGHT_PREFIX):
                # The fact line already carries every number; a digit in a
                # quip is a restated (or invented) fact.
                clean = [c for c in clean if not any(ch.isdigit() for ch in c)]
            latency_ms = int((time.monotonic() - started) * 1000)
            stored = store_lines(
                category, mood, 0, clean,
                provider=provider.name, model=used_model,
                db_path=db_path, now=current,
            )
            usage = getattr(_last_call, "usage", None)
            usage = usage if isinstance(usage, dict) else {}
            log_call(
                provider=provider.name, model=used_model,
                category=category, mood=mood, ok=True,
                latency_ms=latency_ms,
                returned=len(raw.splitlines()), accepted=len(clean), stored=stored,
                prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
                completion_tokens=_int_or_none(usage.get("completion_tokens")),
                db_path=db_path, now=current,
            )
            return {
                "ok": True,
                "provider": provider.name,
                "returned": len(raw.splitlines()),
                "accepted": len(clean),
                "stored": stored,
                "attempted": attempted,
                "limits": limits,
            }
    return {"ok": False, "provider": None, "stored": 0, "accepted": 0, "attempted": attempted}


def refill(
    *,
    config: AiConfig,
    personality: str = "funny_sarcastic",
    db_path: str | None = None,
    now: datetime | None = None,
    max_buckets: int = MAX_BUCKETS_PER_REFILL,
    sleep=None,
) -> dict[str, object]:
    """Top up the emptiest buckets. Background worker entry point."""
    current = now or datetime.now()
    if not any(p.enabled for p in config.providers):
        return {"skipped": "no-providers", "calls": 0, "stored": 0}

    used = usage_today(db_path=db_path, now=current)
    if used >= config.daily_request_cap:
        return {"skipped": "daily-cap", "calls": 0, "stored": 0, "used": used}

    ensure_schema(db_path)
    counts = bucket_counts(db_path=db_path)
    # Fresh install: nothing has rendered yet, so nothing is "wanted". Warm a
    # small seed set so the first screen already has lines. Still bounded by
    # max_buckets and the daily cap below.
    demand = wanted_buckets(db_path=db_path) or seed_buckets()
    hungry = [
        (cat, mood)
        for (cat, mood) in demand
        if counts.get((cat, mood, 0), 0) < config.min_lines_per_bucket
    ]

    calls = 0
    stored = 0
    results = []
    for cat, mood in hungry[:max_buckets]:
        if usage_today(db_path=db_path, now=current) >= config.daily_request_cap:
            break
        result = generate(
            cat, mood,
            config=config, personality=personality,
            db_path=db_path, now=current, sleep=sleep,
        )
        calls += 1
        stored += int(result.get("stored", 0))
        results.append({"category": cat, "mood": mood, **result})

    pruned = prune(config.max_lines_per_bucket, db_path=db_path)
    return {
        "calls": calls,
        "stored": stored,
        "pruned": pruned,
        "used": usage_today(db_path=db_path, now=current),
        "cap": config.daily_request_cap,
        "results": results,
    }


# --- Status (admin surface) -------------------------------------------------

def status(
    *,
    config: AiConfig,
    db_path: str | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now()
    ensure_schema(db_path)
    counts = bucket_counts(db_path=db_path)
    total = sum(counts.values())
    providers = []
    for provider in config.providers:
        state = breaker_state(provider.name, db_path=db_path, now=current)
        try:
            _, model, api_key = resolve_provider(provider)
            ready, detail = True, "ready" if api_key or provider.name == "ollama" else "no key required"
        except AiError as exc:
            ready, model, detail = False, provider.model, str(exc)
        providers.append({
            "name": provider.name,
            "model": model,
            "enabled": provider.enabled,
            "ready": ready,
            "detail": detail,
            "breaker_open": bool(state["open"]),
            "failures": state["failures"],
            "open_until": state["open_until"],
        })
    return {
        "enabled": True,
        "ready": any(provider["ready"] and provider["enabled"] for provider in providers),
        "providers": providers,
        "used_today": usage_today(db_path=db_path, now=current),
        "daily_cap": config.daily_request_cap,
        "cache_total": total,
        "buckets": [
            {"category": cat, "mood": mood, "angry_level": lvl, "lines": n}
            for (cat, mood, lvl), n in sorted(counts.items())
        ],
        "min_lines_per_bucket": config.min_lines_per_bucket,
        "max_output_chars": config.max_output_chars,
    }
