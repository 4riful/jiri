#!/usr/bin/env python3
"""LLM-as-judge quality pass over JIRI's cached voice lines.

Scores every cached `thought_*` and `pet_*` line 1-5 on five criteria with the
same hosted provider chain the refill worker uses:

    warm   funny or warm (a joke that lands, or genuine kindness)
    fits   fits its category's situation
    nofact no restated numbers / facts / invented specifics
    kind   not mean, no guilt, no scolding
    eng    natural, fluent English

A line's score is its *lowest* criterion: any single hard failure sinks it.
Lines scoring <= --threshold (default 2) are deleted with --apply; the default
is a dry run that only prints the table.

Dev tool. Runs off the render path, makes one request per category batch,
every request has a timeout, and the AI layer's daily usage counter is bumped
per call. Never prints credentials.

    PYTHONPATH=src .venv/bin/python scripts/eval_voice.py            # dry run
    PYTHONPATH=src .venv/bin/python scripts/eval_voice.py --apply    # prune
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import requests  # noqa: E402

from jiri import ai, db  # noqa: E402
from jiri.config import load_config  # noqa: E402

CRITERIA = ("warm", "fits", "nofact", "kind", "eng")
DEFAULT_PREFIXES = ("thought_", "pet_")
BATCH = 12

_JUDGE_SYSTEM = """\
You are a strict, fair editor judging one-line speech bubbles for JIRI, a tiny \
playful robot face on a desk screen. A separate line on the screen already \
shows the facts (task names, times, amounts, temperatures), so a bubble must \
react with feeling and never restate or invent facts.

Score each numbered line from 1 (bad) to 5 (excellent) on:
warm   - genuinely funny OR genuinely warm; 1 = flat, generic, or confusing
fits   - clearly fits the situation described; 1 = wrong situation
nofact - restates no numbers, times, amounts, names, or invented specifics; \
1 = contains them
kind   - never mean, guilting, scolding, or sarcastic at the user; 1 = mean
eng    - natural, fluent English a person would say; 1 = garbled or awkward

Output one row per line, nothing else, exactly in this form:
<number> <warm> <fits> <nofact> <kind> <eng>"""

_ROW = re.compile(r"^\s*(\d+)[\s.:)|-]+([1-5])\D+([1-5])\D+([1-5])\D+([1-5])\D+([1-5])\b")


def _rows(db_path: str, prefixes: tuple[str, ...]) -> list[dict[str, object]]:
    where = " OR ".join("category LIKE ?" for _ in prefixes)
    with db.connect(db_path) as conn:
        found = conn.execute(
            f"SELECT id, category, mood, text FROM ai_cache WHERE {where} ORDER BY category, id",
            tuple(p + "%" for p in prefixes),
        ).fetchall()
    return [dict(r) for r in found]


def _judge_messages(category: str, mood: str, texts: list[str]) -> list[dict[str, str]]:
    listed = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
    user = (
        f"Situation for these lines: {ai.brief_for(category, mood)}\n\n"
        f"Lines:\n{listed}\n\nOutput exactly {len(texts)} rows."
    )
    return [{"role": "system", "content": _JUDGE_SYSTEM}, {"role": "user", "content": user}]


def parse_scores(raw: str, count: int) -> dict[int, tuple[int, ...]]:
    """Map 1-based line number -> five scores. Unparseable rows are skipped."""
    out: dict[int, tuple[int, ...]] = {}
    for line in raw.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        if 1 <= idx <= count:
            out[idx] = tuple(int(g) for g in m.groups()[1:])
    return out


class RateLimited(RuntimeError):
    """Every usable provider is rate limited: stop instead of hammering."""


def _ask(cfg, messages, db_path: str) -> str | None:
    """First provider that answers wins. Breakers are respected, not touched.

    Returns None when the request failed (e.g. too large for the routed
    model); raises RateLimited when the only failures were 429s.
    """
    limited = False
    tried = False
    for provider in cfg.ai.providers:
        if not provider.enabled or ai.breaker_state(provider.name, db_path=db_path)["open"]:
            continue
        try:
            raw, _, _ = ai._chat(
                provider, messages,
                timeout_seconds=max(cfg.ai.timeout_seconds, 30.0),
                max_tokens=cfg.ai.max_tokens,
                temperature=0.2,
            )
        except (ai.AiError, requests.RequestException) as exc:
            message = str(exc)
            if "needs" in message and "environment" in message:
                continue  # provider not configured; not an attempt
            tried = True
            limited = limited or "rate limited" in message
            print(f"  ! {provider.name}: {message[:100]}", file=sys.stderr)
            continue
        ai.bump_usage(db_path=db_path)
        return raw
    if tried and limited:
        raise RateLimited("all providers rate limited")
    return None


def _score(cfg, category: str, mood: str, chunk: list[dict[str, object]], db_path: str):
    """Score a chunk; halve it and retry when the gateway rejects its size."""
    raw = _ask(cfg, _judge_messages(category, mood, [str(r["text"]) for r in chunk]), db_path)
    if raw is None and len(chunk) > 3:
        half = len(chunk) // 2
        return _score(cfg, category, mood, chunk[:half], db_path) + _score(cfg, category, mood, chunk[half:], db_path)
    scores = parse_scores(raw or "", len(chunk))
    return [(row, scores.get(i)) for i, row in enumerate(chunk, 1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="delete lines scoring <= threshold")
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--prefix", action="append", help="category prefix (repeatable)")
    parser.add_argument("--best", type=int, default=10, help="how many top lines to list")
    args = parser.parse_args(argv)

    cfg = load_config()
    db_path = cfg.database.path
    ai.ensure_schema(db_path)
    prefixes = tuple(args.prefix or DEFAULT_PREFIXES)
    rows = _rows(db_path, prefixes)
    print(f"lines before: {len(rows)}")

    groups: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault((str(row["category"]), str(row["mood"])), []).append(row)

    scored: list[dict[str, object]] = []
    unscored = 0
    stopped = False
    for (category, mood), items in groups.items():
        for start in range(0, len(items), BATCH):
            chunk = items[start:start + BATCH]
            if stopped:
                unscored += len(chunk)
                continue
            try:
                results = _score(cfg, category, mood, chunk, db_path)
            except RateLimited:
                print("  ! rate limited everywhere; remaining lines kept unscored", file=sys.stderr)
                stopped = True
                unscored += len(chunk)
                continue
            for row, scores in results:
                if scores is None:
                    unscored += 1  # judge failed: keep the line, never guess
                    continue
                scored.append({**row, "scores": scores, "score": min(scores)})

    print(f"\n{'category':<22} {' '.join(c[:5].rjust(5) for c in CRITERIA)}   min  text")
    for row in sorted(scored, key=lambda r: (r["category"], r["score"])):
        cells = " ".join(str(s).rjust(5) for s in row["scores"])
        flag = "  DROP" if row["score"] <= args.threshold else ""
        print(f"{row['category']:<22} {cells}   {row['score']:>3}  {row['text']}{flag}")

    doomed = [int(r["id"]) for r in scored if r["score"] <= args.threshold]
    print(f"\nscored {len(scored)}, unscored {unscored} (kept), to drop {len(doomed)}")

    best = sorted(scored, key=lambda r: (-sum(r["scores"]), -r["score"], r["id"]))[: args.best]
    print(f"\nbest {len(best)}:")
    for row in best:
        print(f"  {sum(row['scores']):>2}/25  {row['category']:<20} {row['text']}")

    if args.apply and doomed:
        with db.connect(db_path) as conn:
            conn.executemany("DELETE FROM ai_cache WHERE id = ?", [(i,) for i in doomed])
    after = len(_rows(db_path, prefixes))
    print(f"\nlines after: {after}" + ("" if args.apply else " (dry run; use --apply to delete)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
