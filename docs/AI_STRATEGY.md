# AI Strategy

**Decision: no model runs on the Raspberry Pi. JIRI's wording comes from
hosted, OpenAI-compatible APIs, generated in the background into a local
cache, with built-in wording as the floor.** Closed; do not reopen on this
hardware.

This document is the record of *why*. *What* is built, its invariants and its
acceptance gates are in `docs/AI_SPEC.md`.

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
| Local AI HTTP timeout (budget at the time) | max 1 second | off by 20-60x |
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

## 2. What replaced it

- Providers, in order: FreeLLMAPI (the owner's self-hosted gateway, default
  model `qwen3.8-27b`), Google Gemini, Groq. One client speaks the
  OpenAI-compatible chat-completions shape, so a provider is a config entry
  (`PROVIDER_PRESETS` in `src/jiri/ai.py`). A LAN Ollama box would be one more
  entry.
- Requests run only on the refill worker in the web process, 15 s timeout per
  attempt, daily cap counted in SQLite before the call, consecutive-failure
  circuit breaker per provider.
- Providers write *lines* into `ai_cache`; the display only reads that table.
  There is no live rewrite and no network on the render path.
- Requests carry a category, a mood and a fixed style brief only. No user data
  is ever sent, so free tiers that may train on prompts are acceptable.

## 3. What this costs

| | Value |
| --- | --- |
| Pi CPU | effectively zero (one HTTPS request at a time, off the UI) |
| Pi RAM | a few hundred KB of cache reads |
| Money | $0 on free tiers at JIRI's volume (capped at 200 requests/day by default) |
| Latency budget | none on the render path; 15 s per background attempt |
| New dependencies | none (`requests` is already used) |
| Offline behaviour | cache, then built-in wording; always functional |

If a free tier disappears, the fix is one config edit, and the cache and
built-in layers keep the device working while you decide.

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
