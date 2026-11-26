"""A plausible payroll bureau's monthly payroll: PAYE on code 1257L (month 1 basis), Class 1 NI by the exact
percentage method, auto-enrolment pension under a net pay arrangement, and the Employment Allowance.

It is not HMRC's exact tables; the answer key books whatever the bureau's report says."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from testbooks.dates import previous_working_day
from testbooks.engine.model import Employee
from testbooks.money import ZERO, pennies
from testbooks.rules.rates import rate


@dataclass(frozen=True)
class Payslip:
    employee_id: str
    pay_date: date
    gross: Decimal
    tax: Decimal
    ee_ni: Decimal
    er_ni: Decimal
    ee_pension: Decimal
    er_pension: Decimal
    net: Decimal


@dataclass(frozen=True)
class PayRun:
    pay_date: date
    payslips: tuple[Payslip, ...]
    ea_used: Decimal

    @property
    def gross(self) -> Decimal:
        return sum((p.gross for p in self.payslips), ZERO)

    @property
    def net(self) -> Decimal:
        return sum((p.net for p in self.payslips), ZERO)

    @property
    def er_ni(self) -> Decimal:
        return sum((p.er_ni for p in self.payslips), ZERO)

    @property
    def paye(self) -> Decimal:
        """What is paid to HMRC for the month: tax and both NI, less the Employment Allowance used."""
        return sum((p.tax + p.ee_ni + p.er_ni for p in self.payslips), ZERO) - self.ea_used

    @property
    def pension(self) -> Decimal:
        return sum((p.ee_pension + p.er_pension for p in self.payslips), ZERO)


def pay_date_for(year: int, month: int) -> date:
    """Payday is the 28th, or the working day before."""
    return previous_working_day(date(year, month, 28))


def payslip(emp: Employee, pay_date: date, ee_rate: Decimal, er_rate: Decimal) -> Payslip:
    gross = pennies(emp.salary / 12)
    ee_pension = er_pension = ZERO
    if emp.pension:
        qualifying = max(ZERO, min(gross, rate("pension_qe_upper_month", pay_date)) -
                         rate("pension_qe_lower_month", pay_date))
        ee_pension, er_pension = pennies(ee_rate * qualifying), pennies(er_rate * qualifying)
    taxable = max(ZERO, (gross - ee_pension - rate("paye_free_pay_month", pay_date)).quantize(
        Decimal("1"), rounding=ROUND_FLOOR))
    basic_limit = rate("paye_basic_limit_month", pay_date)
    tax = pennies(min(taxable, basic_limit) * rate("income_tax_basic", pay_date) +
                  max(ZERO, taxable - basic_limit) * rate("income_tax_higher", pay_date))
    pt, uel = rate("ni_pt_month", pay_date), rate("ni_uel_month", pay_date)
    ee_ni = pennies(max(ZERO, min(gross, uel) - pt) * rate("ni_employee_main", pay_date) +
                    max(ZERO, gross - uel) * rate("ni_employee_upper", pay_date))
    er_ni = pennies(max(ZERO, gross - rate("ni_st_month", pay_date)) * rate("ni_employer", pay_date))
    net = gross - ee_pension - tax - ee_ni
    return Payslip(emp.id, pay_date, gross, tax, ee_ni, er_ni, ee_pension, er_pension, net)


def pay_year(employees, tax_year_start_year: int, ee_rate: Decimal, er_rate: Decimal) -> list[PayRun]:
    """Twelve monthly runs, April to March. A director's employer NI is trued up in month 12 to the annual figure
    (the employer rate on annual pay above the annual secondary threshold); the Employment Allowance is used up
    run by run from April."""
    months = [(tax_year_start_year, m) for m in range(4, 13)] + [(tax_year_start_year + 1, m) for m in range(1, 4)]
    slips_by_month: list[list[Payslip]] = []
    for year, month in months:
        slips_by_month.append([payslip(e, pay_date_for(year, month), ee_rate, er_rate) for e in employees])
    last = slips_by_month[-1]
    for i, emp in enumerate(employees):
        if not emp.director:
            continue
        mine = [month_slips[i] for month_slips in slips_by_month]
        annual_gross = sum((p.gross for p in mine), ZERO)
        on = last[i].pay_date
        target = pennies(max(ZERO, annual_gross - rate("ni_st_year", on)) * rate("ni_employer", on))
        so_far = sum((p.er_ni for p in mine[:-1]), ZERO)
        p = last[i]
        last[i] = Payslip(p.employee_id, p.pay_date, p.gross, p.tax, p.ee_ni, target - so_far, p.ee_pension,
                          p.er_pension, p.net)
    allowance = rate("employment_allowance", slips_by_month[0][0].pay_date) if employees else ZERO
    runs = []
    for month_slips in slips_by_month:
        er_total = sum((p.er_ni for p in month_slips), ZERO)
        used = min(allowance, er_total)
        allowance -= used
        runs.append(PayRun(month_slips[0].pay_date, tuple(month_slips), used))
    return runs
