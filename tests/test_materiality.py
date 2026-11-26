import datetime as dt
from decimal import Decimal

from ledgersync.checks import normalise
from ledgersync.materiality import levels, year_levels
from ledgersync.models import BusinessSettings, Transaction, Year

D = Decimal


def test_a_profitable_client_takes_5_percent_of_profit():
    got = levels(D("100000"), D("70000"), which="last year")
    assert (got.overall, got.working, got.trivial, got.benchmark) == (D("1500.00"), D("750.00"), D("45.00"), "profit")
    assert got.basis == "5% of profit before tax, £30,000.00, last year"


def test_a_loss_making_client_takes_1_percent_of_costs():
    got = levels(D("10000"), D("20000"), which="last year")
    assert (got.overall, got.benchmark) == (D("200.00"), "costs")


def test_no_figures_give_no_levels_so_everything_is_asked():
    assert levels(D("0"), D("0"), which="this year") is None


def test_part_of_a_year_is_scaled_to_twelve_months():
    got = levels(D("15000"), D("9000"), months=6, which="this year so far")
    assert got.overall == D("600.00") and "scaled to 12 months" in got.basis


def test_the_firms_figure_sets_the_levels():
    got = levels(D("100000"), D("70000"), which="last year", firm=D("2000"))
    assert (got.overall, got.working, got.trivial, got.benchmark) == (D("2000.00"), D("1000.00"), D("60.00"), "firm")
    assert got.basis == "set by the firm"


YEARS = [Year(start=dt.date(2025, 5, 2), end=dt.date(2026, 5, 1), label="2026"),
         Year(start=dt.date(2026, 5, 2), end=dt.date(2027, 5, 1), label="2027")]


def booked(day, gross, account, direction="out"):
    return normalise(Transaction(date=day, gross=gross, account_code=account, direction=direction,
                                 document_type="statement"), BusinessSettings())


def test_a_years_levels_come_from_the_year_before_when_it_has_figures():
    rows = [booked(dt.date(2025, 6, 1), "100000", "4000", "in"), booked(dt.date(2025, 7, 1), "70000", "7100"),
            booked(dt.date(2026, 6, 1), "5000", "4000", "in")]
    got = year_levels(rows, [0, 0, 1], YEARS, 1, None)
    assert got.overall == D("1500.00") and got.basis.endswith("last year")


def test_a_year_with_no_income_booked_says_nothing_of_the_clients_size():
    # Only expense claims in so far: their costs aren't the business's, so the firm is asked for a figure.
    claims = [booked(dt.date(2026, 10, 2), "62.50", "7400"), booked(dt.date(2026, 10, 8), "3.99", "7406")]
    assert year_levels(claims, [1, 1], YEARS, 1, None) is None
    last_year = [booked(dt.date(2025, 10, 2), "500", "7400"), *claims]
    assert year_levels(last_year, [0, 1, 1], YEARS, 1, None) is None
    assert year_levels(claims, [1, 1], YEARS, 1, D("1000")).overall == D("1000.00")


def test_a_first_year_is_worked_out_from_itself_so_far():
    rows = [booked(dt.date(2026, 6, 1), "15000", "4000", "in"), booked(dt.date(2026, 10, 20), "9000", "7100")]
    got = year_levels(rows, [1, 1], YEARS, 1, None)
    assert got.overall == D("600.00") and "this year so far" in got.basis


def test_a_sale_and_the_payment_of_it_count_once():
    # The agency run: each invoice and the bank line that paid it were both counted, so income came to £1.27m and
    # profit to £569,094.74 against the books' £138,818.83. A payment posts against Debtors or Creditors, not to
    # income or costs.
    from ledgersync.matching import match
    settings = BusinessSettings()
    def doc(day, gross, account, direction, kind, who):
        return normalise(Transaction(date=day, gross=gross, account_code=account, direction=direction,
                                     document_type=kind, counterparty=who, document_ref=f"{who}-{kind}"), settings)
    rows = match([doc(dt.date(2026, 6, 1), "15000", "4000", "in", "invoice", "Brightwater"),
                  doc(dt.date(2026, 6, 20), "15000", "4000", "in", "statement", "Brightwater"),
                  doc(dt.date(2026, 7, 1), "9000", "7100", "out", "invoice", "Harbourside"),
                  doc(dt.date(2026, 7, 10), "9000", "7100", "out", "statement", "Harbourside")], settings)
    assert rows[1].paid_against == "1100" and rows[3].paid_against == "2100"   # the bank lines pay the documents
    got = year_levels(rows, [1, 1, 1, 1], YEARS, 1, None)
    # 15,000 less 9,000, in the year's first 3 months (it starts 2 May; the latest row is July): £24,000 a year
    assert got.figure == D("24000.00") and got.overall == D("1200.00")


# Presentation questions: asked from the client's trivial level, left below it with a note saying so.
from ledgersync.materiality import Levels, decide  # noqa: E402

LV = Levels(overall=D("1500"), working=D("750"), trivial=D("45"), benchmark="profit", basis="test")
YEAR_END = BusinessSettings(period_start=dt.date(2026, 5, 2), period_end=dt.date(2027, 5, 1))


def bill(gross, account, **kw):
    return normalise(Transaction(date=kw.pop("date", dt.date(2026, 9, 1)), gross=gross, account_code=account,
                                 direction="out", document_type="receipt", description=kw.pop("description", "x"),
                                 **kw), YEAR_END)


def decided(*rows, levels=LV):
    return decide(list(rows), [1] * len(rows), {1: levels})


def codes(t):
    return [(i.code, i.severity) for i in t.issues]


def test_sundry_under_the_trivial_level_is_left_and_says_so():
    [small] = decided(bill("6.99", "8207"))
    assert codes(small) == [("left_small", "info")]
    assert small.issues[0].message == ("£6.99 is under this client's trivial level of £45.00: left on Sundry Expenses "
                                       "as coded.")
    [big] = decided(bill("60.00", "8207"))
    assert codes(big) == [("sundry_check", "warning")]


def test_with_no_levels_a_presentation_question_waits_for_the_firms_figure():
    [t] = decided(bill("60.00", "8207"), levels=None)
    assert codes(t) == [("left_unset", "info")]
    assert t.issues[0].message.startswith("Left on Sundry Expenses as coded until this client's materiality is set "
                                          "(in the client's details): ")
    [cable] = decided(bill("9.67", "0030"), levels=None)
    assert codes(cable) == [("left_unset", "info")]


def test_a_small_asset_is_asked_about_under_the_working_level():
    # The line between worth keeping as an asset and not is the working level, as for equipment kept as a cost: a
    # £12.99 mouse on Office Equipment is asked about for a client whose trivial level is £12.60 (accountant cases).
    assert codes(decided(bill("30.00", "0030"))[0]) == [("small_asset", "warning")]
    assert codes(decided(bill("200.00", "0030"))[0]) == [("small_asset", "warning")]
    assert codes(decided(bill("800.00", "0030"))[0]) == []


def test_equipment_on_a_cost_account_is_asked_about_from_the_working_level():
    assert ("asset_check", "warning") in codes(decided(bill("800.00", "7504", alternatives=["0030"]))[0])
    assert codes(decided(bill("700.00", "7504", alternatives=["0030"]))[0]) == [("left_small", "info")]


def test_an_annual_bill_asks_about_the_part_after_the_year_end():
    [big] = decided(bill("1200.00", "8204", date=dt.date(2026, 11, 1)))
    assert codes(big) == [("prepayment", "warning")] and "£601.64" in big.issues[0].message
    [small] = decided(bill("60.00", "8204", date=dt.date(2026, 11, 1)))
    assert codes(small) == [("left_small", "info")]


def test_small_items_left_on_one_account_are_asked_about_together_when_they_add_up():
    rows = decided(*(bill("40.00", "8207") for _ in range(19)), bill("39.00", "8207"))
    together = [i for t in rows for i in t.issues if i.code == "small_items_add_up"]
    assert len(together) == 1 and "£799.00" in together[0].message and len(together[0].related) == 19


def test_an_accepted_question_is_neither_asked_nor_left():
    [t] = decided(bill("6.99", "8207", accepted=["sundry_check"]))
    assert codes(t) == []


def test_small_items_a_person_said_are_fine_together_are_not_asked_again():
    rows = decided(*(bill("40.00", "8207", accepted=["small_items_add_up"]) for _ in range(19)), bill("39.00", "8207"))
    assert not [i for t in rows for i in t.issues if i.code == "small_items_add_up"]


# Who was at a meal: asked whatever the amount when something points to guests; otherwise left under the trivial level.
def test_a_meal_nothing_points_to_guests_on_is_left_under_the_trivial_level():
    [coffees] = decided(bill("9.20", "7406", people="several"))
    assert codes(coffees) == [("left_small", "info")]
    assert coffees.issues[0].message == ("£9.20 is under this client's trivial level of £45.00, and nothing says "
                                         "guests were there: left on Subsistence as coded.")
    assert codes(decided(bill("60.00", "7406", people="several"))[0]) == [("meal_check", "warning")]
    assert codes(decided(bill("9.20", "7406", people="several"), levels=None)[0]) == [("meal_check", "warning")]
    with_clients = bill("9.20", "7406", description="coffee with clients")
    assert codes(decided(with_clients)[0]) == [("meal_check", "warning")]
