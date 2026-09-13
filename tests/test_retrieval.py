"""Tests for hybrid retrieval, run against the fixture chunks (data/fixtures/chunks_sample.jsonl).

Uses the real fastembed model rather than a mock: it's local and free, unlike the Groq
calls in test_classify.py, so there's no reason not to test the real embedding behaviour.
"""

from __future__ import annotations

import pytest

from auditor.retrieval import (
    DEFAULT_CHUNKS_PATH,
    FIXTURE_CHUNKS_PATH,
    KnowledgeBase,
    _reciprocal_rank_fusion,
    get_knowledge_base,
    load_chunks,
    search_award,
    search_ato_guidance,
)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase.from_jsonl(FIXTURE_CHUNKS_PATH)


def test_load_chunks_reads_every_line():
    chunks = load_chunks(FIXTURE_CHUNKS_PATH)
    assert len(chunks) > 20
    ids = {c.id for c in chunks}
    assert "S1-T09-R01" in ids  # overtime
    assert "S4-cl.20.2" in ids  # award allowance clause


def test_chunk_to_citation_round_trips_fields():
    chunks = load_chunks(FIXTURE_CHUNKS_PATH)
    overtime = next(c for c in chunks if c.id == "S1-T09-R01")
    citation = overtime.to_citation()
    assert citation.source == overtime.source
    assert citation.reference == overtime.reference
    assert citation.text == overtime.text
    assert citation.url == overtime.url


def test_search_finds_overtime_rule(kb: KnowledgeBase):
    results = kb.search("does overtime count towards super", top_k=3)
    ids = [c.id for c in results]
    assert "S1-T09-R01" in ids


def test_search_finds_site_allowance_rule(kb: KnowledgeBase):
    results = kb.search("allowance for working in adverse heat conditions", top_k=5)
    ids = [c.id for c in results]
    assert "S1-T08-R02" in ids


def test_search_distinguishes_rdo_in_service_from_termination(kb: KnowledgeBase):
    """The exact ambiguity Data's research flagged: two different rows govern the same
    code name depending on how it was paid. Both should be retrievable."""

    in_service = kb.search("cash out RDO while still employed", top_k=5)
    termination = kb.search("unused RDO paid out on termination", top_k=5)
    assert "S1-T06-R01" in [c.id for c in in_service]
    assert "S1-T13-R01" in [c.id for c in termination]


def test_category_filter_restricts_to_ato_guidance(kb: KnowledgeBase):
    results = kb.search("overtime", top_k=10, category="ato_guidance")
    assert all(c.category == "ato_guidance" for c in results)
    assert len(results) > 0


def test_category_filter_restricts_to_award(kb: KnowledgeBase):
    results = kb.search("ordinary hours span", top_k=10, category="award")
    assert all(c.category == "award" for c in results)
    assert len(results) > 0


def test_search_award_only_returns_award_citations():
    citations = search_award("adverse conditions allowance", path=str(FIXTURE_CHUNKS_PATH))
    assert citations
    assert all("Hospitality" in c.source for c in citations)


def test_search_ato_guidance_only_returns_ato_citations():
    citations = search_ato_guidance("commission payment", path=str(FIXTURE_CHUNKS_PATH))
    assert citations
    assert all("ATO" in c.source for c in citations)


def test_get_knowledge_base_is_cached():
    kb1 = get_knowledge_base(str(FIXTURE_CHUNKS_PATH))
    kb2 = get_knowledge_base(str(FIXTURE_CHUNKS_PATH))
    assert kb1 is kb2


def test_reciprocal_rank_fusion_favours_items_ranked_highly_in_both():
    # index 0 is top in both rankings; index 5 only appears in the second ranking.
    keyword_ranking = [0, 1, 2, 3, 4]
    embedding_ranking = [0, 2, 1, 4, 3, 5]
    fused = _reciprocal_rank_fusion([keyword_ranking, embedding_ranking])
    assert fused[0] == 0
    assert 5 in fused  # present even though only one ranking saw it


def test_search_on_empty_knowledge_base_returns_nothing():
    empty_kb = KnowledgeBase([])
    assert empty_kb.search("anything", top_k=3) == []


# --- Data's real chunks.jsonl (67 ATO table rows, landed on the data branch) ---------


def test_default_chunks_path_now_resolves_to_the_real_file():
    # Once this fails, Data's file has moved or been renamed — update DEFAULT_CHUNKS_PATH.
    assert DEFAULT_CHUNKS_PATH.exists()


def test_load_chunks_handles_datas_real_ato_table_row_format():
    chunks = load_chunks(DEFAULT_CHUNKS_PATH)
    assert len(chunks) == 67
    rdo_in_service = next(c for c in chunks if c.id == "S1-T06-R04")
    assert rdo_in_service.qualifying_earnings is True
    assert rdo_in_service.category == "ato_guidance"
    assert rdo_in_service.source == "ATO qualifying earnings page"
    assert "rostered days off" in rdo_in_service.text.lower()


def test_real_chunk_to_citation_handles_full_iso_datetime():
    # Data's real chunks carry retrieved_utc as a full ISO datetime (with a time
    # component); Citation.retrieved_date is a plain date, which pydantic rejects
    # unless truncated first. Regression test for that exact failure.
    chunks = load_chunks(DEFAULT_CHUNKS_PATH)
    citation = chunks[0].to_citation()
    assert citation.retrieved_date is not None
    assert str(citation.retrieved_date) == "2026-09-12"

    rdo_on_termination = next(c for c in chunks if c.id == "S1-T13-R04")
    assert rdo_on_termination.qualifying_earnings is False


def test_real_knowledge_base_distinguishes_rdo_scenarios():
    real_kb = KnowledgeBase.from_jsonl(DEFAULT_CHUNKS_PATH)
    in_service = real_kb.search("cash out rostered day off while still employed", top_k=5)
    termination = real_kb.search("unused rostered day off paid on termination", top_k=5)
    assert "S1-T06-R04" in [c.id for c in in_service]
    assert "S1-T13-R04" in [c.id for c in termination]


def test_real_knowledge_base_has_no_award_chunks_yet():
    # True as of this commit — Data hasn't chunked the award (S4) yet. If this starts
    # failing, great: it means award-aware retrieval just got real citations for free.
    real_kb = KnowledgeBase.from_jsonl(DEFAULT_CHUNKS_PATH)
    assert real_kb.search("ordinary hours", top_k=5, category="award") == []
