# ltd-payroll: how the expected trial balance was worked out

**These two documents are authored test documents, not copies of `eval/fixtures/`.** They test payroll: a payroll
report books the wages as costs, owed until the bank pays them, and the bank lines paying them clear what is owed.

The expected trial balance was worked out by hand from the documents and the booking rules, and is checked by
`tests/test_eval_cases.py`, which feeds the rows a good reading gives through the real API, with a fake model. All
names, reference numbers and amounts are made up for the test.

## The rules

- **The payroll report books the cost.** Each of its rows is out, dated the pay date, with the cost on an expense
  account and the other side on the account that holds what is owed, by what the row is owed to:

  | Owed to | Account holding it |
  |---|---|
  | `net_pay`: the staff | 2220 Net Wages |
  | `paye_ni`: HMRC | 2210 PAYE and National Insurance |
  | `pension`: the pension provider | 2230 Pension Fund |

  The report never touches the bank.
- **The bank lines clear it.** A bank line coded to 2220, 2210 or 2230 debits that account and credits the bank, so
  it clears what the report owed. It books no VAT.
- **Costs:** net pay, employees' tax and NI, and employees' pension together are the gross pay, on 7000 Gross
  Wages. The employer's NI is on 7006 and the employer's pension on 7007, on top of gross pay.

## Client and year

| Setting | Value | Why |
|---|---|---|
| Name | Kestrel Joinery Ltd | The report is for it. |
| Business type | `limited_company` | A limited company. |
| VAT registered | yes | No row shows VAT, so this changes no figure. |
| First year end | 2027-03-31 | The client's first year runs 1 Apr 2026 to 31 Mar 2027, and both documents are in it. |
| Bank accounts | one current account (1200) | |

## Documents (authored)

| File | What it is |
|---|---|
| `documents/payroll-report-october.txt` | Payroll summary, pay date 28/10/2026, two employees. Gross pay 4,000.00; income tax 450.00; employee NI 180.00; employee pension 120.00; net pay 3,250.00 (4,000.00 − 450.00 − 180.00 − 120.00); employer NI 395.00; employer pension 160.00 |
| `documents/current-account-oct-nov.csv` | Bank CSV in the layout of the `csv-starling` fixture, 28/10 to 22/11/2026. Opening balance 12,000.00, five lines with running balances, closing balance 7,438.50 |

## Rows from the payroll report (all out, dated 28/10/2026)

| # | Description | Owed to | Account | Debit | Credit |
|---|---|---|---|---|---|
| P1 | Net pay | net_pay | 7000 | 7000 3,250.00 | 2220 3,250.00 |
| P2 | Income tax 450.00 + employee NI 180.00 | paye_ni | 7000 | 7000 630.00 | 2210 630.00 |
| P3 | Employee pension | pension | 7000 | 7000 120.00 | 2230 120.00 |
| P4 | Employer NI | paye_ni | 7006 | 7006 395.00 | 2210 395.00 |
| P5 | Employer pension | pension | 7007 | 7007 160.00 | 2230 160.00 |

7000 is 3,250.00 + 630.00 + 120.00 = 4,000.00, which is the gross pay. HMRC is owed 630.00 + 395.00 = 1,025.00 and
the pension provider 120.00 + 160.00 = 280.00.

## Rows from the bank statement

| # | Date | Description | Way | Amount | Account | Debit | Credit |
|---|---|---|---|---|---|---|---|
| B1 | 28/10/2026 | Elif Demir, salary October | out | 1,750.00 | 2220 | 2220 1,750.00 | 1200 1,750.00 |
| B2 | 28/10/2026 | Owen Price, salary October | out | 1,500.00 | 2220 | 2220 1,500.00 | 1200 1,500.00 |
| B3 | 30/10/2026 | Bank charges | out | 6.50 | 7901 Bank Charges | 7901 6.50 | 1200 6.50 |
| B4 | 05/11/2026 | Aviva Workplace Pension | out | 280.00 | 2230 | 2230 280.00 | 1200 280.00 |
| B5 | 22/11/2026 | HMRC PAYE | out | 1,025.00 | 2210 | 2210 1,025.00 | 1200 1,025.00 |

B1 and B2 add to the net pay: 1,750.00 + 1,500.00 = 3,250.00. All five dates are in the year to 31 Mar 2027, and
the 22/11 payment is in the month after the report, which is when HMRC is paid.

**Statement check:**

| From | Movement | Balance | Printed |
|---|---|---|---|
| Opening | | 12,000.00 | |
| B1 | −1,750.00 | 10,250.00 | ✓ |
| B2 | −1,500.00 | 8,750.00 | ✓ |
| B3 | −6.50 | 8,743.50 | ✓ |
| B4 | −280.00 | 8,463.50 | ✓ |
| B5 | −1,025.00 | 7,438.50 | ✓ |

The statement reconciles. Its movement is 7,438.50 − 12,000.00 = −4,561.50, which is 1200's net below.

## Per-account sums

| Account | Debits | Credits | Net (Dr − Cr) |
|---|---|---|---|
| 1200 Bank Current Account | | 1,750.00 + 1,500.00 + 6.50 + 280.00 + 1,025.00 = 4,561.50 | **-4561.50** |
| 2210 PAYE and National Insurance | 1,025.00 (B5) | 630.00 (P2) + 395.00 (P4) = 1,025.00 | 0.00, so it is left out |
| 2220 Net Wages | 3,250.00 (B1, B2) | 3,250.00 (P1) | 0.00, so it is left out |
| 2230 Pension Fund | 280.00 (B4) | 120.00 (P3) + 160.00 (P5) = 280.00 | 0.00, so it is left out |
| 7000 Gross Wages | 3,250.00 + 630.00 + 120.00 = 4,000.00 | | **4000.00** |
| 7006 Employer's National Insurance | 395.00 | | **395.00** |
| 7007 Employer's Pension Contributions | 160.00 | | **160.00** |
| 7901 Bank Charges | 6.50 (B3) | | **6.50** |

Check: the debit nets are 4,000.00 + 395.00 + 160.00 + 6.50 = 4,561.50, and the credit net is 4,561.50. The
expected trial balance sums to zero.

## What a wrong result looks like

- **Wages booked from the bank as well as the report** (the bank lines coded to 7000, 7006 or 7007 instead of
  2220, 2210 and 2230): the wages would be counted twice, and 2220, 2210 and 2230 would stay owed.
- **The report not read**: the three payroll accounts would show a debit balance of 4,555.00, and the cost accounts
  nothing.

## Judgement calls

1. **Net pay and the employees' tax, NI and pension are separate rows**, as the reading is asked to give them, all
   on 7000. The report prints the gross pay once, and 7000's total is that gross pay.
2. **The two salary payments go to 2220 one by one**, the way the bank shows them.
3. **No opening balance is entered**, so 1200 shows the year's movement, −4,561.50.
