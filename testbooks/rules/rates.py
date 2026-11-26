"""Every rate the generator uses, each applied from its own date, with its source.

Values come from research_notes/test-corpus/uk-banks-and-tax-facts.md (sections 2.2, 3.1, 3.2 and 3.5)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

_START = date(2023, 1, 1)

_PAYROLL = "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2023-to-2024"
_PAYROLL_25 = "https://www.gov.uk/guidance/rates-and-thresholds-for-employers-2025-to-2026"
_INCOME_TAX = ("https://www.gov.uk/government/publications/rates-and-allowances-income-tax/"
               "income-tax-rates-and-allowances-current-and-past")
_CT = "https://www.gov.uk/government/publications/rates-and-allowances-corporation-tax/rates-and-allowances-corporation-tax"
_CT_MR = "https://www.gov.uk/guidance/corporation-tax-marginal-relief"
_VAT_RATES = "https://www.gov.uk/guidance/rates-of-vat-on-different-goods-and-services"
_VAT_THRESHOLD = ("https://gov.uk/government/publications/vat-increasing-the-registration-and-deregistration-"
                  "thresholds/increasing-the-vat-registration-threshold")
_PENSION = ("https://www.thepensionsregulator.gov.uk/employers/new-employers/im-an-employer-who-has-to-provide-a-"
            "pension/declare-your-compliance/ongoing-duties-for-employers/earnings-thresholds")
_MILEAGE = ("https://www.gov.uk/government/publications/increase-to-approved-mileage-allowance-payments-amaps-and-"
            "self-employed-simplified-mileage-rates/increasing-mileage-rates")
_S455 = ("https://www.gov.uk/government/publications/changes-to-tax-rates-for-property-savings-and-dividend-income/"
         "change-to-tax-rates-for-property-savings-and-dividend-income-technical-note")


def _d(iso: str) -> date:
    return date.fromisoformat(iso)


# name -> (source, [(from, value), ...] ascending)
_TABLE: dict[str, tuple[str, list[tuple[date, str]]]] = {
    "vat_standard": (_VAT_RATES, [(_START, "0.20")]),
    "vat_reduced": (_VAT_RATES, [(_START, "0.05")]),
    "vat_threshold": (_VAT_THRESHOLD, [(_START, "85000"), (_d("2024-04-01"), "90000")]),
    "ni_employee_main": (_PAYROLL, [(_START, "0.12"), (_d("2024-01-06"), "0.10"), (_d("2024-04-06"), "0.08")]),
    "ni_employee_upper": (_PAYROLL, [(_START, "0.02")]),
    "ni_employer": (_PAYROLL_25, [(_START, "0.138"), (_d("2025-04-06"), "0.15")]),
    "ni_pt_month": (_PAYROLL, [(_START, "1048")]),
    "ni_uel_month": (_PAYROLL, [(_START, "4189")]),
    "ni_st_month": (_PAYROLL_25, [(_START, "758"), (_d("2025-04-06"), "417")]),
    "ni_pt_year": (_PAYROLL, [(_START, "12570")]),
    "ni_st_year": (_PAYROLL_25, [(_START, "9100"), (_d("2025-04-06"), "5000")]),
    "employment_allowance": (_PAYROLL_25, [(_START, "5000"), (_d("2025-04-06"), "10500")]),
    "paye_free_pay_month": (_INCOME_TAX, [(_START, "1048.25")]),
    "paye_basic_limit_month": (_INCOME_TAX, [(_START, "3142")]),
    "income_tax_basic": (_INCOME_TAX, [(_START, "0.20")]),
    "income_tax_higher": (_INCOME_TAX, [(_START, "0.40")]),
    "pension_qe_lower_month": (_PENSION, [(_START, "520")]),
    "pension_qe_upper_month": (_PENSION, [(_START, "4189")]),
    "ct_small": (_CT, [(_START, "0.19")]),
    "ct_main": (_CT, [(_START, "0.25")]),
    "ct_lower": (_CT_MR, [(_START, "50000")]),
    "ct_upper": (_CT_MR, [(_START, "250000")]),
    "ct_mr_fraction": (_CT_MR, [(_START, "0.015")]),
    "mileage_car_first": (_MILEAGE, [(_START, "0.45"), (_d("2026-04-06"), "0.55")]),
    "mileage_car_after": (_MILEAGE, [(_START, "0.25")]),
    "s455": (_S455, [(_START, "0.3375"), (_d("2026-04-06"), "0.3575")]),
}

RATE_SOURCES: dict[str, str] = {name: source for name, (source, _) in _TABLE.items()}


def rate(name: str, on: date) -> Decimal:
    """The rate in force on `on`: the latest entry from on or before that day."""
    _, steps = _TABLE[name]
    if on < steps[0][0]:
        raise ValueError(f"{name}: no rate before {steps[0][0]}")
    value = steps[0][1]
    for start, v in steps:
        if start <= on:
            value = v
    return Decimal(value)
