# AI Wording Layer — Specification

Authoritative spec for JIRI's AI feature. `docs/AI_STRATEGY.md` records *why*
the local-LLM plan was abandoned; this document defines *what is being built*
and *how it is accepted*.

Status: **specified, implementation in progress.**
Acceptance: **Stage-gated. Not accepted until Gate 3 passes on real Pi 3B+.**

---

## 1. Definition

> **JIRI's AI layer generates reusable persona line *templates* in the
> background, which the device fills in locally at render time.**

One sentence, and every word is load-bearing.

- **templates**, not finished lines — the output contains `{task}` and
  `{minutes}` placeholders, filled on-device.
- **in the background** — never on any path a user is waiting on.
- **fills in locally** — the render path is SQLite only.

### What this feature is NOT

Stated explicitly, because each of these was considered and rejected:

| Not this | Why |
| --- | --- |
| A local model running on the Pi | 20-60s per line, breaks 5 performance budgets. See `AI_STRATEGY.md` §1. |
| A live rewrite on the nudge path | Would put a network call between the user and a message, and would transmit real todo titles. Rejected in favour of templates. |
| Anything that decides *what* to say or *when* | `persona.py` owns that. AI owns wording only. |
| A required dependency | The device is fully functional with AI disabled, uninstalled, or offline. |

### The privacy property this design buys

Because JIRI generates templates rather than finished lines, **no todo title,
note, water log, location, or any other user data is ever transmitted.** The
outbound prompt contains only a category name, a mood name, and a fixed style
brief. This is a structural guarantee, not a policy promise — there is no code
path that puts user data into a request body.

This is what makes a free tier acceptable even where the provider's terms allow
training on free-tier prompts: there is nothing personal in the prompt.

---

## 2. Architecture

```text
  BACKGROUND (network allowed)          RENDER PATH (no network, ever)
  ────────────────────────────          ──────────────────────────────
  telegram poll loop, idle tick         persona.py decides the moment
            │                                     │
            ▼                                     ▼
      ai.refill()                          messages.resolve()
            │                                     │
     provider failover                      ai.line()  ── SQLite SELECT
     Groq → Gemini                                │
            │                              hit ───┴─── miss
            ▼                               │           │
      sanitize + reject                 fill slots   messages.py
            │                               │        constants
            ▼                               ▼           │
      ai_cache (SQLite) ───────────────► rendered line ◄┘
```

**The two halves never touch at runtime.** They communicate only through the
`ai_cache` table. A dead provider, an expired key, an exhausted quota, and a
pulled ethernet cable are all the same event to the render path: a cache miss.

---

## 3. Invariants

Numbered so tests can cite them. Each is written to be falsifiable.

| # | Invariant | Enforced by |
| --- | --- | --- |
| I1 | No network call is reachable from `ai.line()`, `messages.*`, `views.*`, `persona.*`, or `jiri.ui.*` | test: monkeypatch `requests` to raise, render a full frame |
| I2 | `ai.line()` returns in under 5ms on the Pi with a full cache | Gate 3 measurement |
| I3 | AI never writes any table except `ai_cache` and its own settings keys | test: assert table set before/after `refill()` |
| I4 | With AI disabled, output is byte-identical to pre-AI behaviour | test: golden strings from `messages.py` |
| I5 | Every category `persona.py` can emit has a defined bucket | test: enumerate `PersonaMoment` construction sites |
| I6 | No rendered line exceeds `max_output_chars` after slot filling | test: property test over stored templates x worst-case slots |
| I7 | Daily and hourly caps are never exceeded, including across restarts | test: caps persisted in SQLite, counted before the call |
| I8 | An unparseable, hostile, or oversized model response never reaches the display | test: sanitizer fixture suite |

**I5 is the one that was already broken.** An earlier draft hardcoded a category
list in `ai.py` that did not match `persona.py`. The fix is structural: `ai.py`
holds no category list at all.

---

## 4. Bucket taxonomy — derived, never duplicated

A cache bucket is keyed by `(category, mood)` taken **from the `PersonaMoment`
being worded**, at call time. `ai.py` must not contain a hardcoded list of
categories.

Categories `persona.py` emits today:

| Category | Mood (face state) | Slots available |
| --- | --- | --- |
| `todo_due_soon` | `alert` | `task`, `minutes` |
| `todo_annoyed` | `annoyed` | `task`, `minutes` |
| `todo_late` | `annoyed` | `task`, `minutes` |
| `todo_angry` | `angry` | `task`, `minutes` |
| `todo_rage` | `rage` | `task`, `minutes` |
| `water` | *(see code)* | `amount`, `goal` |
| `weather_hot` | `weather_hot` | `temp`, `condition` |
| `weather_rain` | `weather_rain` | `temp`, `condition` |
| `focus` | **dynamic** — `focused` or the base state when paused | `minutes` |
| `celebrate` | `happy` | `task` |
| `ambient` | *(see code)* | — |
| `sleep` | `sleeping` | — |

`focus` proves the point: its mood is computed at runtime, so no static table
can be correct. The bucket key must come from the moment.

This table is documentation, not configuration. The authority is `persona.py`,
and I5's test fails the build if the two drift.

---

## 5. Acceptance gates

House style: numbered, falsifiable, and hardware-gated where hardware is the
risk. A gate is either passed or not; "mostly working" is not passed.

### Gate 1 — Software correctness (WSL/CI)

Passes when all hold:

- [ ] `scripts/test_wsl.sh` passes with AI disabled and with AI enabled.
- [ ] I1 test: rendering a full frame with `requests` monkeypatched to raise
      produces valid output and raises nothing.
- [ ] I4 test: with `[ai].enabled = false`, every message equals the pre-AI
      deterministic string, byte for byte.
- [ ] I5 test: every category constructed in `persona.py` resolves to a bucket.
- [ ] I6 test: no stored template can exceed `max_output_chars` when every slot
      is filled with a 32-character worst case.
- [ ] Sanitizer suite: markdown, preambles, wrapping quotes, newlines, unknown
      slots, zero-width and bidi codepoints, the Unicode tag block, oversized
      output, and empty output are each rejected or folded.
- [ ] Cap test: with the daily cap set to 1, a second `refill()` in the same day
      makes zero HTTP calls. Caps survive a simulated restart.
- [ ] Breaker test: 3 consecutive provider failures open the circuit; a
      subsequent `refill()` makes zero HTTP calls to that provider.
- [ ] Failover test: primary raising 429 causes exactly one attempt on the
      secondary.

### Gate 2 — Live provider (dev machine, real keys)

- [ ] A real `refill()` against Groq stores at least 8 accepted templates for a
      bucket in one call.
- [ ] Acceptance rate (accepted / returned) is at least **60%**. Below that, the
      prompt is wrong, not the sanitizer.
- [ ] Zero user data appears in any request body. Verified by logging the exact
      outbound payload for one full refill and reading it.
- [ ] Failover to Gemini works with the Groq key deliberately invalidated.
- [ ] 100 generated templates reviewed by hand; none is offensive, none is
      nonsense, none breaks the persona voice.

### Gate 3 — Real Raspberry Pi 3B+ (hardware, blocking)

**No AI claim may be marked accepted in any document until this gate passes on
real hardware.** WSL results are preflight only. This mirrors the standard the
display and the abandoned Gemma benchmark were held to.

- [ ] `ai.line()` p95 under **5ms** with a full cache (measured, not assumed).
- [ ] UI holds **10-15 FPS** during a background `refill()`.
- [ ] Total JIRI RSS stays under **350MB** during a refill.
- [ ] CPU temperature stays under **70°C** during a refill.
- [ ] `ai_cache` at the configured maximum adds under **5MB** to the database.
- [ ] Pulling the network mid-operation produces no visible error, no stall, and
      no dropped frame.
- [ ] 24-hour soak: no unbounded growth in DB size, memory, or daily counter.

---

## 6. Test plan

| Layer | What | Where |
| --- | --- | --- |
| Unit | sanitize, render, worst_case_length, mood mapping | `tests/test_ai.py` |
| Unit | breaker open/close, cap arithmetic, day rollover | `tests/test_ai.py` |
| Contract | I5 taxonomy coverage against `persona.py` | `tests/test_ai_taxonomy.py` |
| Integration | refill with a stubbed HTTP layer, full failover matrix | `tests/test_ai.py` |
| Regression | I1 no-network render, I4 identical-with-AI-off | `tests/test_persona.py` |
| Manual | Gate 2 live provider checks | documented run |
| Hardware | Gate 3 | `scripts/measure_pi.sh` extension |

No test may make a real network call. The HTTP layer is injected.

---

## 7. Migration and rollback

**Schema.** `ai_cache` is additive — a new table, no changes to existing ones.
Schema version goes `4 → 5`. Downgrade is safe: older code ignores the table.

**Config.** The `[llm]` block is removed and `[ai]` added. An existing
`config.toml` carrying `[llm]` will fail to load with a clear
`Unknown config keys` error rather than silently ignoring it — deliberate, so
the operator notices the rename.

**Rollback.** Three levels, each independently sufficient:

1. `[ai].enabled = false` — instant, no restart of anything else, reverts to
   deterministic wording.
2. `DELETE FROM ai_cache` — drops all generated wording, keeps the feature.
3. `git revert` — the feature is additive; reverting restores prior behaviour
   with no data migration, since nothing else reads `ai_cache`.

**The backup requirement in `docs/SAFE_UPDATE_METHODOLOGY.md` applies to the
schema bump.** A verified SQLite backup is taken before migration.

---

## 8. Decision log

Recorded so these are not silently reopened.

| Decision | Rationale | Date |
| --- | --- | --- |
| No on-device inference | 20-60s/line on Pi 3B+; breaks 5 documented budgets | 2026-08-04 |
| API-driven, free tier | Zero Pi cost, zero money at JIRI's volume | 2026-08-04 |
| **Templates, not live rewrite** | Removes network from the render path entirely and makes "no user data leaves the device" structural | 2026-08-04 |
| Groq primary, Gemini fallback | Groq has a standing free tier and contractually does not train on inputs; Gemini free tier does train, which is acceptable only because we send no user data | 2026-08-04 |
| xAI Grok not used | No standing free tier as of 2026; credits only | 2026-08-04 |
| Bucket key derived from `PersonaMoment` | A duplicated category list already drifted once (I5) | 2026-08-04 |
| Reject, never truncate | A line cut mid-word is worse than the deterministic string | 2026-08-04 |
| Consecutive-failure breaker, not rate-based | At JIRI's call volume a percentage over a sliding window is statistically meaningless | 2026-08-04 |

---

## 9. Open questions

Tracked rather than hidden.

1. **Refill trigger.** Currently proposed inside the Telegram poll loop. That
   couples AI warmth to Telegram being enabled. Alternative: a small systemd
   timer. **Needs a decision before Gate 1.**
2. **Cold start.** A fresh install has an empty cache and speaks deterministic
   strings until the first refill. Acceptable, or ship a seed file of
   hand-written templates?
3. **Per-bucket quality.** Some buckets (`ambient`, `sleep`) may not benefit
   from AI variety at all. Worth measuring before spending quota on them.
