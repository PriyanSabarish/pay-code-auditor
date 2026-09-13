"""Award-aware hybrid retrieval (spec section 6.2, hours 7-10).

Combines BM25 keyword search (exact terms like "leading hand allowance") with local
embedding search (meaning) via Reciprocal Rank Fusion — robust to the two systems scoring
on completely different scales, with no weight to tune.

The chunks.jsonl contract (Data owns auditor/knowledge/, this module just consumes it)
-----------------------------------------------------------------------------------
`load_chunks()` accepts two record shapes, one JSON object per line:

1. Data's real format (auditor/knowledge/chunks.jsonl, ATO table rows):
    {
      "chunk_id": "S1-T08-R03", "source_id": "S1",
      "table_number": 8, "table_name": "Allowances", "row_number": 3,
      "payment_type": "the actual passage",
      "ordinary_time_earnings": true|false|null, "qualifying_earnings": true|false,
      "url": "https://...", "retrieved_utc": "2026-09-12T14:16:07+00:00"
    }
   `category` isn't given explicitly — it's inferred from source_id (S1-S3 -> ato_guidance,
   S4 -> award), and `source`/`reference` are built from the table/source labels below.

2. This module's own generic format (used by the test fixture, and by any future award
   chunks until Data's build_chunks.py covers them too):
    {
      "id": "S4-cl.20.2", "category": "ato_guidance"|"award",
      "source": "...", "reference": "...", "text": "...",
      "url": "https://...", "retrieved_date": "2026-09-12"
    }

Both normalise to the same KnowledgeChunk, so nothing downstream needs to know which
shape a given line was.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

import numpy as np
from fastembed import TextEmbedding
from rank_bm25 import BM25Okapi

from .schemas import Citation

ChunkCategory = Literal["ato_guidance", "award"]

DEFAULT_CHUNKS_PATH = Path(__file__).resolve().parent / "knowledge" / "chunks.jsonl"
FIXTURE_CHUNKS_PATH = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "chunks_sample.jsonl"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Matches the source labels in auditor/knowledge/sources.md, for whichever chunk records
# only carry a source_id rather than a human-readable source name.
SOURCE_LABELS = {
    "S1": "ATO qualifying earnings page",
    "S2": "ATO Law Companion Ruling LCR 2026/D1",
    "S3": "ATO SGR 2009/2 (ordinary time earnings)",
    "S4": "Hospitality Industry (General) Award MA000009",
}
AWARD_SOURCE_IDS = {"S4"}

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common Australian payroll pay-code acronyms. Chunk text (both the fixture and the real
# ATO table rows) is written out in full ("rostered days off"), never as an acronym, and
# neither BM25 nor a small embedding model reliably bridges that gap on its own — a query
# of just "RDO PAYOUT" retrieved nothing about rostered days off at all until this existed.
_ACRONYM_EXPANSIONS = {
    "rdo": "rostered day off",
    "ot": "overtime",
    "piln": "payment in lieu of notice",
    "toil": "time off in lieu",
    "ppl": "parental leave pay",
    "al": "annual leave",
    "lsl": "long service leave",
    "cas": "casual",
    "comm": "commission",
    "dir": "director",
    "ord": "ordinary",
    "hrs": "hours",
    "pen": "penalty",
    "allow": "allowance",
}
_ACRONYM_RE = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in _ACRONYM_EXPANSIONS) + r")\b", re.IGNORECASE
)


def expand_query(text: str) -> str:
    """Expand known payroll acronyms so retrieval can match spelled-out chunk text.
    Appends expansions rather than replacing, so exact-acronym keyword hits still work."""

    expansions = {m.group(0).lower() for m in _ACRONYM_RE.finditer(text)}
    if not expansions:
        return text
    return text + " " + " ".join(_ACRONYM_EXPANSIONS[e] for e in expansions)


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    category: ChunkCategory
    source: str
    reference: str
    text: str
    url: Optional[str] = None
    retrieved_date: Optional[str] = None
    # Ground truth from the ATO page's own two columns, when the source carries them
    # (Data's finding: OTE and QE are separate verdicts, not one — see sources.md).
    qualifying_earnings: Optional[bool] = None
    ordinary_time_earnings: Optional[bool] = None

    def to_citation(self) -> Citation:
        return Citation(
            source=self.source,
            reference=self.reference,
            url=self.url,
            # Citation.retrieved_date is a plain date; Data's real chunks carry a full
            # ISO datetime (retrieved_utc), which pydantic rejects unless truncated first.
            retrieved_date=self.retrieved_date[:10] if self.retrieved_date else None,
            text=self.text,
        )


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _normalise_record(record: dict) -> KnowledgeChunk:
    if "chunk_id" in record:
        # Data's real ATO-table-row format.
        source_id = record["source_id"]
        return KnowledgeChunk(
            id=record["chunk_id"],
            category="award" if source_id in AWARD_SOURCE_IDS else "ato_guidance",
            source=SOURCE_LABELS.get(source_id, source_id),
            reference=f"Table {record['table_number']} ({record['table_name']}), row {record['row_number']}",
            text=record["payment_type"],
            url=record.get("url"),
            retrieved_date=record.get("retrieved_utc"),
            qualifying_earnings=record.get("qualifying_earnings"),
            ordinary_time_earnings=record.get("ordinary_time_earnings"),
        )
    # This module's own generic format (the fixture, and any hand-authored award chunks).
    return KnowledgeChunk(
        id=record["id"],
        category=record["category"],
        source=record["source"],
        reference=record["reference"],
        text=record["text"],
        url=record.get("url"),
        retrieved_date=record.get("retrieved_date"),
        qualifying_earnings=record.get("qualifying_earnings"),
        ordinary_time_earnings=record.get("ordinary_time_earnings"),
    )


def load_chunks(path: Path) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON — {exc}") from exc
            try:
                chunks.append(_normalise_record(record))
            except KeyError as exc:
                raise ValueError(f"{path}:{line_number}: missing field {exc}") from exc
    return chunks


def _reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Combine multiple rank-ordered lists of chunk indices into one, via RRF.

    RRF needs no score normalisation between BM25 and embedding similarity — it only
    looks at each system's rank order, which is what makes combining two differently-
    scaled retrieval methods robust without tuning a blend weight.
    """

    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda idx: scores[idx], reverse=True)


class KnowledgeBase:
    """Loads chunks.jsonl once and indexes it for both keyword and embedding search."""

    def __init__(self, chunks: list[KnowledgeChunk]):
        self.chunks = chunks
        self._bm25 = BM25Okapi([_tokenize(c.text) for c in chunks]) if chunks else None
        self._embedder = TextEmbedding(EMBEDDING_MODEL_NAME) if chunks else None
        self._embeddings = (
            np.array(list(self._embedder.embed([c.text for c in chunks]))) if chunks else None
        )

    @classmethod
    def from_jsonl(cls, path: Path) -> "KnowledgeBase":
        return cls(load_chunks(path))

    def _candidate_indices(self, category: Optional[ChunkCategory]) -> list[int]:
        if category is None:
            return list(range(len(self.chunks)))
        return [i for i, c in enumerate(self.chunks) if c.category == category]

    def search(
        self, query: str, top_k: int = 3, category: Optional[ChunkCategory] = None
    ) -> list[KnowledgeChunk]:
        if not self.chunks:
            return []
        candidates = self._candidate_indices(category)
        if not candidates:
            return []

        query = expand_query(query)
        bm25_scores = self._bm25.get_scores(_tokenize(query))
        bm25_ranking = sorted(candidates, key=lambda i: bm25_scores[i], reverse=True)

        query_vec = np.array(next(self._embedder.embed([query])))
        embedding_scores = self._embeddings @ query_vec
        embedding_ranking = sorted(candidates, key=lambda i: embedding_scores[i], reverse=True)

        fused = _reciprocal_rank_fusion([bm25_ranking, embedding_ranking])
        return [self.chunks[i] for i in fused[:top_k]]


@lru_cache(maxsize=4)
def get_knowledge_base(path: Optional[str] = None) -> KnowledgeBase:
    """Cached loader. Pass a path explicitly in tests; production calls use the default,
    which resolves to Data's real chunks.jsonl once it exists, or the fixture until then."""

    resolved = Path(path) if path else (DEFAULT_CHUNKS_PATH if DEFAULT_CHUNKS_PATH.exists() else FIXTURE_CHUNKS_PATH)
    return KnowledgeBase.from_jsonl(resolved)


def search_ato_guidance(query: str, top_k: int = 3, *, path: Optional[str] = None) -> list[Citation]:
    kb = get_knowledge_base(path)
    return [c.to_citation() for c in kb.search(query, top_k=top_k, category="ato_guidance")]


def search_award(query: str, top_k: int = 3, *, path: Optional[str] = None) -> list[Citation]:
    kb = get_knowledge_base(path)
    return [c.to_citation() for c in kb.search(query, top_k=top_k, category="award")]
