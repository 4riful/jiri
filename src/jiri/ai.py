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
import unicodedata

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

# Bumped whenever the prompt or the sanitizer changes meaningfully. Stored on
# every row so a prompt change can invalidate stale wording without a migration.
PROMPT_VERSION = 1

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
                return None
            conn.execute(
                "UPDATE ai_cache SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                (current.isoformat(timespec="seconds"), int(row["id"])),
            )
            return str(row["text"])
    except Exception:
        # A cache miss and a broken cache are the same thing to the caller.
        return None


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
You write one-line status messages for JIRI, a small desk assistant device.

JIRI's voice: {personality}. Playful, warm, a little theatrical. Delighted by \
small things. It lives on the user's desk and considers this a shared \
workspace. Fond of the user, always.

Voice rules:
- Be genuinely funny, not merely wry. Specific and surprising beats generic.
- Delight in small stuff. A finished task is worth a tiny parade.
- Happy to be absurd about objects, the desk, the weather, or itself.
- Never explain the joke.
- No emoji. No rhetorical questions aimed at the user.
- Never scold, guilt, moralise, or comment on the user's character. JIRI is \
playful about the situation and about itself, never at the user's expense.

Never use these words or shapes — they are the signature of generic AI writing:
delve, dive into, testament, chef's kiss, tapestry, realm, elevate, unleash, \
navigate the, "not just X but Y", "it's worth noting", "in a world where".

Hard format rules:
- Output ONE line per line. Never a newline inside a line.
- No preamble, no numbering, no bullets, no quotes, no markdown.
- Aim for under 120 characters per line. Never exceed {max_chars}.
- Plain ASCII punctuation only.
- Use ONLY these placeholders, spelled exactly: {slots}
- Invent no facts, numbers, times, or names. Where a specific value belongs, \
use a placeholder."""

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
    "sincere and warm, no joke at all",
)

# Per-category writing brief and slot vocabulary, keyed by the category strings
# persona.py actually constructs. This is a *description* of known categories,
# not the authority on which categories exist — an unknown category still gets
# a generic brief and no slots, so persona.py can add one without breaking AI.
#
# HUMOUR POLICY: categories that comment on something the user is failing to
# do get plain, short, neutral wording. Research on proactive assistants found
# "nudging" — the assistant remarking on the user's behaviour — was the single
# most-disliked scenario, and that escalating snark reads as nagging. The face
# escalates; the words do not. See docs/AI_SPEC.md §8.
HUMOUR_FREE_CATEGORIES = frozenset({
    "todo_annoyed", "todo_late", "todo_angry", "todo_rage",
})

_BUCKET_BRIEFS: dict[str, str] = {
    "todo_due_soon": "A task is due soon. State it plainly. One light touch at most.",
    "todo_annoyed": "A task is slightly overdue. Plain and short. No joke.",
    "todo_late": "A task is late. Plain and short. No joke.",
    "todo_angry": "A task is well overdue. Shorter still. Neutral. No joke.",
    "todo_rage": "A task is very overdue. The shortest, flattest possible statement of fact.",
    "water": "A gentle nudge to drink water. Warm and light. Never critical, never about willpower - the joke, if any, is about hydration itself.",
    "weather_hot": "It is hot out. Practical advice, delivered wryly.",
    "weather_rain": "Rain is likely. Practical advice, delivered wryly.",
    "focus": "A focus session is running or hit a milestone. Encouraging, not saccharine.",
    "celebrate": "The user finished something. Small, dry congratulation.",
    "ambient": "Nothing is pending. Bored, mildly suspicious of the calm.",
    "sleep": "Quiet hours. Low-key, sleepy, barely awake.",
}

_BUCKET_SLOTS: dict[str, tuple[str, ...]] = {
    "todo_due_soon": ("task", "minutes"),
    "todo_annoyed": ("task", "minutes"),
    "todo_late": ("task", "minutes"),
    "todo_angry": ("task", "minutes"),
    "todo_rage": ("task", "minutes"),
    "water": ("amount", "goal"),
    "weather_hot": ("temp", "condition"),
    "weather_rain": ("temp", "condition"),
    "focus": ("minutes",),
    "celebrate": ("task",),
    "ambient": (),
    "sleep": (),
}


def slots_for(category: str) -> tuple[str, ...]:
    """Slots a template for this category may use. Unknown category -> none."""
    return _BUCKET_SLOTS.get(category, ())


def brief_for(category: str, mood: str) -> str:
    """Writing brief for a bucket. Unknown categories degrade, never fail."""
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
        max_chars=max_chars,
        slots=slot_text,
    )

    parts = [brief_for(category, mood), ""]
    if category in HUMOUR_FREE_CATEGORIES:
        # No angle list here on purpose: enumerating comedic angles is exactly
        # what we do not want for a category that comments on a user shortfall.
        parts.append(
            f"Write {count} plain variations. No jokes, no sarcasm, no commentary "
            "on the person. State the situation and stop. Vary only the wording "
            "and the sentence shape. Shorter is better."
        )
    else:
        angles = ", ".join(_ANGLES[:count])
        parts.append(
            f"Write {count} lines, one from each of these angles, in this order: {angles}."
        )
        parts.append(
            "The joke's target is always the situation or JIRI itself, never the user."
        )
    if avoid:
        listed = "\n".join(f"- {line}" for line in avoid[:40])
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

def resolve_provider(cfg: AiProviderConfig) -> tuple[str, str, str]:
    """Return (base_url, model, api_key). Raises AiError if unusable."""
    preset = PROVIDER_PRESETS.get(cfg.name, {})
    base_url = (cfg.base_url or preset.get("base_url", "")).rstrip("/")
    if not base_url:
        raise AiError(f"Provider '{cfg.name}' has no base_url and no preset")
    model = cfg.model or preset.get("default_model", "")
    if not model:
        raise AiError(f"Provider '{cfg.name}' has no model configured")
    key_env = cfg.api_key_env or preset.get("api_key_env", "")
    if not key_env:
        return base_url, model, ""
    # Accept the provider's conventional name or a JIRI_-prefixed variant.
    api_key = (os.environ.get(f"JIRI_{key_env}") or os.environ.get(key_env) or "").strip()
    if not api_key:
        raise AiError(f"Provider '{cfg.name}' needs {key_env} (or JIRI_{key_env}) in the environment")
    return base_url, model, api_key


def _chat(
    cfg: AiProviderConfig,
    messages: list[dict[str, str]],
    *,
    timeout_seconds: float,
    max_tokens: int,
    temperature: float | None = None,
) -> tuple[str, dict[str, str]]:
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
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiError(f"{cfg.name}: unexpected response shape") from exc
    return str(content or ""), rate_limit_headers(resp)


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


# --- Refill (background only) -----------------------------------------------

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
    # Over-generate and filter mechanically. Every model in this class busts
    # stated character limits and repeats itself; asking for more than we need
    # means the sanitizer can be strict without starving the bucket.
    ask_for = min(len(_ANGLES), max(count, count * 2))
    messages = build_messages(
        category, mood,
        personality=personality,
        max_chars=config.max_output_chars,
        count=ask_for,
        avoid=recent_lines(category, mood, db_path=db_path),
    )
    attempted: list[str] = []
    for provider in config.providers:
        if not provider.enabled:
            continue
        state = breaker_state(provider.name, db_path=db_path, now=current)
        if state["open"]:
            attempted.append(f"{provider.name}:breaker-open")
            continue
        for attempt in range(MAX_ATTEMPTS_PER_PROVIDER):
            try:
                raw, limits = _chat(
                    provider, messages,
                    timeout_seconds=config.timeout_seconds,
                    max_tokens=config.max_tokens,
                    temperature=config.temperature,
                )
            except (AiError, requests.RequestException) as exc:
                attempted.append(f"{provider.name}:{exc}")
                if attempt + 1 < MAX_ATTEMPTS_PER_PROVIDER:
                    delay = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * (2**attempt))
                    if sleep is not None:
                        sleep(delay + random.uniform(0, delay / 2))
                    continue
                record_failure(provider.name, db_path=db_path, now=current)
                break

            bump_usage(db_path=db_path, now=current)
            record_success(provider.name, db_path=db_path)
            candidates = [
                sanitize(part, max_chars=config.max_output_chars, allowed_slots=allowed)
                for part in raw.splitlines()
            ]
            clean = [c for c in candidates if c]
            # A template whose slots could overflow the display is rejected here,
            # not at render time when there is no way to recover.
            clean = [c for c in clean if worst_case_length(c) <= config.max_output_chars]
            stored = store_lines(
                category, mood, 0, clean,
                provider=provider.name, model=provider.model,
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
    if not config.enabled:
        return {"skipped": "disabled", "calls": 0, "stored": 0}
    if not any(p.enabled for p in config.providers):
        return {"skipped": "no-providers", "calls": 0, "stored": 0}

    used = usage_today(db_path=db_path, now=current)
    if used >= config.daily_request_cap:
        return {"skipped": "daily-cap", "calls": 0, "stored": 0, "used": used}

    ensure_schema(db_path)
    counts = bucket_counts(db_path=db_path)
    hungry = [
        (cat, mood)
        for (cat, mood) in wanted_buckets(db_path=db_path)
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
        "enabled": config.enabled,
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
