# AI Strategy

This document replaces the "run a local LLM on the Pi" plan (`docs/ROADMAP.md`
stages E and F).

**Decision: JIRI's AI dependency is fully API-driven.** No model runs on the
Raspberry Pi. Wording comes from hosted LLM APIs on free tiers, with a
deterministic fallback that guarantees JIRI never goes silent.

Status: decided, not yet implemented.

---

## 1. Why Not Local Inference On Pi 3B+

Kept as the record of why this path is closed, so it does not get reopened.

### Hardware reality

| Property | Raspberry Pi 3B+ | Raspberry Pi 5 (reference) |
| --- | --- | --- |
| CPU | 4x Cortex-A53 @ 1.4GHz (ARMv8.0-A) | 4x Cortex-A76 @ 2.4GHz (ARMv8.2-A) |
| RAM | 1GB LPDDR2, shared with VideoCore GPU | 4-16GB LPDDR4X |
| Practical memory bandwidth | roughly 1.5-2.5 GB/s | roughly 34 GB/s |
| SIMD for int8 | NEON only, no `dotprod` / `i8mm` | `dotprod` + `i8mm` |
| Storage | microSD (swap is punishing) | NVMe possible |

Token generation is memory-bandwidth bound — every token streams the whole
quantized model through the CPU. The Pi 3B+ has roughly one fifteenth of a
Pi 5's bandwidth and lacks the ARMv8.2 dot-product instructions llama.cpp's fast
quantized kernels rely on, so it falls back to slower generic NEON paths.

### Published throughput, smallest useful model

Gemma 3 270M Q4_K_M (roughly 300MB on disk):

| Device | Generation speed |
| --- | --- |
| Raspberry Pi 5 | roughly 22 tok/s |
| Raspberry Pi 4 (8GB) | roughly 3-6 tok/s |
| **Raspberry Pi 3B+ (extrapolated)** | **roughly 1-3 tok/s** |

The Pi 3B+ figure is extrapolated, not measured, and is the optimistic end.
Adding prefill for a 200-400 token prompt, a single 40-token rewrite costs
roughly **20-60 seconds with all four cores at 100%**.

### Collision with JIRI's own budgets

| Budget (`docs/PERFORMANCE_BUDGETS.md`) | Value | Local LLM outcome |
| --- | --- | --- |
| Local AI HTTP timeout | max 1 second | off by 20-60x |
| Total JIRI memory without LLM | under 350MB | +300MB model on a 1GB board means SD swap |
| UI target FPS | 10-15 FPS | saturated cores starve the Pygame loop |
| CPU idle average | under 15%, hard limit 30% | 100% across all cores per rewrite |

The project already wrote down a requirement no on-device model on this board
can meet. Add thermal throttling on a passively cooled 3B+ and SD swap thrash,
and local inference is a stability risk to an always-on device.

Separately: a 270M model is a weaker writer than the hand-written strings in
`src/jiri/messages.py`. Spending 40 seconds and 100% CPU to make the prose worse
is a bad trade.

**Closed. Do not reopen without different hardware.**

---

## 2. Architecture

Three layers. Only layer 1 is required for JIRI to function.

```text
Layer 1  Deterministic core                  always, already built
         persona.py decides WHAT to say and WHEN
         messages.py provides baseline wording
                  |
Layer 2  Response cache (SQLite)             always, offline-safe
         recent AI lines, reused when the network is unavailable
                  |
Layer 3  Hosted LLM API                      network, free tier, capped
         Groq / Gemini / any OpenAI-compatible endpoint
         2s timeout, background only, silent fallback
```

Read it bottom-up at runtime: try the API, fall back to the cache, fall back to
deterministic. Every failure is invisible to the user.

Invariants that do not change:

- **No AI on the Pygame frame loop.** Ever. Background worker only.
- **AI cannot write SQLite state, run commands, complete todos, change due
  dates, or own any state.** It returns a string. That is the entire contract.
- **JIRI is never worse than it is today**, at any layer, in any failure mode.

---

## 3. Providers

### One client, many providers

Groq, xAI, Gemini, OpenAI, OpenRouter, and a LAN Ollama box all speak the
**OpenAI-compatible `/v1/chat/completions`** shape. Build one client against
that shape with per-provider presets, and provider choice becomes configuration
rather than code.

| Provider | Base URL | Free tier |
| --- | --- | --- |
| Groq | `https://api.groq.com/openai/v1` | yes — roughly 1000 req/day/model, 30 RPM, 6000 TPM |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | yes — roughly 1500 req/day, 15 RPM, no card |
| xAI (Grok) | `https://api.x.ai/v1` | credits-based, **not a standing free tier** |
| LAN Ollama | `http://<host>:11434/v1` | free, needs a machine on |

> **"Grok" vs "Groq" — these are different companies.** Groq is the fast-inference
> provider with the standing free tier. Grok is xAI's model family, which bills
> against credits. Both work with the same client code, but only Groq is free
> without a card. All third-party limits change frequently — verify against
> current provider docs before relying on any number above.

### Failover chain

Configure an ordered list. On timeout, 429, or 5xx, advance to the next entry;
on exhaustion, fall through to the cache.

```toml
[[ai.providers]]
name = "groq"
base_url = "https://api.groq.com/openai/v1"
model = "llama-3.3-70b-versatile"
api_key_env = "JIRI_GROQ_API_KEY"

[[ai.providers]]
name = "gemini"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
model = "gemini-2.0-flash"
api_key_env = "JIRI_GEMINI_API_KEY"
```

Two free providers in the chain means a rate-limited or degraded provider costs
nothing but a retry.

### Privacy — decide this deliberately

Persona rewrites include real todo titles. Those leave the device.

Google's terms permit training on **free-tier** prompts (the paid tier and
Vertex AI do not). If your todos are personal, that is a real consideration, not
a footnote. Three ways to handle it, pick one:

1. **Accept it.** Fine for "buy milk", less fine for anything sensitive.
2. **Abstract the prompt.** Send structure, not content: *"a high-priority task
   is 45 minutes overdue"* instead of the title. The rewrite cannot name the
   task, which costs some personality.
3. **Per-todo opt-out.** A `private` flag on todos; private ones never reach an
   API and always use deterministic wording.

Option 3 is the right long-term answer and is cheap to add later. Start with 1
or 2 and a clear-eyed decision, not a default.

---

## 4. Runtime Rules

Non-negotiable, because this is a always-on device on someone's desk.

| Rule | Value |
| --- | --- |
| Timeout | 2 seconds hard, per provider attempt |
| Execution context | background worker only, never the UI process |
| Daily request cap | enforced in SQLite, default 200, counted before the call |
| Rate-limit handling | 429 advances the failover chain, then backs off for the rest of the hour |
| Default state | `[ai].enabled = false` — opt-in, with an admin toggle |
| Failure behavior | silent; log it, serve cache or deterministic text, never surface an error to the display |
| API keys | environment variables or DB settings, never in Git |
| Output validation | length-capped, stripped of newlines/markdown before it reaches the 160-char display |

That last row matters more than it looks. A model returning 400 characters of
markdown into a typed-mouth renderer with a 160-character cap is a display bug,
not an AI feature. Validate and reject; on rejection, fall back.

---

## 5. Response Cache

The cache is what makes "fully API-driven" safe on an offline-capable device.

```sql
CREATE TABLE ai_cache (
  id INTEGER PRIMARY KEY,
  category TEXT NOT NULL,       -- idle, reminder, hydration, weather, focus, milestone
  mood TEXT NOT NULL,
  angry_level INTEGER,
  text TEXT NOT NULL,           -- validated, length-capped output
  provider TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  use_count INTEGER NOT NULL DEFAULT 0
);
```

Behavior:

- Every accepted API response is written here.
- Offline, rate-limited, or capped: serve from cache, ordered by
  `last_used_at ASC` so repeats are maximally spaced.
- Bounded: keep the most recent N per (category, mood), prune the rest. Ties
  into the existing cleanup policy and the under-50MB database target.
- Empty cache plus no network: `messages.py` deterministic strings. Exactly
  today's behavior, which is a working product.

After a week of normal use the cache holds enough variety that an offline day is
barely noticeable. This is the entire offline story, and it costs one table.

---

## 6. Implementation Plan

### Phase 1: Client and config

1. **`src/jiri/ai.py`** — new. OpenAI-compatible client: provider list, ordered
   failover, 2s timeout, daily cap check against SQLite, output validation.
   Pure `requests`, no new dependency.
2. **`config.example.toml`** — replace the `[llm]` block:

   ```toml
   [ai]
   enabled = false
   timeout_seconds = 2
   daily_request_cap = 200
   max_output_chars = 160

   # [[ai.providers]] entries as shown in section 3
   ```

3. **Env vars** — `JIRI_GROQ_API_KEY`, `JIRI_GEMINI_API_KEY`. Document in the
   README env table alongside the Telegram seeds.

### Phase 2: Cache and wiring

4. **`ai_cache` migration** in `src/jiri/db.py`.
5. **`src/jiri/messages.py`** — add a resolver that tries AI, then cache, then
   the existing constants. The existing functions stay as the floor and keep
   their current signatures.
6. **Wire into the Telegram worker and persona nudge path only.** Not the UI
   frame loop. `persona.py` decisions stay deterministic — AI only rewords the
   result.

### Phase 3: Admin and observability

7. Replace the AI status page: provider health, today's request count against
   the cap, cache size per category, last error, enable/disable toggle, and a
   "test prompt" button.
8. Log every call outcome (provider, latency, status) so a degrading free tier
   is visible before it becomes a mystery.

### Phase 4: Remove the local-LLM scaffolding

- **`src/jiri/llama.py`** — delete. Process control (`llama_start`,
  `llama_stop`, `llama_logs`, `_find_pid_on_port`, `_extract_model_name`,
  `_process_uptime`) is meaningless once nothing runs locally. A LAN Ollama box,
  if ever wanted, is just another `[[ai.providers]]` entry pointing at
  `http://host:11434/v1` — no process management needed.
- **Scripts** — delete `ai_baseline.sh`, `ai_benchmark_gemma.sh`,
  `ai_common.sh`, `ai_monitor.sh`, `ai_run_gemma_512.sh`, `ai_safe_debloat.sh`.
  The debloat script existed to free RAM for a model that is not coming.
- **`tests/test_ai_scripts.py`** — replace with tests for `ai.py`: failover
  order, timeout, cap enforcement, output validation, cache fallback.
- **`docs/PERFORMANCE_BUDGETS.md`** — "Local AI HTTP timeout: max 1 second"
  becomes "AI API timeout: max 2 seconds, background only"; add "AI cache
  lookup: under 5ms".
- **`docs/ROADMAP.md`** — stage E becomes "AI API Client", stage F becomes
  "AI Integration"; drop the Gemma benchmark blockers.
- **`README.md`** — the Local AI row, the Local AI Notes section, the
  `JIRI_LLM_*` env rows, and the `llama.py` line in the file tree. The system
  map's `JIRI Runtime -> local llama-server` becomes
  `JIRI Runtime -> AI API (free tier) -> cache -> deterministic`.

---

## 7. What This Costs

| | Value |
| --- | --- |
| Pi CPU | zero |
| Pi RAM | a few hundred KB for the cache reads |
| Money | $0 on Groq + Gemini free tiers at JIRI's volume |
| Latency budget | 2s, off the critical path, invisible on failure |
| New dependencies | none (`requests` is already used) |
| Offline behavior | cache, then deterministic — always functional |

JIRI's realistic volume is roughly 30-150 rewrites/day. Groq alone
(roughly 1000/day) covers that with an order of magnitude of headroom, and
Gemini is the second chain entry.

If a free tier disappears, the fix is one config edit — or nothing at all, since
the cache and deterministic layers keep the device working while you decide.

---

## Sources

- [Gemma 3 on Raspberry Pi 5: Real Benchmarks (2026)](https://www.kunalganglani.com/blog/gemma-3-raspberry-pi-5-benchmark)
- [Running LLMs on Raspberry Pi 5: A Practical Guide with Real Benchmarks](https://tinyweights.dev/posts/run-llms-raspberry-pi-5/)
- [Raspberry Pi 5 LLM Benchmarks (2026): 12 Models, Real Tokens/Sec](https://localaimaster.com/blog/llm-raspberry-pi-5)
- [LLMs on a Budget: Testing Serving Frameworks on the Raspberry Pi 4](https://medium.com/@thomasnahon/llms-on-a-budget-testing-serving-frameworks-on-the-raspberry-pi-4-5fc56623840e)
- [LLMPi: Optimizing LLMs for High-Throughput on Raspberry Pi (arXiv)](https://arxiv.org/html/2504.02118v1)
- [Free LLM APIs in 2026: Real Free Tiers, Rate Limits](https://speedmvps.com/blog/free-llm-api-2026)
- [Gemini API Free Tier 2026: Limits, Quotas](https://pecollective.com/tools/gemini-free-tier-guide/)
- [Free LLM API Tiers in 2026: Groq, Cerebras, Mistral & More](https://ianlpaterson.com/blog/free-llm-api-2026/)
