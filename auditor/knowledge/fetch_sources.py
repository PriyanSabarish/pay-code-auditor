"""
Downloads each knowledge source, stores the raw capture, and records
provenance (URL, resolved URL, retrieval timestamp, byte size, SHA256).

Run from the repo root:  python auditor/knowledge/fetch_sources.py

Nothing here interprets the content. It only proves what was downloaded,
from where, and when, so the guidance can be re dated once the ATO revises
a page. S3 (SGR 2009/2) is deliberately not automated, see the note at the
bottom of main().
"""

import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

VAULT_DIR = pathlib.Path(__file__).parent / "raw"
LEDGER_PATH = VAULT_DIR / "manifest.json"
POLITE_AGENT = "PayCodeAuditor/0.1 (hackathon research build)"

SOURCE_REGISTER = [
    {
        "source_id": "S1",
        "label": "ATO What payments are qualifying earnings",
        "url": (
            "https://www.ato.gov.au/businesses-and-organisations/"
            "super-for-employers/paying-super-on-payday/"
            "what-payments-are-qualifying-earnings"
        ),
        "filename": "s1_ato_qualifying_earnings.html",
    },
    {
        "source_id": "S2",
        "label": "ATO Law Companion Ruling LCR 2026/D1",
        "url": (
            "https://www.ato.gov.au/law/view/document"
            "?DocID=COD/LCR2026D1/NAT/ATO/00001&PiT=99991231235958"
        ),
        "filename": "s2_lcr_2026_d1.html",
    },
    {
        "source_id": "S4",
        "label": "Hospitality Industry (General) Award MA000009",
        "url": "https://awards.fairwork.gov.au/MA000009.html",
        "filename": "s4_award_ma000009.html",
    },
]


def pull_one(entry):
    """Fetch a single source. Returns a provenance record, or None on failure."""
    request = urllib.request.Request(
        entry["url"], headers={"User-Agent": POLITE_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as stream:
            payload = stream.read()
            landed_at = stream.geturl()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as problem:
        print(f"  FAILED {entry['source_id']}: {problem}")
        return None

    target = VAULT_DIR / entry["filename"]
    target.write_bytes(payload)

    return {
        "source_id": entry["source_id"],
        "label": entry["label"],
        "requested_url": entry["url"],
        "resolved_url": landed_at,
        "saved_as": entry["filename"],
        "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    provenance = []

    for entry in SOURCE_REGISTER:
        print(f"Fetching {entry['source_id']} ... {entry['label']}")
        record = pull_one(entry)
        if record is not None:
            provenance.append(record)
            print(f"  saved {record['byte_size']} bytes, sha256 {record['sha256'][:12]}")

    LEDGER_PATH.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"\n{len(provenance)} of {len(SOURCE_REGISTER)} sources captured.")
    print(f"Provenance ledger: {LEDGER_PATH}")

    print("\nS3 (SGR 2009/2) is not automated. Download it from the ATO Legal")
    print("Database, drop it in raw/, and add its real URL to sources.md.")

    if len(provenance) < len(SOURCE_REGISTER):
        sys.exit(1)


if __name__ == "__main__":
    main()
