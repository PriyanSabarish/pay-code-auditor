# Knowledge Sources

Every source used to label pay codes or to ground a classification is listed
here with its URL and retrieval date. When a source changes, re download it,
update the retrieval date, and re run the evaluation.

Raw captures live in auditor/knowledge/raw/ and are not edited by hand.

---

## S1. ATO — What payments are qualifying earnings

| Field | Value |
|---|---|
| Source ID | S1 |
| Publisher | Australian Taxation Office |
| URL | https://www.ato.gov.au/businesses-and-organisations/super-for-employers/paying-super-on-payday/what-payments-are-qualifying-earnings |
| ATO quick code | QC105843 |
| Page last updated | 2 September 2026 |
| Retrieved | 2026-09-12 |
| URL status | Verified live 2026-09-12 |
| Licence | Commonwealth of Australia, copying and adaptation permitted, no implied endorsement |
| Role | Primary authority. Every classification cites a table row from this page |

Fourteen tables on this page, chunked at Hour 9 with the ID scheme
S1-T<table_number>-R<row_number>, for example S1-T08-R03 means source S1,
table 8, row 3. That ID is what the model cites, what the labelled datasets
reference, and what the UI shows the bookkeeper.

Table index: T01 Gross, T02 Other paid leave, T03 Paid parental leave,
T04 Workers compensation, T05 Ancillary and defence leave, T06 Cash out of
leave in service, T07 Unused leave on termination, T08 Allowances,
T09 Overtime, T10 Bonuses and commissions, T11 Directors fees,
T12 Return to work payments, T13 Termination payments, T14 Salary sacrifice.

---

## S2. ATO — Law Companion Ruling LCR 2026/D1

| Field | Value |
|---|---|
| Source ID | S2 |
| URL | https://www.ato.gov.au/law/view/document?DocID=COD/LCR2026D1/NAT/ATO/00001&PiT=99991231235958 |
| Retrieved | pending, run fetch_sources.py |
| URL status | Link taken directly from the S1 allowances section, 2026-09-12 |
| Role | Worked examples for the hardest category in the audit, whether an expense allowance is expected to be fully expended. S1 points here explicitly |

---

## S3. ATO — SGR 2009/2, meaning of ordinary time earnings

| Field | Value |
|---|---|
| Source ID | S3 |
| URL | to be recorded from the ATO Legal Database: https://www.ato.gov.au/single-page-applications/legaldatabase |
| Retrieved | pending, manual download required |
| URL status | Deep link not yet confirmed, record the exact URL you land on |
| Role | Underpins the ordinary time earnings layer that qualifying earnings is built on. Relevant to leave loading referable to lost overtime, and to the ordinary hours test where an award does not state them |

---

## S4. Modern award

| Field | Value |
|---|---|
| Source ID | S4 |
| Proposed | Hospitality Industry (General) Award, MA000009 |
| URL | https://awards.fairwork.gov.au/MA000009.html |
| Retrieved | pending, run fetch_sources.py |
| URL status | Constructed from the Fair Work award URL pattern, confirm before relying on it |
| Role | Supplies the ordinary hours span and real allowance names for the cafe sample business, so the synthetic data reflects an actual award rather than invention |

Chosen because the cafe is the business used in the demo video. Retail
(MA000004) and Construction (MA000020) are named in the sample data but not
downloaded, and the README states that plainly.

---

## Corrections to the project spec's rule summary

Checked against S1 on 2026-09-12. The ATO page governs over the spec summary
wherever they disagree.

| Spec said | S1 actually says | Consequence |
|---|---|---|
| Commissions for work entirely outside ordinary hours simply count | They are not ordinary time earnings but are qualifying earnings, Table 10. OTE and QE are two separate columns on the ATO page, not one verdict | The label schema needs both an ote field and a qe field, otherwise the tool cannot explain why a code counts |
| RDO payout is unclear | Cash out of an RDO in service counts, Table 6. An unused RDO paid on termination does not, Table 13 | Still correctly unclear from the code name alone, but now unclear for a documented reason with two cited rows, a stronger review prompt |
| Not mentioned | Workers compensation splits: counts for hours worked or required to attend, does not count when not required to work, Table 4 | Needs a labelled pair in the dev set |

Two further items the spec omits, both belong in the dev set: family and
domestic violence leave counts (Table 2), and annual leave loading counts
unless clearly linked to lost overtime (Table 2).
