# CSV Input Contract (locked at Hour 2)

Owner: Lane B. Consumed by Lane A (api/) and Lane C (web/).
Any change to this file after Hour 2 requires agreement from all three lanes.

---

## 1. File 1: paycodes.csv

One row per pay code in the client's payroll system.

| Column | Required | Type | Example | Notes |
|---|---|---|---|---|
| code | Yes | string | SUNPEN | Unique within the file. Case preserved for display, uppercased for matching |
| name | Yes | string | Sunday Penalty 175% | Free text, expected to be messy |
| description | No | string | Sunday ordinary hours penalty | Empty string when absent |
| counts_for_super | Yes | enum | Y | The client's current setting. See Section 3 |
| payroll_category | No | string | Allowance | Passed through untouched |

## 2. File 2: payruns.csv

One row per code per pay run. Aggregated totals only.
No employee names, no employee IDs, no per person rows. Rejected if present.

| Column | Required | Type | Example | Notes |
|---|---|---|---|---|
| pay_date | Yes | date | 2026-08-14 | ISO 8601 only, YYYY-MM-DD |
| code | Yes | string | SUNPEN | Must exist in paycodes.csv |
| total_amount | Yes | decimal | 4210.50 | Gross for that code in that run. Non negative |
| employees_paid | Yes | integer | 12 | Headcount receiving the code. Non negative |
| overtime_hours | No | decimal | 36 | Total overtime hours in that run. Blank allowed |

## 3. Value normalisation

Applied by ingest.py before validation. Deterministic, no model involved.

| Field | Rule |
|---|---|
| Header names | Lowercased, whitespace and BOM stripped, internal spaces to underscores |
| code | Trimmed, uppercased for join keys, original retained for display |
| counts_for_super | Accepted truthy: Y, YES, TRUE, 1, T. Accepted falsy: N, NO, FALSE, 0, F. Case insensitive. Anything else is a field error |
| total_amount | Currency symbols, thousands separators and surrounding whitespace stripped. Parentheses mean negative and are rejected with NEGATIVE_AMOUNT |
| pay_date | ISO only. 14/08/2026 is rejected rather than guessed, because day and month order cannot be inferred safely |
| Blank rows | Skipped silently |

## 4. Derived values (never supplied by the user)

| Value | How it is derived |
|---|---|
| pay_frequency | Median gap between distinct sorted pay_date values. 6 to 8 days is weekly, 13 to 16 fortnightly, 27 to 32 monthly, otherwise unknown |
| pay_runs_per_year | weekly 52, fortnightly 26, monthly 12. unknown blocks the impact calculation and raises a warning rather than a guess |
| average_amount_per_run | Sum of total_amount for the code divided by the count of distinct pay dates in the file, not by the number of rows |

## 5. Error contract (for HTTP 422)

ingest.py returns errors, it does not raise. Shape:

    {
      "file": "paycodes.csv",
      "row": 14,
      "column": "counts_for_super",
      "code": "INVALID_ENUM",
      "message": "Expected Y or N, found 'Maybe'",
      "value": "Maybe"
    }

Error codes, fixed at Hour 2:

| Code | Meaning |
|---|---|
| MISSING_COLUMN | A required column is absent from the header |
| MISSING_VALUE | A required cell is empty |
| INVALID_ENUM | counts_for_super outside the accepted set |
| INVALID_DATE | pay_date not ISO 8601 |
| INVALID_NUMBER | Amount or headcount not parseable |
| NEGATIVE_AMOUNT | Amount below zero |
| DUPLICATE_CODE | Same code twice in paycodes.csv |
| ORPHAN_CODE | payruns.csv references a code absent from paycodes.csv |
| PII_SUSPECTED | A column header matching a name or ID pattern was found |
| EMPTY_FILE | No data rows after the header |

Warnings (non blocking, surfaced to the reviewer):

| Code | Meaning |
|---|---|
| UNUSED_CODE | Code configured but never paid in any run |
| SINGLE_PAY_RUN | Only one pay date present, so frequency cannot be derived |
| UNKNOWN_FREQUENCY | Pay date gaps do not match a known cycle |
