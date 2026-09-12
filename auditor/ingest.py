"""
auditor/ingest.py

Parses and validates paycodes.csv and payruns.csv against the contract in
data/csv_contract.md. Nothing in this module calculates a dollar figure,
that boundary belongs to impact.py. This module only decides whether the
input is well formed and, where it is, derives the three values a bookkeeper
never supplies directly: pay frequency, pay runs per year, and the average
amount paid per run for each code.

Errors are returned, never raised, so the API layer can turn them into a
structured 422 response instead of a stack trace.
"""

from __future__ import annotations

import csv
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional


# ---- Field level error and warning shapes, mirrors csv_contract.md Section 5 ----

@dataclass
class IngestFieldError:
    file: str
    row: Optional[int]      # None for file level problems such as EMPTY_FILE
    column: Optional[str]
    code: str
    message: str
    value: Optional[str] = None


@dataclass
class IngestWarning:
    file: str
    code: str
    message: str
    detail: Optional[str] = None


# ---- Validated row shapes ----

@dataclass
class PayCodeRow:
    code: str                 # uppercased, used as the join key
    display_code: str         # original casing, for the UI
    name: str
    description: str
    counts_for_super: bool
    payroll_category: str


@dataclass
class PayRunRow:
    pay_date: date
    code: str                 # uppercased, matches PayCodeRow.code
    total_amount: float
    employees_paid: int
    overtime_hours: Optional[float]


@dataclass
class CodeFrequencyProfile:
    """The three derived values from csv_contract.md Section 4, per code."""
    code: str
    pay_frequency: str            # weekly, fortnightly, monthly, unknown
    pay_runs_per_year: Optional[int]
    average_amount_per_run: float
    distinct_pay_dates: int


@dataclass
class IngestResult:
    paycodes: list[PayCodeRow] = field(default_factory=list)
    payruns: list[PayRunRow] = field(default_factory=list)
    frequency_by_code: dict[str, CodeFrequencyProfile] = field(default_factory=dict)
    errors: list[IngestFieldError] = field(default_factory=list)
    warnings: list[IngestWarning] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return len(self.errors) == 0


# ---- Constants pulled straight from the locked contract ----

PAYCODES_REQUIRED = {"code", "name", "counts_for_super"}
PAYCODES_OPTIONAL = {"description", "payroll_category"}
PAYCODES_KNOWN = PAYCODES_REQUIRED | PAYCODES_OPTIONAL

PAYRUNS_REQUIRED = {"pay_date", "code", "total_amount", "employees_paid"}
PAYRUNS_OPTIONAL = {"overtime_hours"}
PAYRUNS_KNOWN = PAYRUNS_REQUIRED | PAYRUNS_OPTIONAL

TRUTHY_VALUES = {"y", "yes", "true", "1", "t"}
FALSY_VALUES = {"n", "no", "false", "0", "f"}

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Header fragments that suggest someone slipped employee level data into an
# aggregated file. Checked against any column name not already whitelisted
# for that file, so "name" on paycodes.csv (the pay code's own name) never
# trips this, but "employee_name" on payruns.csv would.
PII_SUSPECT_FRAGMENTS = (
    "employee_name", "first_name", "last_name", "surname", "given_name",
    "employee_id", "staff_id", "tfn", "abn_holder", "dob", "date_of_birth",
    "medicare", "email", "phone", "address",
)


def _clean_header(raw_header: str) -> str:
    stripped = raw_header.strip().lstrip("\ufeff")  # BOM safe
    return re.sub(r"\s+", "_", stripped).lower()


def _flag_suspicious_headers(headers: list[str], known: set[str], source_file: str) -> list[IngestFieldError]:
    flagged = []
    for header in headers:
        if header in known:
            continue
        if any(fragment in header for fragment in PII_SUSPECT_FRAGMENTS):
            flagged.append(IngestFieldError(
                file=source_file, row=None, column=header, code="PII_SUSPECTED",
                message=f"Column header '{header}' looks like it may hold personal information. "
                        "Only aggregated per-code totals are accepted.",
                value=header,
            ))
    return flagged


def _parse_super_flag(raw_value: str) -> Optional[bool]:
    lowered = raw_value.strip().lower()
    if lowered in TRUTHY_VALUES:
        return True
    if lowered in FALSY_VALUES:
        return False
    return None


def _parse_money(raw_value: str) -> Optional[float]:
    """Strips currency symbols and thousands separators. Parentheses mean
    negative, and negative amounts are rejected upstream with NEGATIVE_AMOUNT
    rather than silently accepted here."""
    trimmed = raw_value.strip()
    if not trimmed:
        return None
    is_parenthetical_negative = trimmed.startswith("(") and trimmed.endswith(")")
    if is_parenthetical_negative:
        trimmed = trimmed[1:-1]
    scrubbed = re.sub(r"[^\d.\-]", "", trimmed)
    if scrubbed in ("", "-", "."):
        return None
    try:
        parsed = float(scrubbed)
    except ValueError:
        return None
    return -abs(parsed) if is_parenthetical_negative else parsed


def _parse_iso_date(raw_value: str) -> Optional[date]:
    trimmed = raw_value.strip()
    if not ISO_DATE_PATTERN.match(trimmed):
        return None
    try:
        return datetime.strptime(trimmed, "%Y-%m-%d").date()
    except ValueError:
        return None


def read_paycodes_csv(file_path: Path) -> tuple[list[PayCodeRow], list[IngestFieldError]]:
    """Parses and validates paycodes.csv. Returns validated rows and any
    field level errors. A row that fails validation is dropped from the
    returned list but its error is preserved, so the caller sees exactly
    what was rejected and why."""

    rows: list[PayCodeRow] = []
    problems: list[IngestFieldError] = []
    file_label = file_path.name

    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            problems.append(IngestFieldError(
                file=file_label, row=None, column=None, code="EMPTY_FILE",
                message="No header row found.",
            ))
            return rows, problems

        raw_headers = [_clean_header(h) for h in reader.fieldnames]
        missing_columns = PAYCODES_REQUIRED - set(raw_headers)
        for missing in sorted(missing_columns):
            problems.append(IngestFieldError(
                file=file_label, row=None, column=missing, code="MISSING_COLUMN",
                message=f"Required column '{missing}' is absent from the header.",
            ))
        problems.extend(_flag_suspicious_headers(raw_headers, PAYCODES_KNOWN, file_label))

        if missing_columns:
            return rows, problems  # cannot safely continue without the required columns

        seen_codes: set[str] = set()
        for line_number, raw_row in enumerate(reader, start=2):  # header is line 1
            normalised_row = {_clean_header(k): (v or "") for k, v in raw_row.items()}

            if not any(value.strip() for value in normalised_row.values()):
                continue  # blank row, skipped silently per the contract

            row_is_valid = True

            code_value = normalised_row.get("code", "").strip()
            if not code_value:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="code", code="MISSING_VALUE",
                    message="code is required.",
                ))
                row_is_valid = False

            name_value = normalised_row.get("name", "").strip()
            if not name_value:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="name", code="MISSING_VALUE",
                    message="name is required.",
                ))
                row_is_valid = False

            super_flag_raw = normalised_row.get("counts_for_super", "").strip()
            super_flag = _parse_super_flag(super_flag_raw)
            if super_flag is None:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="counts_for_super",
                    code="INVALID_ENUM",
                    message=f"Expected Y or N, found '{super_flag_raw}'.",
                    value=super_flag_raw,
                ))
                row_is_valid = False

            if not row_is_valid:
                continue

            uppercased_code = code_value.upper()
            if uppercased_code in seen_codes:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="code", code="DUPLICATE_CODE",
                    message=f"Code '{code_value}' appears more than once in {file_label}.",
                    value=code_value,
                ))
                continue
            seen_codes.add(uppercased_code)

            rows.append(PayCodeRow(
                code=uppercased_code,
                display_code=code_value,
                name=name_value,
                description=normalised_row.get("description", "").strip(),
                counts_for_super=super_flag,
                payroll_category=normalised_row.get("payroll_category", "").strip(),
            ))

    return rows, problems


def read_payruns_csv(
    file_path: Path, known_codes: set[str]
) -> tuple[list[PayRunRow], list[IngestFieldError], list[IngestWarning]]:
    """Parses and validates payruns.csv. known_codes should be the set of
    uppercased codes already validated from paycodes.csv, used to catch
    ORPHAN_CODE references."""

    rows: list[PayRunRow] = []
    problems: list[IngestFieldError] = []
    notices: list[IngestWarning] = []
    file_label = file_path.name

    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            problems.append(IngestFieldError(
                file=file_label, row=None, column=None, code="EMPTY_FILE",
                message="No header row found.",
            ))
            return rows, problems, notices

        raw_headers = [_clean_header(h) for h in reader.fieldnames]
        missing_columns = PAYRUNS_REQUIRED - set(raw_headers)
        for missing in sorted(missing_columns):
            problems.append(IngestFieldError(
                file=file_label, row=None, column=missing, code="MISSING_COLUMN",
                message=f"Required column '{missing}' is absent from the header.",
            ))
        problems.extend(_flag_suspicious_headers(raw_headers, PAYRUNS_KNOWN, file_label))

        if missing_columns:
            return rows, problems, notices

        for line_number, raw_row in enumerate(reader, start=2):
            normalised_row = {_clean_header(k): (v or "") for k, v in raw_row.items()}

            if not any(value.strip() for value in normalised_row.values()):
                continue

            row_is_valid = True

            code_value = normalised_row.get("code", "").strip()
            if not code_value:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="code", code="MISSING_VALUE",
                    message="code is required.",
                ))
                row_is_valid = False
            uppercased_code = code_value.upper()

            if code_value and uppercased_code not in known_codes:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="code", code="ORPHAN_CODE",
                    message=f"Code '{code_value}' is not present in paycodes.csv.",
                    value=code_value,
                ))
                row_is_valid = False

            date_raw = normalised_row.get("pay_date", "").strip()
            parsed_date = _parse_iso_date(date_raw)
            if parsed_date is None:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="pay_date", code="INVALID_DATE",
                    message=f"Expected YYYY-MM-DD, found '{date_raw}'.",
                    value=date_raw,
                ))
                row_is_valid = False

            amount_raw = normalised_row.get("total_amount", "").strip()
            parsed_amount = _parse_money(amount_raw)
            if parsed_amount is None:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="total_amount", code="INVALID_NUMBER",
                    message=f"Could not parse '{amount_raw}' as an amount.",
                    value=amount_raw,
                ))
                row_is_valid = False
            elif parsed_amount < 0:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="total_amount", code="NEGATIVE_AMOUNT",
                    message=f"total_amount cannot be negative, found {parsed_amount}.",
                    value=amount_raw,
                ))
                row_is_valid = False

            headcount_raw = normalised_row.get("employees_paid", "").strip()
            try:
                parsed_headcount = int(headcount_raw)
                if parsed_headcount < 0:
                    raise ValueError
            except ValueError:
                problems.append(IngestFieldError(
                    file=file_label, row=line_number, column="employees_paid", code="INVALID_NUMBER",
                    message=f"Could not parse '{headcount_raw}' as a non-negative whole number.",
                    value=headcount_raw,
                ))
                row_is_valid = False
                parsed_headcount = None

            overtime_raw = normalised_row.get("overtime_hours", "").strip()
            parsed_overtime = None
            if overtime_raw:
                parsed_overtime = _parse_money(overtime_raw)
                if parsed_overtime is None:
                    problems.append(IngestFieldError(
                        file=file_label, row=line_number, column="overtime_hours", code="INVALID_NUMBER",
                        message=f"Could not parse '{overtime_raw}' as a number.",
                        value=overtime_raw,
                    ))
                    row_is_valid = False

            if not row_is_valid:
                continue

            rows.append(PayRunRow(
                pay_date=parsed_date,
                code=uppercased_code,
                total_amount=parsed_amount,
                employees_paid=parsed_headcount,
                overtime_hours=parsed_overtime,
            ))

    return rows, problems, notices


def derive_frequency_profiles(
    payrun_rows: list[PayRunRow], all_known_codes: set[str]
) -> tuple[dict[str, CodeFrequencyProfile], list[IngestWarning]]:
    """Works out pay_frequency, pay_runs_per_year and average_amount_per_run
    for every code, purely from the dates and amounts actually observed.
    Nothing here is supplied by the user, per ADR-B07."""

    profiles: dict[str, CodeFrequencyProfile] = {}
    notices: list[IngestWarning] = []

    rows_by_code: dict[str, list[PayRunRow]] = {}
    for row in payrun_rows:
        rows_by_code.setdefault(row.code, []).append(row)

    for code in sorted(all_known_codes):
        code_rows = rows_by_code.get(code, [])

        if not code_rows:
            notices.append(IngestWarning(
                file="payruns.csv", code="UNUSED_CODE",
                message=f"Code '{code}' is configured but was never paid in any run.",
                detail=code,
            ))
            continue

        distinct_dates = sorted({row.pay_date for row in code_rows})
        total_paid = sum(row.total_amount for row in code_rows)
        average_per_run = total_paid / len(distinct_dates)

        if len(distinct_dates) < 2:
            notices.append(IngestWarning(
                file="payruns.csv", code="SINGLE_PAY_RUN",
                message=f"Only one pay date present for '{code}', frequency cannot be derived.",
                detail=code,
            ))
            profiles[code] = CodeFrequencyProfile(
                code=code, pay_frequency="unknown", pay_runs_per_year=None,
                average_amount_per_run=average_per_run, distinct_pay_dates=1,
            )
            continue

        gaps_in_days = [
            (distinct_dates[i + 1] - distinct_dates[i]).days
            for i in range(len(distinct_dates) - 1)
        ]
        median_gap = statistics.median(gaps_in_days)

        if 6 <= median_gap <= 8:
            frequency, runs_per_year = "weekly", 52
        elif 13 <= median_gap <= 16:
            frequency, runs_per_year = "fortnightly", 26
        elif 27 <= median_gap <= 32:
            frequency, runs_per_year = "monthly", 12
        else:
            frequency, runs_per_year = "unknown", None
            notices.append(IngestWarning(
                file="payruns.csv", code="UNKNOWN_FREQUENCY",
                message=f"Pay date gaps for '{code}' (median {median_gap} days) don't match a known cycle.",
                detail=code,
            ))

        profiles[code] = CodeFrequencyProfile(
            code=code, pay_frequency=frequency, pay_runs_per_year=runs_per_year,
            average_amount_per_run=average_per_run, distinct_pay_dates=len(distinct_dates),
        )

    return profiles, notices


def run_ingest(paycodes_path: Path, payruns_path: Path) -> IngestResult:
    """Top level entry point. Parses both files, cross-validates them, and
    derives frequency profiles. Always returns a result, never raises for
    malformed input, only for missing files or an unreadable encoding."""

    outcome = IngestResult()

    paycode_rows, paycode_errors = read_paycodes_csv(paycodes_path)
    outcome.paycodes = paycode_rows
    outcome.errors.extend(paycode_errors)

    known_codes = {row.code for row in paycode_rows}

    payrun_rows, payrun_errors, payrun_warnings = read_payruns_csv(payruns_path, known_codes)
    outcome.payruns = payrun_rows
    outcome.errors.extend(payrun_errors)
    outcome.warnings.extend(payrun_warnings)

    if paycode_rows:
        frequency_profiles, frequency_warnings = derive_frequency_profiles(payrun_rows, known_codes)
        outcome.frequency_by_code = frequency_profiles
        outcome.warnings.extend(frequency_warnings)

    return outcome