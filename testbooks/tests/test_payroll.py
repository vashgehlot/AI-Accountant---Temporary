from datetime import date
from decimal import Decimal as D

from testbooks.engine.model import Employee
from testbooks.rules.payroll import pay_date_for, pay_year, payslip

MEGAN = Employee("e3", "Megan Whitlow", False, D("36000"), True, "QQ123456C")
HANNAH = Employee("d1", "Hannah Finch", True, D("12570"), False, "QQ654321A")


def test_staff_payslip_april_2023():
    p = payslip(MEGAN, date(2023, 4, 28), D("0.05"), D("0.03"))
    assert (p.gross, p.ee_pension, p.tax, p.ee_ni, p.er_ni, p.er_pension, p.net) == (
        D("3000.00"), D("124.00"), D("365.40"), D("234.24"), D("309.40"), D("74.40"), D("2276.36"))


def test_employee_ni_falls_to_10_percent_from_6_january_2024():
    assert payslip(MEGAN, date(2024, 1, 26), D("0.05"), D("0.03")).ee_ni == D("195.20")


def test_pay_dates():
    assert pay_date_for(2023, 5) == date(2023, 5, 26) and pay_date_for(2024, 3) == date(2024, 3, 28)


def test_director_and_employment_allowance_over_the_year():
    runs = pay_year([HANNAH, MEGAN], 2023, D("0.05"), D("0.03"))
    assert len(runs) == 12 and runs[0].pay_date == date(2023, 4, 28)
    director_er = sum(p.er_ni for r in runs for p in r.payslips if p.employee_id == "d1")
    assert director_er == D("478.86")
    total_er = sum(p.er_ni for r in runs for p in r.payslips)
    assert sum(r.ea_used for r in runs) == min(D("5000"), total_er)


def test_run_totals():
    run = pay_year([HANNAH, MEGAN], 2023, D("0.05"), D("0.03"))[0]
    slips = run.payslips
    assert run.gross == sum(p.gross for p in slips) and run.net == sum(p.net for p in slips)
    assert run.paye == sum(p.tax + p.ee_ni + p.er_ni for p in slips) - run.ea_used
    assert run.pension == sum(p.ee_pension + p.er_pension for p in slips)
