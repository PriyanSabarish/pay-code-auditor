"""
auditor/knowledge/build_construction_sample.py

Generates the construction sample business: paycodes.csv, payruns.csv, and a
private answer key kept entirely outside the git working tree. Modelled
loosely on the Building and Construction General On-site Award MA000020,
named in sources.md but not downloaded.

Three genuine setup errors: LSLPORTABLE is a pure category trap, portable
long service leave under a scheme like CoINVEST is excluded, mirroring
dev_set.csv's isolated label but here misconfigured inside a full business.
HEIGHTSALLOW is a plain underpayment, an adverse conditions allowance wrongly
excluded. PRODUCTIVITYBON is both a setup error and a genuine payment
pattern anomaly, its amount is generated as a function of overtime_hours
each run, the actual signature of a disguised overtime payment wrongly
configured to count.

One deliberate decoy, not an error: TOOLALLOWFLAT is correctly excluded, a
genuinely fully expended tool allowance, but it is paid the identical amount
regardless of how much the crew size varies run to run, which superficially
matches the same suspicious flat-payment shape as a genuine anomaly. This
exists specifically to test whether the pattern check produces a false
alarm on a clean code, since the eval harness measures that honestly rather
than only counting hits.

Run from the repo root:  python auditor/knowledge/build_construction_sample.py
"""

import csv
import json
import pathlib
import random

OUTPUT_DIR = pathlib.Path("data/samples/construction")
ANSWER_KEY_DIR = pathlib.Path.home() / "pay-code-auditor-private" / "answer-keys"

PAY_DATES = [
    "2026-06-19", "2026-07-03", "2026-07-17", "2026-07-31",
    "2026-08-14", "2026-08-28", "2026-09-11",
]

GENERATOR_SEED = 20260715  # distinct from cafe (...713) and retail (...714)

# Codes flagged here get their amount generated as base_rate * that run's
# overtime_hours, rather than an independent random draw, so their payment
# history genuinely correlates with overtime worked. This is the mechanism
# behind the pattern anomaly, not just a label on an otherwise random number.
OVERTIME_CORRELATED_CODES = {"PRODUCTIVITYBON": 14.50}  # dollars per overtime hour

PAYCODE_DEFINITIONS = [
    ("ORDHRS", "Ordinary Hours", "Base ordinary hours across all trades", "Y", "Wages", (7, 7), (32000, 42000), None, False),
    ("RDOACCRUAL", "RDO Hours Worked", "Ordinary hours worked that accrue an RDO", "Y", "Wages", (7, 7), (2200, 3400), None, False),
    ("SATPEN", "Saturday Penalty 150%", "Saturday ordinary hours penalty", "Y", "Penalty", (5, 6), (1400, 2400), None, False),
    ("SUNPEN", "Sunday Penalty 200%", "Sunday ordinary hours penalty", "Y", "Penalty", (2, 3), (900, 1800), None, False),
    ("WETWEATHER", "Wet Weather Payment", "Ordinary rate paid when stood down for wet weather", "Y", "Allowance", (2, 4), (400, 900), None, False),
    ("HEIGHTSALLOW", "Heights Allow", "Allowance for work at height above 3 metres", "N", "Allowance", (5, 7), (60, 140), None, False),
    ("CONFINEDALLOW", "Confined Space Allow", "Allowance for work in a confined space", "Y", "Allowance", (2, 4), (70, 160), None, False),
    ("LEADHANDALLOW", "Leading Hand Allow", "Leading hand allowance for crew supervision", "Y", "Allowance", (6, 7), (90, 180), None, False),
    ("FIRSTAID", "First Aid Officer", "First aid officer allowance", "Y", "Allowance", (6, 7), (25, 25), 25.00, False),
    ("TRAVELALLOW", "Travel Allow", "Fares and travel allowance to site", "Y", "Allowance", (7, 7), (55, 55), 55.00, False),
    ("TOOLALLOWFLAT", "Tool Allow", "Tool allowance, fully expended on trade tools", "N", "Allowance", (6, 7), (32, 32), 32.00, False),
    ("PPEALLOW", "PPE Allow", "Reimbursement for required personal protective equipment", "N", "Allowance", (2, 4), (40, 120), None, False),
    ("APPRENTICEALLOW", "Apprentice Tool Allow", "Apprentice tool allowance, fully expended", "N", "Allowance", (3, 5), (20, 20), 20.00, False),
    ("OT15", "Overtime 1.5x", "Overtime paid at time and a half", "Y", "Overtime", (3, 5), (400, 1100), None, True),
    ("OT20", "Overtime 2x", "Overtime paid at double time", "N", "Overtime", (2, 3), (200, 600), None, True),
    ("PRODUCTIVITYBON", "Productivity Bonus", "Site productivity bonus, ordinary hours", "Y", "Bonus", (5, 6), (0, 0), None, True),
    ("ONCALLAH", "On Call After Hours", "On call allowance outside ordinary hours", "N", "Overtime", (1, 2), (50, 100), None, False),
    ("TOILCASHOUT", "TOIL Cashout", "Cash out of time off in lieu", "N", "Leave", (1, 1), (200, 450), None, False),
    ("RDOCASHOUT", "RDO Cashout", "Cash out of an accrued RDO, in service", "Y", "Leave", (1, 2), (350, 700), None, False),
    ("ALCASHOUT", "AL Cashout", "Cash out of annual leave, in service", "Y", "Leave", (1, 2), (700, 1500), None, False),
    ("ANNLV", "Annual Leave", "Paid annual leave taken", "Y", "Leave", (4, 6), (1200, 2800), None, False),
    ("ALLOADING", "AL Loading 17.5%", "Annual leave loading, general case", "Y", "Loading", (4, 6), (200, 500), None, False),
    ("LSLINHOUSE", "Long Service Leave", "Long service leave, not a portable scheme", "Y", "Leave", (1, 1), (2800, 4500), None, False),
    ("LSLPORTABLE", "LSL Portable Scheme", "Long service leave paid through the industry portable scheme", "Y", "Leave", (1, 1), (2800, 4500), None, False),
    ("SICKLV", "Personal Leave", "Paid personal and carers leave", "Y", "Leave", (4, 6), (400, 1300), None, False),
    ("FDVLEAVE", "FDV Leave", "Family and domestic violence leave", "Y", "Leave", (1, 1), (250, 550), None, False),
    ("JURYDUTY", "Jury Duty Leave", "Jury duty leave", "N", "Leave", (0, 1), (150, 300), None, False),
    ("WCOMPWORKED", "WComp Light Duties", "Workers compensation, light duties worked", "Y", "Leave", (0, 1), (900, 1600), None, False),
    ("WCOMPNOTWORK", "WComp Not Worked", "Workers compensation, not required to work", "N", "Leave", (1, 1), (900, 1600), None, False),
    ("SIGNONBONUS", "Sign On Bonus", "Sign on bonus for a new site hire", "Y", "Bonus", (1, 1), (500, 1200), None, False),
    ("REFERRALBONUS", "Staff Referral Bonus", "Bonus for referring a qualified tradesperson", "Y", "Bonus", (1, 2), (200, 400), None, False),
    ("DIRFEE", "Director Fee", "Working director's fee", "Y", "Director", (6, 7), (1400, 1400), 1400.00, False),
    ("STUDYLEAVE", "Study Leave", "Paid study leave for a trade certificate", "Y", "Leave", (1, 1), (180, 380), None, False),
    ("SPECIALLEAVE", "Special Paid Leave", "Compassionate or special paid leave", "Y", "Leave", (1, 1), (250, 500), None, False),
    ("PILN", "PILN", "Payment in lieu of notice", "Y", "Termination", (0, 1), (1500, 3200), None, False),
    ("REDUNDANCY", "Redundancy Pmt", "Genuine redundancy payment", "N", "Termination", (1, 1), (4000, 9000), None, False),
    ("ALTERM", "AL Payout Term", "Unused annual leave paid on termination", "N", "Termination", (1, 1), (1200, 2600), None, False),
    ("LSLTERM", "LSL Payout Term", "Unused long service leave paid on termination", "N", "Termination", (1, 1), (2000, 4000), None, False),
    ("RDOTERM", "RDO Payout Term", "Unused RDO paid on termination", "N", "Termination", (0, 1), (250, 550), None, False),
    ("SUPERVISORALLOW", "Site Supervisor Allow", "Ongoing site supervision allowance", "Y", "Allowance", (5, 7), (100, 220), None, False),
]

ANSWER_KEY = {
    "ORDHRS": ("yes", "S1-T01-R01", False, False),
    "RDOACCRUAL": ("yes", "S1-T01-R01", False, False),
    "SATPEN": ("yes", "S1-T01-R03", False, False),
    "SUNPEN": ("yes", "S1-T01-R03", False, False),
    "WETWEATHER": ("yes", "S1-T01-R01", False, False),
    "HEIGHTSALLOW": ("yes", "S1-T08-R02", True, False),
    "CONFINEDALLOW": ("yes", "S1-T08-R02", False, False),
    "LEADHANDALLOW": ("yes", "S1-T08-R02", False, False),
    "FIRSTAID": ("yes", "S1-T08-R02", False, False),
    "TRAVELALLOW": ("yes", "S1-T08-R04", False, False),
    "TOOLALLOWFLAT": ("no", "S1-T08-R03", False, True),
    "PPEALLOW": ("no", "S1-T08-R03", False, False),
    "APPRENTICEALLOW": ("no", "S1-T08-R03", False, False),
    "OT15": ("no", "S1-T09-R01", False, False),
    "OT20": ("no", "S1-T09-R01", False, False),
    "PRODUCTIVITYBON": ("no", "S1-T09-R01", True, False),
    "ONCALLAH": ("no", "S1-T09-R04", False, False),
    "TOILCASHOUT": ("no", "S1-T09-R03", False, False),
    "RDOCASHOUT": ("yes", "S1-T06-R04", False, False),
    "ALCASHOUT": ("yes", "S1-T06-R01", False, False),
    "ANNLV": ("yes", "S1-T02-R01", False, False),
    "ALLOADING": ("yes", "S1-T02-R03", False, False),
    "LSLINHOUSE": ("yes", "S1-T02-R04", False, False),
    "LSLPORTABLE": ("no", "S1-T02-R05", True, False),
    "SICKLV": ("yes", "S1-T02-R08", False, False),
    "FDVLEAVE": ("yes", "S1-T02-R06", False, False),
    "JURYDUTY": ("no", "S1-T05-R02", False, False),
    "WCOMPWORKED": ("yes", "S1-T04-R01", False, False),
    "WCOMPNOTWORK": ("no", "S1-T04-R02", False, False),
    "SIGNONBONUS": ("yes", "S1-T10-R06", False, False),
    "REFERRALBONUS": ("yes", "S1-T10-R07", False, False),
    "DIRFEE": ("yes", "S1-T11-R01", False, False),
    "STUDYLEAVE": ("yes", "S1-T02-R10", False, False),
    "SPECIALLEAVE": ("yes", "S1-T02-R11", False, False),
    "PILN": ("yes", "S1-T13-R02", False, False),
    "REDUNDANCY": ("no", "S1-T13-R05", False, False),
    "ALTERM": ("no", "S1-T07-R01", False, False),
    "LSLTERM": ("no", "S1-T07-R02", False, False),
    "RDOTERM": ("no", "S1-T13-R04", False, False),
    "SUPERVISORALLOW": ("yes", "S1-T08-R02", False, False),
}
# tuple shape: (correct_verdict, ato_citation, is_planted_error, is_decoy)

PATTERN_ANOMALY_NOTE = (
    "PRODUCTIVITYBON is configured Y and named like an ordinary hours "
    "performance bonus, which reads as plausible on category alone. But its "
    "amount is generated directly from each run's overtime hours, the "
    "actual signature of a disguised overtime payment, which is excluded "
    "under S1-T09-R01. A setup error and a genuine usage pattern anomaly "
    "on the same code."
)

DECOY_NOTE = (
    "TOOLALLOWFLAT is correctly excluded, a genuine fully expended tool "
    "allowance under S1-T08-R03. It is deliberately included because it "
    "is paid the identical $32 regardless of how much the crew size varies "
    "run to run, the same superficial shape as a genuine flat-payment "
    "anomaly. This is not an error, it exists to test whether the pattern "
    "check produces a false alarm on a code that is actually configured "
    "correctly."
)


def choose_contiguous_dates(rng: random.Random, appearances: int) -> list[str]:
    if appearances <= 0:
        return []
    if appearances >= len(PAY_DATES):
        return list(PAY_DATES)
    latest_valid_start = len(PAY_DATES) - appearances
    start_index = rng.randint(0, latest_valid_start)
    return PAY_DATES[start_index:start_index + appearances]


def build_paycodes_csv() -> list[dict]:
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
            # A construction crew's headcount swings more than a retail
            # or cafe roster, which is exactly what makes TOOLALLOWFLAT's
            # flat amount despite that swing a meaningful decoy signal.
            employees_paid = rng.randint(2, 15)
            overtime_hours = round(rng.uniform(3, 20), 1) if overtime_linked else ""

            if code in OVERTIME_CORRELATED_CODES:
                rate_per_hour = OVERTIME_CORRELATED_CODES[code]
                noise = rng.uniform(0.92, 1.08)  # realistic variance, not a perfectly clean line
                amount = round(overtime_hours * rate_per_hour * noise, 2)
            elif flat_amount is not None:
                amount = flat_amount
            else:
                amount = round(rng.uniform(*amount_range), 2)

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
    planted = [c for c, (_, _, is_error, _) in ANSWER_KEY.items() if is_error]
    decoys = [c for c, (_, _, _, is_decoy) in ANSWER_KEY.items() if is_decoy]
    payload = {
        "business": "construction",
        "total_codes": len(PAYCODE_DEFINITIONS),
        "planted_setup_errors": planted,
        "planted_pattern_anomalies": ["PRODUCTIVITYBON"],
        "pattern_anomaly_note": PATTERN_ANOMALY_NOTE,
        "decoys_not_errors": decoys,
        "decoy_note": DECOY_NOTE,
        "verdicts": {
            code: {
                "correct_counts_towards_super": verdict, "ato_citation": citation,
                "is_planted_error": is_error, "is_decoy": is_decoy,
            }
            for code, (verdict, citation, is_error, is_decoy) in ANSWER_KEY.items()
        },
    }
    key_path = ANSWER_KEY_DIR / "construction_answer_key.json"
    key_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Private answer key written to {key_path} (outside the git working tree)")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(GENERATOR_SEED)

    paycode_rows = build_paycodes_csv()
    payrun_rows = build_payruns_csv(rng)
    build_answer_key()

    print(f"Wrote {len(paycode_rows)} pay codes to {OUTPUT_DIR / 'paycodes.csv'}")
    print(f"Wrote {len(payrun_rows)} pay run rows to {OUTPUT_DIR / 'payruns.csv'}")
    print(f"Planted setup errors: {[c for c, (_, _, e, _) in ANSWER_KEY.items() if e]}")
    print(f"Decoys (not errors): {[c for c, (_, _, _, d) in ANSWER_KEY.items() if d]}")


if __name__ == "__main__":
    main()
