"""
tests/test_leakage.py

Guards ADR-B03 and ADR-B04: no code from data/eval/test_set.csv may appear
in data/eval/dev_set.csv (the methodologically real leakage risk, since
dev_set.csv is explicitly allowed inside prompts as few-shot examples), in
any sample business fixture, in the retrieval chunk index, or in Lane A's
prompt or classifier source once those files exist on this branch.

Run standalone:  pytest tests/test_leakage.py -v
"""

import csv
import json
import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent
TEST_SET_PATH = REPO_ROOT / "data" / "eval" / "test_set.csv"
DEV_SET_PATH = REPO_ROOT / "data" / "eval" / "dev_set.csv"
CHUNKS_PATH = REPO_ROOT / "auditor" / "knowledge" / "chunks.jsonl"

FIXTURE_PAYCODE_PATHS = [
    REPO_ROOT / "data" / "samples" / "dummy" / "paycodes.csv",
    REPO_ROOT / "data" / "samples" / "cafe" / "paycodes.csv",
    REPO_ROOT / "data" / "samples" / "retail" / "paycodes.csv",
    REPO_ROOT / "data" / "samples" / "construction" / "paycodes.csv",
    # The small subset the website actually serves for its bundled "sample data" feature
    # (api/routes.py) — a separate file from the full fixture above, so it needs its own
    # entry here rather than being covered by scanning the full one.
    REPO_ROOT / "data" / "samples" / "cafe" / "sanity_paycodes.csv",
    REPO_ROOT / "data" / "samples" / "retail" / "sanity_paycodes.csv",
    REPO_ROOT / "data" / "samples" / "construction" / "sanity_paycodes.csv",
]

# Not owned by Lane B, and may not exist yet on this branch. Scanned if
# present, skipped with a clear note if not, never created by this test.
LANE_A_SOURCE_PATHS = [
    REPO_ROOT / "auditor" / "prompts.py",
    REPO_ROOT / "auditor" / "classify.py",
]


def load_test_set_codes() -> set[str]:
    with TEST_SET_PATH.open() as handle:
        return {row["code"] for row in csv.DictReader(handle)}


def load_codes_from_paycodes_csv(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open() as handle:
        return {row["code"] for row in csv.DictReader(handle)}


class TestNoLeakageFromHeldOutSet:

    def test_test_set_has_no_duplicate_codes(self):
        with TEST_SET_PATH.open() as handle:
            codes = [row["code"] for row in csv.DictReader(handle)]
        assert len(codes) == len(set(codes)), "duplicate codes inside test_set.csv itself"

    def test_no_overlap_with_dev_set(self):
        """The real leakage risk: dev_set.csv is explicitly allowed inside
        prompts as few-shot examples, so any shared code string would let a
        classifier get a held-out code right by memorised association
        rather than genuine classification."""
        test_codes = load_test_set_codes()
        dev_codes = load_codes_from_paycodes_csv(DEV_SET_PATH) if False else set()
        with DEV_SET_PATH.open() as handle:
            dev_codes = {row["code"] for row in csv.DictReader(handle)}
        overlap = test_codes & dev_codes
        assert not overlap, f"test_set.csv codes also appear in dev_set.csv: {overlap}"

    def test_no_overlap_with_any_sample_business_fixture(self):
        test_codes = load_test_set_codes()
        for fixture_path in FIXTURE_PAYCODE_PATHS:
            fixture_codes = load_codes_from_paycodes_csv(fixture_path)
            overlap = test_codes & fixture_codes
            assert not overlap, f"test_set.csv codes appear in {fixture_path}: {overlap}"

    def test_no_test_code_appears_in_the_retrieval_chunk_index(self):
        """chunks.jsonl holds ATO category text, never a pay code name, so
        this should trivially pass, kept as a defensive check since the
        chunk index is one of the three locations the plan explicitly
        names."""
        if not CHUNKS_PATH.exists():
            return
        test_codes = load_test_set_codes()
        with CHUNKS_PATH.open() as handle:
            chunk_text = handle.read().upper()
        leaked = [code for code in test_codes if code.upper() in chunk_text]
        assert not leaked, f"test_set.csv codes found inside chunks.jsonl text: {leaked}"

    def test_no_test_code_appears_in_lane_a_prompt_or_classifier_source(self):
        """Skips gracefully if Lane A hasn't built these files on this
        branch yet. This test exists to catch it the moment they do, not
        to force their existence."""
        test_codes = load_test_set_codes()
        for source_path in LANE_A_SOURCE_PATHS:
            if not source_path.exists():
                continue
            source_text = source_path.read_text(encoding="utf-8").upper()
            leaked = [code for code in test_codes if code.upper() in source_text]
            assert not leaked, f"test_set.csv codes found inside {source_path}: {leaked}"
