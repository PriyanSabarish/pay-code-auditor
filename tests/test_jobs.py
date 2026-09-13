"""Tests for the in-memory job store's bounded eviction (api/jobs.py).

_jobs never had anything removed from it — every audit ever created against a
long-running process stayed in memory forever, which caused a real production OOM
restart. The fix is a capped, oldest-first eviction rather than a different store
(the architecture is locked to a single in-memory dict, spec: one uvicorn worker).
"""

from __future__ import annotations

from api import jobs


def test_create_job_evicts_the_oldest_once_over_the_cap(monkeypatch):
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_resume_events", {})
    monkeypatch.setattr(jobs, "_pending_answers", {})
    monkeypatch.setattr(jobs, "MAX_STORED_JOBS", 5)

    created = [jobs.create_job(award_id="a", mode="full") for _ in range(8)]

    assert len(jobs._jobs) == 5
    # The 3 oldest (created first) were evicted; the 5 most recent remain.
    for job in created[:3]:
        assert jobs.get_job(job.audit_id) is None
    for job in created[3:]:
        assert jobs.get_job(job.audit_id) is not None


def test_eviction_cleans_up_resume_state_too(monkeypatch):
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_resume_events", {})
    monkeypatch.setattr(jobs, "_pending_answers", {})
    monkeypatch.setattr(jobs, "MAX_STORED_JOBS", 1)

    first = jobs.create_job(award_id="a", mode="full")
    jobs._resume_events[first.audit_id] = object()
    jobs._pending_answers[first.audit_id] = "some answer"

    jobs.create_job(award_id="a", mode="full")

    assert first.audit_id not in jobs._resume_events
    assert first.audit_id not in jobs._pending_answers


def test_does_not_evict_while_under_the_cap(monkeypatch):
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_resume_events", {})
    monkeypatch.setattr(jobs, "_pending_answers", {})
    monkeypatch.setattr(jobs, "MAX_STORED_JOBS", 50)

    created = [jobs.create_job(award_id="a", mode="full") for _ in range(10)]

    assert len(jobs._jobs) == 10
    for job in created:
        assert jobs.get_job(job.audit_id) is not None
