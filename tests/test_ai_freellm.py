"""FreeLLMAPI provider, lenient parsing, .env loader, and refill worker.

No test here makes a real network call: `requests.post` is replaced.
"""

from __future__ import annotations

import os
import threading

import pytest

from jiri import ai, ai_worker, db
from jiri.config import AiConfig, AiProviderConfig, load_env_file


def _db(tmp_path):
    path = str(tmp_path / "jiri.db")
    db.init_db(path)
    ai.ensure_schema(path)
    return path


@pytest.fixture
def freellm_env(monkeypatch):
    for name in ("FREELLM_BASE_URL", "FREELLM_API_KEY", "FREELLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"JIRI_{name}", raising=False)
    monkeypatch.setenv("FREELLM_BASE_URL", "https://llm.example.test/")
    monkeypatch.setenv("FREELLM_API_KEY", "test-key")
    return monkeypatch


class _Resp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
        self.headers = {}

    def json(self):  # pragma: no cover - must not be used
        raise AssertionError("_chat must parse leniently, not via resp.json()")


# --- Preset resolution ------------------------------------------------------

def test_freellm_resolves_from_env_and_appends_v1(freellm_env):
    base, model, key = ai.resolve_provider(AiProviderConfig(name="freellm"))
    assert base == "https://llm.example.test/v1"
    assert model == "qwen3.8-27b"
    assert key == "test-key"


def test_freellm_keeps_existing_v1_and_reads_model_env(freellm_env):
    freellm_env.setenv("FREELLM_BASE_URL", "https://llm.example.test/v1")
    freellm_env.setenv("JIRI_FREELLM_MODEL", "other-model")
    base, model, _ = ai.resolve_provider(AiProviderConfig(name="freellm"))
    assert base == "https://llm.example.test/v1"
    assert model == "other-model"


def test_freellm_jiri_prefixed_base_url(freellm_env):
    freellm_env.delenv("FREELLM_BASE_URL")
    freellm_env.setenv("JIRI_FREELLM_BASE_URL", "http://lan:8080")
    base, _, _ = ai.resolve_provider(AiProviderConfig(name="freellm"))
    assert base == "http://lan:8080/v1"


def test_freellm_without_base_url_is_not_ready(freellm_env):
    freellm_env.delenv("FREELLM_BASE_URL")
    with pytest.raises(ai.AiError, match="FREELLM_BASE_URL"):
        ai.resolve_provider(AiProviderConfig(name="freellm"))


# --- Lenient parsing and empty content --------------------------------------

def test_chat_parses_raw_newlines_inside_json_strings(freellm_env, monkeypatch):
    # Literal newlines inside the string: invalid strict JSON, as the gateway sends it.
    body = '{"choices":[{"message":{"content":"First line here.\nSecond line here."}}]}'
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["auth"] = kwargs["headers"]["Authorization"]
        seen["timeout"] = kwargs["timeout"]
        return _Resp(body)

    monkeypatch.setattr(ai.requests, "post", fake_post)
    text, _, model = ai._chat(AiProviderConfig(name="freellm"), [], timeout_seconds=5, max_tokens=50)
    assert text.splitlines() == ["First line here.", "Second line here."]
    assert model == "qwen3.8-27b"
    assert seen["url"] == "https://llm.example.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["timeout"] == 5


def test_empty_content_is_a_failure_and_fails_over(tmp_path, freellm_env, monkeypatch):
    path = _db(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "llm.example.test" in url:
            return _Resp('{"choices":[{"message":{"content":""}}]}')
        return _Resp('{"choices":[{"message":{"content":"The desk is suspiciously calm."}}]}')

    monkeypatch.setattr(ai.requests, "post", fake_post)
    cfg = AiConfig(providers=(AiProviderConfig(name="freellm"), AiProviderConfig(name="groq")))
    result = ai.generate("ambient", "idle", config=cfg, personality="playful", db_path=path)
    assert result["ok"] is True
    assert result["provider"] == "groq"
    assert any("empty content" in a for a in result["attempted"])
    assert ai.breaker_state("freellm", db_path=path)["failures"] == 1
    assert ai.line("ambient", "idle", db_path=path) == "The desk is suspiciously calm."


def test_refill_seeds_known_buckets_when_nothing_is_wanted(tmp_path, freellm_env, monkeypatch):
    path = _db(tmp_path)
    monkeypatch.setattr(
        ai.requests, "post",
        lambda url, **kw: _Resp('{"choices":[{"message":{"content":"A perfectly quiet desk today."}}]}'),
    )
    cfg = AiConfig(providers=(AiProviderConfig(name="freellm"),))
    result = ai.refill(config=cfg, db_path=path, max_buckets=1)
    assert result["calls"] == 1
    assert result["results"][0]["category"] == ai.seed_buckets()[0][0]


# --- .env loader -------------------------------------------------------------

def test_env_loader_parses_and_never_overrides(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\n"
        "JIRI_T_PLAIN=abc\n"
        'JIRI_T_DQ="quoted value"\n'
        "export JIRI_T_SQ='single'\n"
        "JIRI_T_SET=from-file\n"
        "not a line\n",
        encoding="utf-8",
    )
    for name in ("JIRI_T_PLAIN", "JIRI_T_DQ", "JIRI_T_SQ"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JIRI_T_SET", "from-shell")
    applied = load_env_file(env_file)
    assert os.environ["JIRI_T_PLAIN"] == "abc"
    assert os.environ["JIRI_T_DQ"] == "quoted value"
    assert os.environ["JIRI_T_SQ"] == "single"
    assert os.environ["JIRI_T_SET"] == "from-shell"
    assert "JIRI_T_SET" not in applied
    for name in ("JIRI_T_PLAIN", "JIRI_T_DQ", "JIRI_T_SQ"):
        monkeypatch.delenv(name)


def test_env_loader_missing_file_is_noop(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == {}


# --- Worker -------------------------------------------------------------------

def test_worker_runs_and_stops():
    ran = threading.Event()

    def refill():
        ran.set()
        raise RuntimeError("boom")  # must be swallowed

    worker = ai_worker.AiRefillWorker(refill, interval_seconds=3600, initial_delay_seconds=0)
    worker.start()
    assert ran.wait(2)
    assert worker.running
    worker.stop(timeout=2)
    assert not worker.running
    assert worker.runs == 1


def test_worker_disabled_when_interval_zero():
    class _Rt:
        class config:
            class ai:
                refill_interval_minutes = 0

    assert ai_worker.start_for_runtime(_Rt()) is None


def test_413_compacts_prompt_and_retries(monkeypatch, tmp_path):
    from jiri import ai, db
    from jiri.config import AiConfig, AiProviderConfig

    db_path = str(tmp_path / "j.db")
    db.init_db(db_path)
    ai.ensure_schema(db_path)
    monkeypatch.setenv("FREELLM_BASE_URL", "https://gw.example")
    monkeypatch.setenv("FREELLM_API_KEY", "k")
    seen = []

    class Resp:
        def __init__(self, code, text):
            self.status_code, self.text, self.headers = code, text, {}

        def json(self):
            import json
            return json.loads(self.text)

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.append((json["max_tokens"], "Already in use" in json["messages"][1]["content"]))
        if len(seen) == 1:
            return Resp(413, '{"error":{"message":"too large"}}')
        return Resp(200, '{"choices":[{"message":{"content":"A small robot sighs.\\nThe desk hums along."}}]}')

    monkeypatch.setattr(ai.requests, "post", fake_post)
    ai.store_lines("ambient", "idle", 0, ["Old line one here."], provider="x", model="m", db_path=db_path)
    cfg = AiConfig(providers=(AiProviderConfig(name="freellm"), AiProviderConfig(name="gemini")))
    result = ai.generate("ambient", "idle", config=cfg, personality="playful", db_path=db_path)
    assert result["stored"] >= 1
    assert seen[0][1] is True and seen[1] == (160, False)   # history dropped, smaller budget
    assert any("gemini:not-configured" in a for a in result.get("attempted", [])) or result["provider"] == "freellm"
