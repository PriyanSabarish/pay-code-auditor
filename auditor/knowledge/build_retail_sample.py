"""
auditor/knowledge/build_retail_sample.py

Generates the retail sample business: paycodes.csv, payruns.csv, and a
private answer key kept entirely outside the git working tree. Modelled
loosely on the General Retail Industry Award MA000004, referenced in
sources.md but not downloaded, this business exists to widen the code name
vocabulary and vary which categories carry the planted errors, not to
duplicate the café's coverage.

Two codes are deliberately misconfigured. COMMWEEKEND carries the
commission versus bonus trap that dev_set.csv already tests in isolation,
here it appears inside a full business so the audit has to find it amid 44
other codes rather than as a single labelled row. ONCALLWEEKEND is the
second setup error and also the retail pattern anomaly, an allowance
excluded from super, paid as an identical flat amount every single run it
appears in, the disguised regular pay signature.

Uses the same contiguous date selection as build_cafe_sample.py, for the
same reason: a scattered sample of pay dates can produce gaps that don't
match any real pay cycle, wrongly leaving a code's frequency unclassified.

Run from the repo root:  python auditor/knowledge/build_retail_sample.py
"""

import csv
import json
import pathlib
import random

OUTPUT_DIR = pathlib.Path("data/samples/retail")
ANSWER_KEY_DIR = pathlib.Path.home() / "pay-code-auditor-private" / "answer-keys"

PAY_DATES = [
    "2026-06-19", "2026-07-03", "2026-07-17", "2026-07-31",
    "2026-08-14", "2026-08-28", "2026-09-11",
]

GENERATOR_SEED = 20260714  # one day on from the cafe seed, deliberately distinct

PAYCODE_DEFINITIONS = [
    ("ORDHRS", "Ordinary Hours", "Base ordinary hours across all roles", "Y", "Wages", (7, 7), (14000, 18000), None, False),
    ("SUNPEN", "Sunday Penalty 150%", "Sunday ordinary hours penalty", "Y", "Penalty", (7, 7), (1200, 2100), None, False),
    ("SATPEN", "Saturday Penalty 125%", "Saturday ordinary hours penalty", "Y", "Penalty", (7, 7), (900, 1500), None, False),
    ("PHPEN", "Public Holiday Penalty 225%", "Public holiday penalty for hours worked", "Y", "Penalty", (1, 2), (450, 980), None, False),
    ("EVEPEN", "Late Night Penalty", "Penalty for trading hours after 6pm weekdays", "Y", "Penalty", (6, 7), (380, 720), None, False),
    ("CASLOAD", "Casual Loading 25%", "Casual loading on ordinary hours", "Y", "Loading", (7, 7), (1800, 2600), None, False),
    ("HDALLOW", "HD Allow", "Higher duties allowance, acting store manager", "Y", "Allowance", (1, 3), (80, 150), None, False),
    ("FIRSTAID", "First Aid Officer", "First aid officer allowance", "Y", "Allowance", (6, 7), (25, 25), 25.00, False),
    ("KEYALLOW", "Key Holder Allow", "Allowance for staff holding store keys", "Y", "Allowance", (5, 7), (20, 35), None, False),
    ("UNIFORMALLOW", "Uniform Allow", "Flat uniform allowance regardless of expense", "Y", "Allowance", (1, 2), (120, 120), 120.00, False),
    ("LAUNDRYALLOW", "Laundry Allow", "Uniform laundering allowance", "N", "Allowance", (5, 7), (10, 18), None, False),
    ("TOOLALLOW", "Stationery Allow", "Allowance expected to be fully spent on work tools", "N", "Allowance", (2, 4), (15, 30), None, False),
    ("OT15", "Overtime 1.5x", "Overtime paid at time and a half", "Y", "Overtime", (2, 4), (150, 480), None, True),
    ("OT20", "Overtime 2x", "Overtime paid at double time", "N", "Overtime", (1, 2), (80, 220), None, True),
    ("ONCALLWEEKEND", "Weekend On Call", "Standby allowance for weekend roster coverage", "N", "Overtime", (7, 7), (95, 95), 95.00, False),
    ("TOILCASHOUT", "TOIL Cashout", "Cash out of time off in lieu", "N", "Leave", (1, 1), (120, 320), None, False),
    ("RDOCASHOUT", "RDO Cashout", "Cash out of a rostered day off, in service", "Y", "Leave", (1, 2), (180, 380), None, False),
    ("ALCASHOUT", "AL Cashout", "Cash out of annual leave, in service", "Y", "Leave", (1, 2), (500, 1100), None, False),
    ("ANNLV", "Annual Leave", "Paid annual leave taken", "Y", "Leave", (5, 7), (800, 2000), None, False),
    ("ALLOADING", "AL Loading 17.5%", "Annual leave loading, general case", "Y", "Loading", (5, 7), (140, 350), None, False),
    ("ALLOADOT", "AL Loading (OT Linked)", "Leave loading clearly tied to lost overtime opportunity", "Y", "Loading", (1, 1), (60, 60), 60.00, False),
    ("LSLINHOUSE", "Long Service Leave", "Long service leave, not a portable scheme", "Y", "Leave", (1, 1), (2200, 3800), None, False),
    ("SICKLV", "Personal Leave", "Paid personal and carers leave", "Y", "Leave", (5, 7), (300, 1000), None, False),
    ("FDVLEAVE", "FDV Leave", "Family and domestic violence leave", "Y", "Leave", (1, 1), (250, 550), None, False),
    ("PPLGOVT", "PPL Govt Scheme", "Government paid parental leave, employer administered", "N", "Leave", (1, 2), (1400, 2200), None, False),
    ("JURYDUTY", "Jury Duty Leave", "Jury duty leave", "N", "Leave", (0, 1), (150, 300), None, False),
    ("COMMQ3", "Commission Q3", "Sales commission for the quarter", "Y", "Bonus", (2, 3), (400, 1200), None, False),
    ("COMMWEEKEND", "Weekend Sales Bonus", "Sales incentive earned entirely on weekend trading shifts", "N", "Bonus", (5, 6), (200, 600), None, False),
    ("XMASBONUS", "Christmas Bonus", "Discretionary Christmas bonus for ordinary hours staff", "Y", "Bonus", (1, 1), (300, 700), None, False),
    ("REFERRALBONUS", "Staff Referral Bonus", "Bonus for referring a new staff member", "Y", "Bonus", (1, 2), (150, 300), None, False),
    ("STOCKTAKEBON", "Stocktake Bonus", "Bonus for ordinary hours worked during stocktake week", "Y", "Bonus", (1, 1), (100, 250), None, False),
    ("WCOMPWORKED", "WComp Light Duties", "Workers compensation, light duties worked", "Y", "Leave", (0, 1), (700, 1300), None, False),
    ("WCOMPNOTWORK", "WComp Not Worked", "Workers compensation, not required to work", "N", "Leave", (1, 1), (700, 1300), None, False),
    ("DIRFEE", "Director Fee", "Working director's fee", "Y", "Director", (6, 7), (1100, 1100), 1100.00, False),
    ("STUDYLEAVE", "Study Leave", "Paid study leave for a retail traineeship", "Y", "Leave", (1, 1), (140, 300), None, False),
    ("SPECIALLEAVE", "Special Paid Leave", "Compassionate or special paid leave", "Y", "Leave", (1, 1), (200, 450), None, False),
    ("PILN", "PILN", "Payment in lieu of notice", "Y", "Termination", (0, 1), (1000, 2400), None, False),
    ("REDUNDANCY", "Redundancy Pmt", "Genuine redundancy payment", "N", "Termination", (1, 1), (3500, 7000), None, False),
    ("ALTERM", "AL Payout Term", "Unused annual leave paid on termination", "N", "Termination", (1, 1), (900, 2000), None, False),
    ("LSLTERM", "LSL Payout Term", "Unused long service leave paid on termination", "N", "Termination", (1, 1), (1800, 3400), None, False),
    ("RDOTERM", "RDO Payout Term", "Unused RDO paid on termination", "N", "Termination", (0, 1), (170, 420), None, False),
    ("MEALALLOWOT", "OT Meal Allow", "Overtime meal allowance", "N", "Allowance", (1, 3), (16, 26), None, True),
    ("SUPERVISORALLOW", "Supervisor Allow", "Ongoing supervisory task allowance", "Y", "Allowance", (5, 7), (45, 90), None, False),
    ("ONCALLAH", "On Call After Hours", "On call allowance strictly outside ordinary trading hours", "N", "Overtime", (1, 2), (35, 70), None, False),
]

ANSWER_KEY = {
    "ORDHRS": ("yes", "S1-T01-R01", False),
    "SUNPEN": ("yes", "S1-T01-R03", False),
    "SATPEN": ("yes", "S1-T01-R03", False),
    "PHPEN": ("yes", "S1-T01-R03", False),
    "EVEPEN": ("yes", "S1-T01-R03", False),
    "CASLOAD": ("yes", "S1-T01-R02", False),
    "HDALLOW": ("yes", "S1-T08-R02", False),
    "FIRSTAID": ("yes", "S1-T08-R02", False),
    "KEYALLOW": ("yes", "S1-T08-R02", False),
    "UNIFORMALLOW": ("yes", "S1-T08-R04", False),
    "LAUNDRYALLOW": ("no", "S1-T08-R03", False),
    "TOOLALLOW": ("no", "S1-T08-R03", False),
    "OT15": ("no", "S1-T09-R01", False),
    "OT20": ("no", "S1-T09-R01", False),
    "ONCALLWEEKEND": ("yes", "S1-T08-R02", True),
    "TOILCASHOUT": ("no", "S1-T09-R03", False),
    "RDOCASHOUT": ("yes", "S1-T06-R04", False),
    "ALCASHOUT": ("yes", "S1-T06-R01", False),
    "ANNLV": ("yes", "S1-T02-R01", False),
    "ALLOADING": ("yes", "S1-T02-R03", False),
    "ALLOADOT": ("no", "S1-T02-R02", False),
    "LSLINHOUSE": ("yes", "S1-T02-R04", False),
    "SICKLV": ("yes", "S1-T02-R08", False),
    "FDVLEAVE": ("yes", "S1-T02-R06", False),
    "PPLGOVT": ("no", "S1-T03-R02", False),
    "JURYDUTY": ("no", "S1-T05-R02", False),
    "COMMQ3": ("yes", "S1-T10-R01", False),
    "COMMWEEKEND": ("yes", "S1-T10-R02", True),
    "XMASBONUS": ("yes", "S1-T10-R04", False),
    "REFERRALBONUS": ("yes", "S1-T10-R07", False),
    "STOCKTAKEBON": ("yes", "S1-T10-R03", False),
    "WCOMPWORKED": ("yes", "S1-T04-R01", False),
    "WCOMPNOTWORK": ("no", "S1-T04-R02", False),
    "DIRFEE": ("yes", "S1-T11-R01", False),
    "STUDYLEAVE": ("yes", "S1-T02-R10", False),
    "SPECIALLEAVE": ("yes", "S1-T02-R11", False),
    "PILN": ("yes", "S1-T13-R02", False),
    "REDUNDANCY": ("no", "S1-T13-R05", False),
    "ALTERM": ("no", "S1-T07-R01", False),
    "LSLTERM": ("no", "S1-T07-R02", False),
    "RDOTERM": ("no", "S1-T13-R04", False),
    "MEALALLOWOT": ("no", "S1-T08-R03", False),
    "SUPERVISORALLOW": ("yes", "S1-T08-R02", False),
    "ONCALLAH": ("no", "S1-T09-R04", False),
}

PATTERN_ANOMALY_NOTE = (
    "ONCALLWEEKEND is configured N (excluded) and named like a genuine "
    "standby allowance, which reads as plausible on its own. But it is a "
    "task and skill type allowance for ongoing weekend roster coverage "
    "under S1-T08-R02, not a true on-call payment for hours outside "
    "ordinary hours, and it is paid the identical $95 in every single run "
    "it appears in across all seven, the same disguised regular pay "
    "signature as the cafe's LOYALTYBON. Two independent reasons this "
    "should be flagged, not one."
)


def choose_contiguous_dates(rng: random.Random, appearances: int) -> list[str]:
    if appearances <= 0:
        return []
    if appearances >= len(PAY_DATES):
        return list(PAY_DATES)
    latest_valid_start = len(PAY_DATES) - appearances
    start_index = rng.randint(0, latest_valid_start)
    return PAY_DATES[start_index:start_index + appearances]


def build_paycodes_csv(rng: random.Random) -> list[dict]:
    rows = []
    for code, name, description, configured, category, freq_range, amount_range, flat_amount, overtime_linked in PAYCODE_DEFINITIONS:
        rows.append({
            "code": code, "name": name, "description": description,
            "counts_for_super": configured, "payroll_category": category,
        })
    with (OUTPUT_DIR / "paycodes.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["code", "name", "description", "counts_for_super", "payroll_category"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def build_payruns_csv(rng: random.Random) -> list[dict]:
    rows = []
    for code, name, description, configured, category, freq_range, amount_range, flat_amount, overtime_linked in PAYCODE_DEFINITIONS:
        appearances = rng.randint(*freq_range)
        chosen_dates = choose_contiguous_dates(rng, appearances)
        for pay_date in chosen_dates:
            amount = flat_amount if flat_amount is not None else round(rng.uniform(*amount_range), 2)
            employees_paid = rng.randint(1, 10)
            overtime_hours = round(rng.uniform(3, 18), 1) if overtime_linked else ""
            rows.append({
                "pay_date": pay_date, "code": code, "total_amount": f"{amount:.2f}",
                "employees_paid": employees_paid, "overtime_hours": overtime_hours,
            })
    rows.sort(key=lambda r: (r["pay_date"], r["code"]))
    with (OUTPUT_DIR / "payruns.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pay_date", "code", "total_amount", "employees_paid", "overtime_hours"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def build_answer_key() -> None:
    ANSWER_KEY_DIR.mkdir(parents=True, exist_ok=True)
    planted = [code for code, (_, _, is_error) in ANSWER_KEY.items() if is_error]
    payload = {
        "business": "retail",
        "total_codes": len(PAYCODE_DEFINITIONS),
        "planted_setup_errors": planted,
        "planted_pattern_anomalies": ["ONCALLWEEKEND"],
        "pattern_anomaly_note": PATTERN_ANOMALY_NOTE,
        "verdicts": {
            code: {"correct_counts_towards_super": verdict, "ato_citation": citation, "is_planted_error": is_error}
            for code, (verdict, citation, is_error) in ANSWER_KEY.items()
        },
    }
    key_path = ANSWER_KEY_DIR / "retail_answer_key.json"
    key_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Private answer key written to {key_path} (outside the git working tree)")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(GENERATOR_SEED)

    paycode_rows = build_paycodes_csv(rng)
    payrun_rows = build_payruns_csv(rng)
    build_answer_key()

    print(f"Wrote {len(paycode_rows)} pay codes to {OUTPUT_DIR / 'paycodes.csv'}")
    print(f"Wrote {len(payrun_rows)} pay run rows to {OUTPUT_DIR / 'payruns.csv'}")
    print(f"Planted setup errors: {[c for c, (_, _, e) in ANSWER_KEY.items() if e]}")


if __name__ == "__main__":
    main()
