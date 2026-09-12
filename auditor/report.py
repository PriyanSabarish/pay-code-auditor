"""CSV export of an audit's verdicts (spec section 11: report.py, owned by the Data lane).

Minimal interim implementation so GET /api/audits/{id}/report.csv works before Data
lane replaces it with the full version (e.g. cost summaries, per-client formatting).
"""

from __future__ import annotations

import csv
import io

from .schemas import CodeVerdict


def generate_report_csv(verdicts: list[CodeVerdict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "code",
            "name",
            "status",
            "counts_towards_super",
            "confidence",
            "annual_amount",
            "super_amount",
            "max_penalty_uplift",
            "reviewer_decision",
            "override_note",
        ]
    )
    for v in verdicts:
        writer.writerow(
            [
                v.code,
                v.name,
                v.status,
                v.classification.counts_towards_super,
                v.classification.confidence,
                v.impact.annual_amount if v.impact else "",
                v.impact.super_amount if v.impact else "",
                v.impact.max_penalty_uplift if v.impact and v.impact.max_penalty_uplift is not None else "",
                v.reviewer_decision or "",
                v.override_note or "",
            ]
        )
    return buffer.getvalue()
