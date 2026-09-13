"""
auditor/knowledge/build_chunks.py

Turns the 14 tables on the ATO qualifying earnings page (source S1) into one
JSONL record per row, keyed by the same S1-T<table>-R<row> scheme already
used as citations in data/eval/dev_set.csv. Run this after fetch_sources.py,
since it reads S1's retrieval timestamp straight out of manifest.json rather
than hardcoding a date that could drift out of sync with what was actually
downloaded.

Run from the repo root:  python auditor/knowledge/build_chunks.py
"""

import json
import pathlib
import sys

KNOWLEDGE_DIR = pathlib.Path(__file__).parent
MANIFEST_PATH = KNOWLEDGE_DIR / "raw" / "manifest.json"
OUTPUT_PATH = KNOWLEDGE_DIR / "chunks.jsonl"

# Each table mirrors the "Ordinary time earnings" and "Qualifying earnings"
# columns as they appear on the live page. Table 14 (salary sacrifice) only
# has a single "Qualifying earnings" column on the source page, so those
# rows carry ote=None rather than a guessed value.
ATO_TABLES = [
    {"number": 1, "name": "Gross", "rows": [
        {"payment": "Ordinary hours of work, as defined in an award or agreement, or if not stated or not separated from other hours, the total hours worked.", "ote": True, "qe": True},
        {"payment": "Casual loading.", "ote": True, "qe": True},
        {"payment": "Shift penalties, including public holiday penalties.", "ote": True, "qe": True},
        {"payment": "Workers compensation, payment for hours an employee performs work or is required to attend work. See table 4 for the excluded case.", "ote": True, "qe": True},
        {"payment": "Piece rates for work done during ordinary hours.", "ote": True, "qe": True},
        {"payment": "Daily rates for employees compensated using a flat daily rate.", "ote": True, "qe": True},
        {"payment": "Flexi time, all ordinary hours paid under a flexi-time arrangement. Flexi-time is treated differently to rostered days off and time off in lieu.", "ote": True, "qe": True},
        {"payment": "Breach of break payments, such as for a rest, meal or crib break, where an award requires overtime rates to be paid until the employee is released from duty. The employee is still considered to be working ordinary hours.", "ote": True, "qe": True},
        {"payment": "Time for travel or training paid within the span of ordinary hours.", "ote": True, "qe": True},
        {"payment": "Charge rates for work performed, outcomes achieved, or targets met by contractors.", "ote": True, "qe": True},
        {"payment": "Public holidays not worked, or worked as ordinary hours.", "ote": True, "qe": True},
    ]},
    {"number": 2, "name": "Other paid leave", "rows": [
        {"payment": "Annual leave.", "ote": True, "qe": True},
        {"payment": "Annual leave loading that is clearly linked to a lost opportunity to work overtime.", "ote": False, "qe": False},
        {"payment": "Annual leave loading, all other cases.", "ote": True, "qe": True},
        {"payment": "Long service leave that is not paid under a portable long service leave scheme.", "ote": True, "qe": True},
        {"payment": "Long service leave that is paid by a scheme administrator under a portable long service leave scheme.", "ote": False, "qe": False},
        {"payment": "Family and domestic violence leave.", "ote": True, "qe": True},
        {"payment": "Rostered days off, time taken and paid at ordinary rates.", "ote": True, "qe": True},
        {"payment": "Sick, personal and carers leave.", "ote": True, "qe": True},
        {"payment": "Time off in lieu of overtime, time taken and paid at ordinary rates.", "ote": True, "qe": True},
        {"payment": "Study leave.", "ote": True, "qe": True},
        {"payment": "Special paid leave.", "ote": True, "qe": True},
        {"payment": "Gardening leave.", "ote": True, "qe": True},
    ]},
    {"number": 3, "name": "Paid parental leave", "rows": [
        {"payment": "Employer paid parental leave, such as maternity, paternity or adoption leave.", "ote": False, "qe": False},
        {"payment": "Government paid parental leave.", "ote": False, "qe": False},
    ]},
    {"number": 4, "name": "Workers compensation", "rows": [
        {"payment": "Workers compensation, payment for hours an employee performs work or is required to attend work.", "ote": True, "qe": True},
        {"payment": "Workers compensation where the employee is not required to work, including any top up or make up pay to bring the payment to their normal rate.", "ote": False, "qe": False},
    ]},
    {"number": 5, "name": "Ancillary and defence leave", "rows": [
        {"payment": "Community service leave, including voluntary emergency management activities for bodies such as a state emergency service, country fire authority or the RSPCA.", "ote": False, "qe": False},
        {"payment": "Jury duty leave, including attendance for jury selection and jury duty.", "ote": False, "qe": False},
        {"payment": "Defence reserve leave paid to volunteers of the Australian Defence Forces undertaking defence service.", "ote": False, "qe": False},
    ]},
    {"number": 6, "name": "Cash out of leave in service", "rows": [
        {"payment": "Cashed out annual leave and leave loading in service.", "ote": True, "qe": True},
        {"payment": "Cashed out long service leave in service.", "ote": True, "qe": True},
        {"payment": "Cashed out sick, personal and carers leave in service.", "ote": True, "qe": True},
        {"payment": "Cashed out rostered days off in service.", "ote": True, "qe": True},
    ]},
    {"number": 7, "name": "Unused leave on termination", "rows": [
        {"payment": "Annual leave or leave loading accrued after 17 August 1993, paid on a normal termination such as voluntary resignation, termination for inefficiency, or retirement.", "ote": False, "qe": False},
        {"payment": "Long service leave accrued after 17 August 1993, paid on a normal termination such as voluntary resignation, termination for inefficiency, or retirement.", "ote": False, "qe": False},
    ]},
    {"number": 8, "name": "Allowances", "rows": [
        {"payment": "Hourly on-call allowance for ordinary hours of work.", "ote": True, "qe": True},
        {"payment": "Task allowances for work efforts or skills such as industry allowances, higher duties, leading hand, first aid or supervisor allowances, for adverse conditions such as heights, confined spaces, cold, wet or heat, or for staying with the current employer such as a retention allowance. Reported as allowance type KN in STP.", "ote": True, "qe": True},
        {"payment": "Expense allowances paid with the reasonable expectation that the money will be fully expended by the employee in the course of providing their services.", "ote": False, "qe": False},
        {"payment": "Allowances that partially compensate for expenses likely to be incurred, paid regardless of whether the expense was incurred, or where the allowance amount has no relationship to the actual cost incurred.", "ote": True, "qe": True},
    ]},
    {"number": 9, "name": "Overtime", "rows": [
        {"payment": "Overtime payments, provided the employee's ordinary hours of work are clearly identified in an award or agreement.", "ote": False, "qe": False},
        {"payment": "Annual leave loading referrable to the lost opportunity to work overtime.", "ote": False, "qe": False},
        {"payment": "Time off in lieu, cash out of time off in lieu while still in service.", "ote": False, "qe": False},
        {"payment": "On-call allowance for hours outside ordinary hours of work.", "ote": False, "qe": False},
        {"payment": "Call back allowance.", "ote": False, "qe": False},
    ]},
    {"number": 10, "name": "Bonuses and commissions", "rows": [
        {"payment": "Commission payments.", "ote": True, "qe": True},
        {"payment": "Commission solely for work performed entirely outside ordinary hours. Not ordinary time earnings, but included as qualifying earnings under Payday Super, one of the actual changes from 1 July 2026.", "ote": False, "qe": True},
        {"payment": "Performance bonus.", "ote": True, "qe": True},
        {"payment": "Christmas bonus.", "ote": True, "qe": True},
        {"payment": "Bonus labelled as ex gratia but paid for ordinary hours of work.", "ote": True, "qe": True},
        {"payment": "Sign-on bonus for new employees.", "ote": True, "qe": True},
        {"payment": "Referral bonus.", "ote": True, "qe": True},
        {"payment": "Return to work bonus after parental leave.", "ote": True, "qe": True},
        {"payment": "Bonus solely for work performed entirely outside ordinary hours. The opposite outcome to the same scenario paid as a commission.", "ote": False, "qe": False},
    ]},
    {"number": 11, "name": "Directors fees", "rows": [
        {"payment": "Remuneration paid to a working director.", "ote": True, "qe": True},
        {"payment": "Remuneration paid to a non-working director.", "ote": True, "qe": True},
    ]},
    {"number": 12, "name": "Return to work payments", "rows": [
        {"payment": "Bonus paid to an ex-employee to encourage them to return to the employer.", "ote": True, "qe": True},
        {"payment": "Bonus payments made to end industrial action and have employees resume work.", "ote": True, "qe": True},
        {"payment": "Bonus paid to an employee who has resigned, to encourage them to withdraw their resignation.", "ote": True, "qe": True},
    ]},
    {"number": 13, "name": "Termination payments", "rows": [
        {"payment": "Unused leave on termination, including annual leave, annual leave loading and long service leave. Applies regardless of the reason for termination.", "ote": False, "qe": False},
        {"payment": "Payment in lieu of notice, for all termination reasons.", "ote": True, "qe": True},
        {"payment": "Unused personal or carers leave on termination, for all termination reasons.", "ote": False, "qe": False},
        {"payment": "Unused rostered days off and time off in lieu of overtime paid on termination.", "ote": False, "qe": False},
        {"payment": "Other payments in consequence of termination, such as a gratuity or golden handshake, genuine redundancy or early retirement above the tax free limit, severance pay, non-genuine redundancy, compensation for loss of job or wrongful dismissal, invalidity payments other than compensation for personal injury, or lump sum payments paid due to the death of an employee.", "ote": False, "qe": False},
    ]},
    {"number": 14, "name": "Salary sacrifice", "rows": [
        {"payment": "Salary sacrificed to superannuation, where the salary that is sacrificed would otherwise be qualifying earnings if it had instead been paid to the employee.", "ote": None, "qe": True},
        {"payment": "Salary sacrificed to superannuation, where the salary that is sacrificed would not otherwise be qualifying earnings if it had instead been paid to the employee, such as paid parental leave or overtime.", "ote": None, "qe": False},
        {"payment": "Salary sacrificed to other employee benefits, including amounts that are fringe benefits and exempt fringe benefits.", "ote": None, "qe": False},
    ]},
]


def load_s1_provenance():
    if not MANIFEST_PATH.exists():
        sys.exit(f"manifest.json not found at {MANIFEST_PATH}. Run fetch_sources.py first.")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest:
        if entry["source_id"] == "S1":
            return entry
    sys.exit("No S1 entry in manifest.json. Run fetch_sources.py first.")


def main():
    provenance = load_s1_provenance()
    chunk_count = 0

    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        for table in ATO_TABLES:
            for row_index, row in enumerate(table["rows"], start=1):
                chunk_id = f"S1-T{table['number']:02d}-R{row_index:02d}"
                record = {
                    "chunk_id": chunk_id,
                    "source_id": "S1",
                    "table_number": table["number"],
                    "table_name": table["name"],
                    "row_number": row_index,
                    "payment_type": row["payment"],
                    "ordinary_time_earnings": row["ote"],
                    "qualifying_earnings": row["qe"],
                    "url": provenance["resolved_url"],
                    "retrieved_utc": provenance["retrieved_utc"],
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                chunk_count += 1

    print(f"Wrote {chunk_count} chunks across {len(ATO_TABLES)} tables to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
