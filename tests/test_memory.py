"""Unit tests for per-bookkeeper memory (spec 6.5). Always uses an explicit tmp_path —
never the real default store — so tests never read or write real data."""

from __future__ import annotations

from auditor.memory import BookkeeperMemory, normalise_code_pattern


def test_normalise_code_pattern_collapses_near_identical_codes():
    assert normalise_code_pattern("RDO_Payout-2026") == normalise_code_pattern("rdo   payout 2026")
    assert normalise_code_pattern("RDO PAYOUT") == "RDO PAYOUT"
    assert normalise_code_pattern("  Site  Allow!! ") == "SITE ALLOW"


def test_remember_then_recall_round_trips(tmp_path):
    store = BookkeeperMemory(tmp_path / "memory.json")
    store.remember("bk1", "RDO PAYOUT", "Ordinary time or overtime?", "Ordinary time.")
    found = store.recall("bk1", "RDO PAYOUT")
    assert found is not None
    assert found.answer == "Ordinary time."
    assert found.question == "Ordinary time or overtime?"
    assert found.bookkeeper_id == "bk1"


def test_recall_matches_a_differently_formatted_code(tmp_path):
    store = BookkeeperMemory(tmp_path / "memory.json")
    store.remember("bk1", "RDO PAYOUT", "q", "in service")
    found = store.recall("bk1", "rdo_payout")
    assert found is not None
    assert found.answer == "in service"


def test_recall_returns_none_for_unknown_code(tmp_path):
    store = BookkeeperMemory(tmp_path / "memory.json")
    assert store.recall("bk1", "SOMETHING ELSE") is None


def test_memory_is_scoped_per_bookkeeper(tmp_path):
    store = BookkeeperMemory(tmp_path / "memory.json")
    store.remember("bk1", "RDO PAYOUT", "q", "bk1's answer")
    assert store.recall("bk2", "RDO PAYOUT") is None
    assert store.recall("bk1", "RDO PAYOUT").answer == "bk1's answer"


def test_remembering_again_replaces_the_stale_answer_not_accumulates(tmp_path):
    store = BookkeeperMemory(tmp_path / "memory.json")
    store.remember("bk1", "RDO PAYOUT", "q1", "first answer")
    store.remember("bk1", "RDO PAYOUT", "q2", "second answer")
    assert store.recall("bk1", "RDO PAYOUT").answer == "second answer"
    assert len(store._entries) == 1


def test_persists_to_disk_and_reloads_in_a_fresh_instance(tmp_path):
    path = tmp_path / "memory.json"
    BookkeeperMemory(path).remember("bk1", "RDO PAYOUT", "q", "persisted answer")
    reloaded = BookkeeperMemory(path)
    found = reloaded.recall("bk1", "RDO PAYOUT")
    assert found is not None
    assert found.answer == "persisted answer"


def test_stored_record_never_contains_more_than_pay_code_context():
    """Regression guard: the schema itself has no room for employee-level fields —
    this pins the exact field set so an accidental addition doesn't slip through."""

    from dataclasses import fields

    field_names = {f.name for f in fields(__import__("auditor.memory", fromlist=["RememberedAnswer"]).RememberedAnswer)}
    assert field_names == {"bookkeeper_id", "code_pattern", "question", "answer", "stored_at"}
