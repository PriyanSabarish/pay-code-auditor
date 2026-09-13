"""Per-bookkeeper memory of clarifying-question answers (spec section 6.5).

Stores only pay code context — a normalised code pattern, the question, and the
bookkeeper's answer. Never employee details, never dollar amounts, nothing from
payruns.csv. This is deliberately the one thing in the whole system that persists
between audits (see the original spec's storage note: everything else is processed in
memory and thrown away).

No auth system exists in this prototype, so there is no real bookkeeper identity to key
on yet. Every call site defaults to DEFAULT_BOOKKEEPER_ID ("default") — a single-tenant
stand-in. Once real accounts exist, passing the actual bookkeeper id through is a
one-line change at each call site; the storage and lookup logic here doesn't change.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_MEMORY_PATH = Path(__file__).resolve().parent.parent / "var" / "bookkeeper_memory.json"
DEFAULT_BOOKKEEPER_ID = "default"

_PATTERN_RE = re.compile(r"[^A-Z0-9 ]+")


def normalise_code_pattern(code: str) -> str:
    """Turn a pay code into a stable lookup key: 'RDO_Payout-2026' and 'rdo   payout'
    both become 'RDO PAYOUT', so near-identical codes across clients, or the same code
    spelled slightly differently next year, still hit the same remembered answer."""

    upper = code.upper()
    cleaned = _PATTERN_RE.sub(" ", upper)
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass(frozen=True)
class RememberedAnswer:
    bookkeeper_id: str
    code_pattern: str
    question: str
    answer: str
    stored_at: str  # ISO datetime, UTC


class BookkeeperMemory:
    """A small JSON-backed store. One remembered answer per (bookkeeper, code pattern)
    — a fresh answer replaces a stale one rather than accumulating duplicates."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._entries: list[RememberedAnswer] = self._load()

    def _load(self) -> list[RememberedAnswer]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [RememberedAnswer(**record) for record in raw]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self._entries], f, indent=2)

    def remember(self, bookkeeper_id: str, code: str, question: str, answer: str) -> RememberedAnswer:
        pattern = normalise_code_pattern(code)
        entry = RememberedAnswer(
            bookkeeper_id=bookkeeper_id,
            code_pattern=pattern,
            question=question,
            answer=answer,
            stored_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._entries = [
                e
                for e in self._entries
                if not (e.bookkeeper_id == bookkeeper_id and e.code_pattern == pattern)
            ]
            self._entries.append(entry)
            self._save()
        return entry

    def recall(self, bookkeeper_id: str, code: str) -> Optional[RememberedAnswer]:
        pattern = normalise_code_pattern(code)
        with self._lock:
            for e in self._entries:
                if e.bookkeeper_id == bookkeeper_id and e.code_pattern == pattern:
                    return e
        return None


_default_memory: Optional[BookkeeperMemory] = None
_default_memory_lock = threading.Lock()


def get_memory(path: Optional[Path] = None) -> BookkeeperMemory:
    """The process-wide default store, cached — unless an explicit path is given (as
    tests do), which always returns a fresh instance so tests never touch real data."""

    if path is not None:
        return BookkeeperMemory(path)
    global _default_memory
    with _default_memory_lock:
        if _default_memory is None:
            _default_memory = BookkeeperMemory(DEFAULT_MEMORY_PATH)
        return _default_memory
