## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- Link the issue if there is one: Fixes #123 -->

## How it was tested

<!-- Commands you actually ran, and what happened. "scripts/test_wsl.sh passes" is the sentence we look for. -->

```text

```

## Checklist

- [ ] `.venv/bin/python -m pytest tests/ -q` passes
- [ ] `scripts/test_wsl.sh` passes (the full gate, tests plus CLI walkthrough)
- [ ] New behaviour has a test or a documented smoke check
- [ ] No network call is reachable from the render path (`ai.line`, `messages.*`, `views.*`, `persona.*`, `jiri.ui.*`)
- [ ] No writes to SQLite from the UI frame loop
- [ ] Every new network request has a timeout and an offline fallback
- [ ] Performance budgets in `docs/PERFORMANCE_BUDGETS.md` still hold
- [ ] No new dependency, or the pull request explains why one is needed
- [ ] No secrets, tokens, or API keys in any committed file
- [ ] Docs updated if behaviour or setup changed

## Pi impact

<!-- Delete if this is docs-only. -->

- [ ] Tested on a Raspberry Pi 3B/3B+
- [ ] Not tested on hardware, and here is why that is safe:

## Schema changes

<!-- Delete if you did not touch the database. -->

- [ ] Schema version bumped and the migration is additive
- [ ] Rollback path described below
- [ ] `docs/SAFE_UPDATE_METHODOLOGY.md` backup step still applies
