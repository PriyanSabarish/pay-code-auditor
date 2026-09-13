"""Evaluation harness (spec section 10). Runs Lane A's classifier against a labelled
set and reports accuracy plus the cost/latency metrics classify.summarize_metrics
already tracks. Compares three baselines from the same underlying classifier:

    keyword   — the naive keyword_guess() rules alone, no LLM call
    no_rag    — classify_code(): LLM only, no retrieved context
    classifier — classify_code_with_retrieval(): the real award-aware pipeline

Defaults to data/eval/dev_set.csv and refuses data/eval/test_set.csv unless you
pass --allow-test-set explicitly. The test set exists to produce one held-out
number for the README at the very end — tuning anything against it (including
"just checking" during development) invalidates that number. See ADR-B03/B04
and tests/test_leakage.py.

Usage:
    python -m eval.run_eval                       # dev set, all three modes
    python -m eval.run_eval --mode classifier      # dev set, one mode only
    python -m eval.run_eval --dataset data/eval/test_set.csv --allow-test-set
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from auditor.classify import classify_code, classify_code_with_retrieval, keyword_guess, summarize_metrics
from auditor.schemas import PayCode

DEFAULT_DATASET = REPO_ROOT / "data" / "eval" / "dev_set.csv"
TEST_SET = REPO_ROOT / "data" / "eval" / "test_set.csv"

MODES = ("keyword", "no_rag", "classifier")


@dataclass
class EvalRow:
    code: str
    messy_name: str
    expected: str
    ato_citation: str
    rationale: str


def load_dataset(path: Path) -> list[EvalRow]:
    with path.open(encoding="utf-8") as handle:
        return [
            EvalRow(
                code=row["code"],
                messy_name=row["messy_name"],
                expected=row["expected_counts_towards_super"],
                ato_citation=row["ato_citation"],
                rationale=row["rationale"],
            )
            for row in csv.DictReader(handle)
        ]


def _pay_code(row: EvalRow) -> PayCode:
    # counts_for_super is the client's current payroll setting, which this dataset
    # doesn't model (it's testing classification accuracy, not audit status) — the
    # classifier never reads it, only keyword_guess's escalation check touches the
    # code/name, so any placeholder value is safe here.
    return PayCode(code=row.code, name=row.messy_name, counts_for_super="N")


def run_mode(mode: str, rows: list[EvalRow]) -> tuple[list[dict], dict]:
    results = []
    outcomes = []
    for row in rows:
        pay_code = _pay_code(row)
        if mode == "keyword":
            guess = keyword_guess(pay_code)
            predicted = guess or "unclear"
        elif mode == "no_rag":
            outcome = classify_code(pay_code)
            outcomes.append(outcome)
            predicted = outcome.classification.counts_towards_super
        elif mode == "classifier":
            outcome = classify_code_with_retrieval(pay_code)
            outcomes.append(outcome)
            predicted = outcome.classification.counts_towards_super
        else:
            raise ValueError(f"unknown mode: {mode!r}")

        results.append(
            {
                "code": row.code,
                "messy_name": row.messy_name,
                "expected": row.expected,
                "predicted": predicted,
                "correct": predicted == row.expected,
                "ato_citation": row.ato_citation,
                "rationale": row.rationale,
            }
        )

    metrics = summarize_metrics(outcomes) if outcomes else {}
    return results, metrics


def print_report(mode: str, results: list[dict], metrics: dict) -> None:
    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    print(f"\n=== {mode} ({correct}/{total} = {correct / total:.1%}) ===")

    misses = [r for r in results if not r["correct"]]
    if misses:
        print("Wrong:")
        for r in misses:
            print(
                f"  {r['code']:<16} expected={r['expected']:<8} got={r['predicted']:<8} "
                f"[{r['ato_citation']}] {r['rationale']}"
            )
    else:
        print("All correct.")

    if metrics:
        print(
            f"  llm_calls={metrics['llm_calls']} escalated={metrics['escalated_share']:.0%} "
            f"tokens={metrics['total_tokens']} avg_latency={metrics['avg_latency_seconds_per_call']}s"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=MODES, default=None, help="run one mode only; default runs all three")
    parser.add_argument(
        "--allow-test-set",
        action="store_true",
        help="required to point --dataset at data/eval/test_set.csv — see the module docstring before using this",
    )
    args = parser.parse_args()

    if args.dataset.resolve() == TEST_SET.resolve() and not args.allow_test_set:
        parser.error(
            "refusing to run against data/eval/test_set.csv without --allow-test-set. "
            "Fix findings against the dev set only — see the module docstring."
        )

    rows = load_dataset(args.dataset)
    print(f"Loaded {len(rows)} codes from {args.dataset.relative_to(REPO_ROOT)}")

    modes = [args.mode] if args.mode else list(MODES)
    for mode in modes:
        results, metrics = run_mode(mode, rows)
        print_report(mode, results, metrics)


if __name__ == "__main__":
    main()
