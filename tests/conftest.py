"""Pins test-only environment settings before anything else imports api.config.

FAKE_DATA in particular must never leak in from a developer's local .env — api/config.py
calls load_dotenv(), which by default won't override an already-set env var, so setting
it here first keeps the suite deterministic and free regardless of whatever a developer
has locally set for manual browser testing.

Same reasoning for LLM_PROVIDER: test_llm.py's tests are Groq-specific (they monkeypatch
the Groq client) and would silently route through the Gemini path instead — passing
without testing anything — if a developer's local .env has LLM_PROVIDER=gemini set for
manual testing. Pinning "groq" here keeps them deterministic; test_llm_gemini.py
monkeypatches llm.LLM_PROVIDER directly so it's unaffected either way.
"""

import os

os.environ["FAKE_DATA"] = "1"
os.environ["LLM_PROVIDER"] = "groq"

import pytest

from auditor import memory as _memory_module


@pytest.fixture(autouse=True)
def isolated_bookkeeper_memory(tmp_path, monkeypatch):
    """Every test gets its own empty, throwaway memory store. Without this, tests share
    the real process-global singleton (and its file persisted across runs at
    var/bookkeeper_memory.json) — one test's remembered answer then silently changes
    another test's behaviour, which is exactly how a mocked investigate() that always
    returns the same "awaiting_input" outcome turned into a genuine infinite loop the
    first time this was wired up."""

    fresh = _memory_module.BookkeeperMemory(tmp_path / "test_bookkeeper_memory.json")
    monkeypatch.setattr(_memory_module, "_default_memory", fresh)
    yield fresh
