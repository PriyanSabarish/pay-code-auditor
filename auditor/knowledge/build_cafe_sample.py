"""
auditor/knowledge/build_cafe_sample.py

Generates the café sample business: paycodes.csv, payruns.csv, and a private
answer key kept entirely outside the git working tree. Café is modelled on
the Hospitality Industry (General) Award MA000009 (source S4), the award the
demo video uses.

Four codes are deliberately misconfigured. Three are straightforward setup
errors. The fourth, LOYALTYBON, is both a setup error and the café's payment
pattern anomaly, a vaguely worded bonus that also happens to be paid the
identical amount every single run, which is exactly the kind of code the
tool exists to catch on two independent signals rather than one.

Codes that appear in only some pay runs get a contiguous block of dates,
never a scattered sample, since real payroll usage starts or stops rather
than skipping at random, and a scattered sample can produce gaps that don't
match any real pay cycle, which would wrongly leave the code's frequency
unclassified.

Run from the repo root:  python auditor/knowledge/build_cafe_sample.py
"""

import csv
import json
import pathlib
import random

OUTPUT_DIR = pathlib.Path("data/samples/cafe")
ANSWER_KEY_DIR = pathlib.Path.home() / "pay-code-auditor-private" / "answer-keys"

PAY_DATES = [
    "2026-06-19", "2026-07-03", "2026-07-17", "2026-07-31",
    "2026-08-14", "2026-08-28", "2026-09-11",
]

GENERATOR_SEED = 20260713

PAYCODE_DEFINITIONS = [
    ("ORDHRS", "Ordinary Hours", "Base ordinary hours across all roles", "Y", "Wages", (7, 7), (9500, 12500), None, False),
    ("PHNOTWORKED", "Public Holiday Not Worked", "Public holiday paid at ordinary rate, not worked", "Y", "Wages", (1, 2), (280, 640), None, False),
    ("CASLOAD", "Casual Loading 25%", "Casual loading on ordinary hours", "Y", "Loading", (7, 7), (1400, 2200), None, False),
    ("PHPEN", "Public Holiday Penalty", "Public holiday penalty for hours worked", "Y", "Penalty", (1, 2), (380, 920), None, False),
    ("EVEPEN", "Evening Penalty", "Penalty for ordinary hours worked after 7pm", "Y", "Penalty", (6, 7), (420, 780), None, False),
    ("SATPEN", "Saturday Penalty", "Saturday ordinary hours penalty", "Y", "Penalty", (7, 7), (650, 1050), None, False),
    ("SUNPEN", "Sunday Penalty", "Sunday ordinary hours penalty", "Y", "Penalty", (7, 7), (780, 1180), None, False),
    ("BROKENSHIFT", "Broken Shift Allowance", "Compensation for a split rostered shift", "Y", "Allowance", (4, 6), (60, 150), None, False),
    ("FIRSTAID", "First Aid Allow", "First aid officer allowance", "N", "Allowance", (7, 7), (28, 28), 28.00, False),
    ("FOODHANDLER", "Food Handler Allowance", "Food safety supervisor allowance", "Y", "Allowance", (6, 7), (35, 60), None, False),
    ("KNIFEALLOW", "Knife Allow", "Chef's own knife allowance", "Y", "Allowance", (5, 6), (18, 18), 18.00, False),
    ("LAUNDRYALLOW", "Laundry Allow", "Uniform laundering allowance", "N", "Allowance", (6, 7), (12, 20), None, False),
    ("UNIFORMALLOW", "Uniform Allow", "Flat uniform allowance regardless of expense", "Y", "Allowance", (2, 3), (150, 150), 150.00, False),
    ("MEALALLOWOT", "OT Meal Allow", "Overtime meal allowance", "N", "Allowance", (2, 4), (18, 28), None, True),
    ("OT15", "Overtime 1.5x", "Overtime paid at time and a half", "Y", "Overtime", (3, 5), (180, 520), None, True),
    ("OT20", "Overtime 2x", "Overtime paid at double time", "N", "Overtime", (2, 3), (90, 260), None, True),
    ("ONCALLAH", "On Call After Hours", "On call allowance outside ordinary hours", "N", "Overtime", (1, 2), (40, 80), None, False),
    ("TOILCASHOUT", "TOIL Cashout", "Cash out of time off in lieu", "N", "Leave", (1, 2), (150, 400), None, False),
    ("RDOCASHOUT", "RDO Cashout", "Cash out of a rostered day off, in service", "Y", "Leave", (1, 2), (200, 420), None, False),
    ("ALCASHOUT", "AL Cashout", "Cash out of annual leave, in service", "Y", "Leave", (1, 2), (400, 900), None, False),
    ("ANNLV", "Annual Leave", "Paid annual leave taken", "Y", "Leave", (5, 7), (600, 1600), None, False),
    ("ALLOADING", "AL Loading 17.5%", "Annual leave loading, general case", "Y", "Loading", (5, 7), (105, 280), None, False),
    ("LSLINHOUSE", "Long Service Leave", "Long service leave, not a portable scheme", "Y", "Leave", (1, 2), (1800, 3200), None, False),
    ("SICKLV", "Personal Leave", "Paid personal and carers leave", "Y", "Leave", (5, 7), (250, 900), None, False),
    ("FDVLEAVE", "FDV Leave", "Family and domestic violence leave", "Y", "Leave", (1, 2), (200, 500), None, False),
    ("PPLEMPLOYER", "PPL Employer", "Employer paid parental leave", "N", "Leave", (2, 3), (900, 1800), None, False),
    ("JURYDUTY", "Jury Duty Leave", "Jury duty leave", "N", "Leave", (0, 1), (180, 350), None, False),
    ("WCOMPWORKED", "WComp Light Duties", "Workers compensation, light duties worked", "Y", "Leave", (0, 1), (600, 1100), None, False),
    ("WCOMPNOTWORK", "WComp Not Worked", "Workers compensation, not required to work", "N", "Leave", (1, 2), (600, 1100), None, False),
    ("REFERRALBONUS", "Referral Bonus", "Bonus for referring a new staff member", "Y", "Bonus", (1, 2), (150, 300), None, False),
    ("LOYALTYBON", "Loyalty Bonus", "Discretionary staff loyalty payment", "N", "Bonus", (7, 7), (180, 180), 180.00, False),
    ("STAFFMEAL", "Staff Meal Allow", "Allowance for meals during a shift", "N", "Allowance", (5, 7), (15, 25), None, False),
    ("PILN", "PILN", "Payment in lieu of notice", "Y", "Termination", (0, 1), (900, 2200), None, False),
    ("REDUNDANCY", "Redundancy Pmt", "Genuine redundancy payment", "N", "Termination", (1, 1), (3000, 6000), None, False),
    ("ALTERM", "AL Payout Term", "Unused annual leave paid on termination", "N", "Termination", (1, 1), (800, 1800), None, False),
    ("LSLTERM", "LSL Payout Term", "Unused long service leave paid on termination", "N", "Termination", (1, 1), (1500, 3000), None, False),
    ("RDOTERM", "RDO Payout Term", "Unused RDO paid on termination", "N", "Termination", (0, 1), (150, 400), None, False),
    ("DIRFEE", "Director Fee", "Working director's fee", "Y", "Director", (6, 7), (900, 900), 900.00, False),
    ("STUDYLEAVE", "Study Leave", "Paid study leave for a TAFE course", "Y", "Leave", (1, 1), (150, 350), None, False),
    ("SPECIALLEAVE", "Special Paid Leave", "Compassionate or special paid leave", "Y", "Leave", (1, 1), (200, 500), None, False),
]

ANSWER_KEY = {
    "ORDHRS": ("yes", "S1-T01-R01", False),
    "PHNOTWORKED": ("yes", "S1-T01-R11", False),
    "CASLOAD": ("yes", "S1-T01-R02", False),
    "PHPEN": ("yes", "S1-T01-R03", False),
    "EVEPEN": ("yes", "S1-T01-R03", False),
    "SATPEN": ("yes", "S1-T01-R03", False),
    "SUNPEN": ("yes", "S1-T01-R03", False),
    "BROKENSHIFT": ("yes", "S1-T08-R02", False),
    "FIRSTAID": ("yes", "S1-T08-R02", True),
    "FOODHANDLER": ("yes", "S1-T08-R02", False),
    "KNIFEALLOW": ("no", "S1-T08-R03", True),
    "LAUNDRYALLOW": ("no", "S1-T08-R03", False),
    "UNIFORMALLOW": ("yes", "S1-T08-R04", False),
    "MEALALLOWOT": ("no", "S1-T08-R03", False),
    "OT15": ("no", "S1-T09-R01", True),
    "OT20": ("no", "S1-T09-R01", False),
    "ONCALLAH": ("no", "S1-T09-R04", False),
    "TOILCASHOUT": ("no", "S1-T09-R03", False),
    "RDOCASHOUT": ("yes", "S1-T06-R04", False),
    "ALCASHOUT": ("yes", "S1-T06-R01", False),
    "ANNLV": ("yes", "S1-T02-R01", False),
    "ALLOADING": ("yes", "S1-T02-R03", False),
    "LSLINHOUSE": ("yes", "S1-T02-R04", False),
    "SICKLV": ("yes", "S1-T02-R08", False),
    "FDVLEAVE": ("yes", "S1-T02-R06", False),
    "PPLEMPLOYER": ("no", "S1-T03-R01", False),
    "JURYDUTY": ("no", "S1-T05-R02", False),
    "WCOMPWORKED": ("yes", "S1-T04-R01", False),
    "WCOMPNOTWORK": ("no", "S1-T04-R02", False),
    "REFERRALBONUS": ("yes", "S1-T10-R07", False),
    "LOYALTYBON": ("yes", "S1-T10-R05", True),
    "STAFFMEAL": ("no", "S1-T08-R03", False),
    "PILN": ("yes", "S1-T13-R02", False),
    "REDUNDANCY": ("no", "S1-T13-R05", False),
    "ALTERM": ("no", "S1-T07-R01", False),
    "LSLTERM": ("no", "S1-T07-R02", False),
    "RDOTERM": ("no", "S1-T13-R04", False),
    "DIRFEE": ("yes", "S1-T11-R01", False),
    "STUDYLEAVE": ("yes", "S1-T02-R10", False),
    "SPECIALLEAVE": ("yes", "S1-T02-R11", False),
}

PATTERN_ANOMALY_NOTE = (
    "LOYALTYBON is configured N (excluded), and its name alone is genuinely "
    "ambiguous, a classifier could plausibly call this either yes or unclear. "
    "But it is paid the identical $180 in all seven runs, the signature of "
    "disguised regular wages rather than a genuine discretionary bonus. The "
    "correct verdict is yes on category grounds alone (S1-T10-R05), so this "
    "code is wrong twice over, a straightforward setup error the classifier "
    "should catch, corroborated by a payment pattern a naive classifier "
    "reading only the code name would never see."
)


def choose_contiguous_dates(rng: random.Random, appearances: int) -> list[str]:
    """Selects a contiguous block of pay dates rather than a scattered
    sample. Real payroll usage starts or stops, it doesn't skip fortnights
    at random, and a scattered sample can produce gaps between the chosen
    dates that don't match any real pay cycle, wrongly leaving the code's
    frequency unclassified downstream."""
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
            employees_paid = rng.randint(1, 8)
            overtime_hours = round(rng.uniform(4, 22), 1) if overtime_linked else ""
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
        "business": "cafe",
        "total_codes": len(PAYCODE_DEFINITIONS),
        "planted_setup_errors": planted,
        "planted_pattern_anomalies": ["LOYALTYBON"],
        "pattern_anomaly_note": PATTERN_ANOMALY_NOTE,
        "verdicts": {
            code: {"correct_counts_towards_super": verdict, "ato_citation": citation, "is_planted_error": is_error}
            for code, (verdict, citation, is_error) in ANSWER_KEY.items()
        },
    }
    key_path = ANSWER_KEY_DIR / "cafe_answer_key.json"
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
