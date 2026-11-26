import json

import pytest
from fakes import ROW, FakeModel, transactions_json

from ledgersync.accounts import choosable
from ledgersync.errors import ModelError, ModelUnavailable
from ledgersync.extractor import ACCOUNT_CHOICES, AccountingTransaction, ExtractedTransactions, TransactionExtractor
from ledgersync.model_client import ModelAnswer


def extract(reply, text="x", images=None):
    client = FakeModel([reply])
    return TransactionExtractor(client).extract_accounting_data(text, images=images), client


def test_valid_rows_are_returned_with_model_name():
    result, _ = extract(transactions_json(ROW), "BT Broadband 72.00")
    assert result.count == 1 and result.model == "fake-model"
    assert result.data[0].amount == 72.0 and result.warnings == []


def test_a_price_before_vat_and_not_a_vat_invoice_are_read():
    # The Amazon receipt prints £14.99 and £17.99 but no VAT, and says "This is not a VAT invoice".
    result, _ = extract(transactions_json(dict(ROW, amount=17.99, document_total=17.99, document_net=14.99,
                                               not_vat_invoice=True)))
    assert (result.data[0].document_net, result.data[0].not_vat_invoice) == (14.99, True)
    result, _ = extract(transactions_json(ROW))
    assert (result.data[0].document_net, result.data[0].not_vat_invoice) == (None, False)


def test_the_model_name_says_which_host_read_the_document():
    # Kept with the upload: a host that misreads documents can be found afterwards.
    result, _ = extract(ModelAnswer(transactions_json(ROW), host="DeepInfra"))
    assert result.model == "fake-model via DeepInfra"


def test_one_bad_row_does_not_fail_the_batch():
    no_amount = {k: v for k, v in ROW.items() if k != "amount"}
    result, _ = extract(transactions_json(no_amount, ROW, dict(ROW, direction="sideways")))
    assert result.count == 1 and len(result.warnings) == 2
    assert result.warnings[0].startswith("Row 1 skipped (amount:")
    assert result.warnings[1].startswith("Row 3 skipped (direction:")


def test_negative_amounts_are_kept_for_the_ledger_to_read_as_money_out():
    result, _ = extract(transactions_json(dict(ROW, amount=-72.0)))
    assert result.count == 1 and result.data[0].amount == -72.0


def test_invalid_json_is_a_model_error():
    with pytest.raises(ModelError) as info:
        extract("not json")
    assert info.value.code == "ai_output_invalid"


def test_answer_without_a_list_is_a_model_error():
    with pytest.raises(ModelError):
        extract(json.dumps({"rows": "nope"}))


def test_fenced_json_and_bare_lists_are_accepted():
    result, _ = extract("```json\n" + json.dumps([ROW]) + "\n```")
    assert result.count == 1


def test_images_and_schema_are_sent_to_the_model():
    _, client = extract(transactions_json(), None, images=["aGk="])
    assert client.calls[0]["images"] == ["aGk="]
    assert "transactions" in client.calls[0]["schema"]["properties"]


def test_model_failure_raises_instead_of_guessing():
    client = FakeModel([ModelUnavailable("Groq is down")])
    with pytest.raises(ModelUnavailable):
        TransactionExtractor(client).extract_accounting_data("BT Broadband 72.00")


def test_the_model_must_pick_an_account_from_the_chart():
    account = ExtractedTransactions.model_json_schema()["$defs"]["AccountingTransaction"]["properties"]["account"]
    assert account["enum"] == list(ACCOUNT_CHOICES) and "7502 Telephone and Internet" in account["enum"]
    assert not [choice for choice in account["enum"] if choice[:4] in ("2200", "2201")]
    # 1200 is there for a transfer from another of the client's accounts; a line coded to its own bank goes to Suspense.
    assert "1200 Bank Current Account" in account["enum"]


def test_instructions_and_the_document_travel_separately():
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system, user = client.calls[0]["messages"]
    assert system["role"] == "system" and "7502 Telephone and Internet" in system["content"]
    assert user == {"role": "user", "content": "<document>\nBT Broadband 72.00\n</document>"}


def test_images_are_announced_in_the_user_message():
    _, client = extract(transactions_json(), None, images=["aGk=", "aGk="])
    assert client.calls[0]["messages"][1]["content"] == "The document is attached as 2 image(s)."


def test_the_business_name_tells_sales_from_purchases():
    client = FakeModel([transactions_json(ROW)])
    TransactionExtractor(client, business_name="Northbridge Consulting Ltd").extract_accounting_data("x")
    assert "An invoice issued by Northbridge Consulting Ltd is a sale" in client.calls[0]["messages"][0]["content"]


def test_rows_carry_direction_and_printed_vat():
    result, _ = extract(transactions_json(dict(ROW, direction="in", vat=12.0)))
    assert (result.data[0].direction, result.data[0].vat) == ("in", 12.0)


def test_the_instructions_spell_out_every_field_of_the_answer():
    # Groq enforces the schema but does not show it to the model: without the fields spelled out
    # in the prompt, it answered {"transactions": []} for plain bank CSVs.
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system = client.calls[0]["messages"][0]["content"]
    fields = ExtractedTransactions.model_json_schema()["$defs"]["AccountingTransaction"]["properties"]
    assert fields and [name for name in fields if f'"{name}"' not in system] == []


def test_a_paid_invoice_is_still_one_transaction():
    # An invoice ending "Less Amount Paid <total> / AMOUNT DUE GBP 0.00", with payment instructions
    # below, came back with no transactions: the model read "nothing due" as "nothing to record".
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system = client.calls[0]["messages"][0]["content"]
    assert "whether it is still to be paid or already paid" in system
    assert "an amount due of 0.00 means it has been paid, not that there is nothing to record" in system


def test_a_receipt_gives_one_transaction_per_account():
    # A note "Breakfast £20 / Travelling charges £50" holds two kinds of expense: one row per account.
    # Splitting must not lose or guess VAT, so a single VAT total that cannot be divided keeps one row.
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system = client.calls[0]["messages"][0]["content"]
    assert "one transaction per account, not per item" in system
    assert "a single VAT total that cannot be divided" in system and "set mixed_items to true" in system
    assert "(it is shown per item or per rate" not in system
    assert "different VAT rates and the VAT is printed only as one total or per rate" in system
    assert "Never divide one rate's VAT between accounts" in system
    assert "items at different VAT rates, or of different accounts, with one VAT total" in json.dumps(
        AccountingTransaction.model_json_schema())
    assert "give that printed total as document_total" in system
    assert "and its printed VAT total as document_vat" in system


def test_every_line_of_an_expense_claim_is_read():
    # Jenny's claim had a second Southgate car park line, queried in its notes; the model left it out.
    _, client = extract(transactions_json(ROW), "x")
    system = client.calls[0]["messages"][0]["content"]
    assert "List every line, even when its payee or amount repeats another line or a note queries it" in system


def test_an_expense_claim_gives_one_transaction_per_expense_line():
    # Matt's claim of 24 expenses came back as one row: the model added the lines up by account, got three
    # sums wrong, and the rows' VAT no longer matched the printed total, so the ledger kept the claim whole.
    # Each line of a claim is its own expense: copied as printed, never added together.
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system = client.calls[0]["messages"][0]["content"]
    assert "An expense claim or expense report lists separate expenses" in system
    assert "one transaction per expense line" in system and "Never add expense lines together" in system
    assert "the grand total printed on the claim as document_total" in system and "document_vat is null" in system


def test_rows_carry_the_document_totals_and_the_mixed_items_flag():
    result, _ = extract(transactions_json(dict(ROW, document_total=72.0, document_vat=12.0, mixed_items=None)))
    row = result.data[0]
    assert (row.document_total, row.document_vat, row.mixed_items) == (72.0, 12.0, False)


def test_the_prompt_defines_every_account_it_offers():
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system = client.calls[0]["messages"][0]["content"]
    assert [a.code for a in choosable() if f"{a.code} {a.name}: {a.definition}" not in system] == []


def test_the_instructions_name_every_document_type():
    _, client = extract(transactions_json(ROW), "BT Broadband 72.00")
    system = client.calls[0]["messages"][0]["content"]
    assert all(f'"{kind}"' in system for kind in ("receipt", "invoice", "expense_claim", "statement", "quote",
                                                  "pro_forma", "purchase_order", "remittance_advice",
                                                  "supplier_statement"))
    assert "a credit note is an invoice with the money going the other way" in system
    assert "The counterparty of every line is the person claiming, not the shop" in system


def test_the_instructions_explain_a_letting_agents_statement():
    # Read as a bank statement, an agent's statement booked its rent as if it had reached the bank.
    _, client = extract(transactions_json(ROW), "x")
    system = client.calls[0]["messages"][0]["content"]
    assert '"agent_statement"' in system and "the net it paid over is not a transaction" in system
    assert '"agent"' in system


def test_a_cash_machine_withdrawal_is_cash_not_a_purchase():
    # "LOYD STRATFORD WESTFLD (includes fee of GBP 1.00)", a cash machine, was read as a car park, under Travel.
    _, client = extract(transactions_json(ROW), "x")
    system = client.calls[0]["messages"][0]["content"]
    assert "A card line at a cash machine is cash taken out: 1230 Petty Cash" in system


def test_a_suppliers_list_of_card_charges_is_receipts_not_a_bank_statement():
    # Transport for London's contactless "Payment Statement" (a card, a date range and a charge for each day) was read
    # as the client's bank statement: every receipt dated inside it then looked unpaid by the bank.
    _, client = extract(transactions_json(ROW), "x")
    system = client.calls[0]["messages"][0]["content"]
    assert "is not a bank statement, whatever it calls itself" in system
    assert 'each charge is a receipt of its own, with the type "receipt"' in system


def test_a_shops_receipt_is_a_purchase_though_it_prints_sale():
    # A grocer's till receipt, which names no customer and prints "Sale" above its item, was read as money in.
    _, client = extract(transactions_json(ROW), "x")
    system = client.calls[0]["messages"][0]["content"]
    assert 'is a purchase (out) even when it names no customer and prints the word "Sale"' in system


def test_an_agents_name_comes_once_with_the_answer():
    result, _ = extract(json.dumps({"transactions": [dict(ROW, document_type="agent_statement")], "agent": " R+R PR Ltd "}))
    assert (result.data[0].document_type, result.agent) == ("agent_statement", "R+R PR Ltd")


def test_rows_carry_the_document_type_and_counterparty():
    result, _ = extract(transactions_json(dict(ROW, document_type="Invoice ", counterparty="BT plc")))
    assert (result.data[0].document_type, result.data[0].counterparty) == ("invoice", "BT plc")


def test_rows_carry_the_number_printed_on_their_document():
    result, _ = extract(transactions_json(dict(ROW, document_number="SC-2026-00718"), dict(ROW, document_number=3318),
                                          ROW))
    assert [t.document_number for t in result.data] == ["SC-2026-00718", "3318", None]


def test_a_row_without_a_document_type_is_a_receipt():
    result, _ = extract(transactions_json(ROW))
    assert (result.data[0].document_type, result.data[0].counterparty) == ("receipt", None)


def test_the_prompt_names_a_limited_company_and_offers_its_directors_loan_account():
    client = FakeModel([transactions_json(ROW)])
    TransactionExtractor(client, business_name="Business Cube Ltd",
                         business_type="limited_company").extract_accounting_data("x")
    system = client.calls[0]["messages"][0]["content"]
    assert "You keep the books of Business Cube Ltd, a UK limited company." in system
    assert "2250 Director's Loan Account:" in system and "3260 Drawings:" not in system


def test_a_sole_trader_is_offered_drawings_and_no_directors_loan():
    client = FakeModel([transactions_json(ROW)])
    TransactionExtractor(client, business_name="Jo Bloggs", business_type="sole_trader").extract_accounting_data("x")
    system = client.calls[0]["messages"][0]["content"]
    assert "You keep the books of Jo Bloggs, a UK sole trader." in system
    assert "3260 Drawings:" in system and "2250 Director's Loan Account:" not in system


def test_the_schema_accepts_any_account_a_business_could_use():
    account = ExtractedTransactions.model_json_schema()["$defs"]["AccountingTransaction"]["properties"]["account"]
    assert {"2250 Director's Loan Account", "3260 Drawings", "0055 Vans", "3000 Ordinary Shares",
            "3010 Capital Introduced", "1241 Company Credit Card 2", "1202 Bank Current Account 3"} <= set(account["enum"])


def test_the_prompt_offers_only_the_clients_own_bank_accounts():
    client = FakeModel([transactions_json(ROW)])
    TransactionExtractor(client, business_name="Business Cube Ltd", business_type="limited_company",
                         bank_codes=("1200", "1240")).extract_accounting_data("x")
    system = client.calls[0]["messages"][0]["content"]
    assert "1240 Company Credit Card:" in system and "1241 Company Credit Card 2:" not in system


def test_statement_balances_come_once_with_the_answer_and_running_balances_per_row():
    # A 60-row statement with its opening and closing balance on every row ran past 8,192 output tokens.
    shape = ExtractedTransactions.model_json_schema()
    assert {"opening_balance", "closing_balance"} <= set(shape["properties"])
    assert not {"opening_balance", "closing_balance"} & set(shape["$defs"]["AccountingTransaction"]["properties"])
    reply = json.dumps({"transactions": [dict(ROW, balance=1240.5)], "opening_balance": 1500.0, "closing_balance": -20.0})
    result, client = extract(reply)
    assert (result.data[0].balance, result.opening_balance, result.closing_balance) == (1240.5, 1500.0, -20.0)
    assert "opening_balance and closing_balance once" in client.calls[0]["messages"][0]["content"]


def test_the_instructions_explain_a_payroll_report():
    _, client = extract(transactions_json(ROW), "x")
    system = client.calls[0]["messages"][0]["content"]
    assert '"payroll"' in system and "owed_to" in system
    assert ("net pay to staff is coded 2220 Net Wages, payments to HMRC for PAYE and NI 2210, and payments to the "
            "pension provider 2230") in system


def test_owed_to_comes_with_a_payroll_row_and_is_null_otherwise():
    result, _ = extract(transactions_json(dict(ROW, document_type="payroll", owed_to="paye_ni"), ROW))
    assert [r.owed_to for r in result.data] == ["paye_ni", None]


def test_the_schema_asks_for_the_suppliers_vat_number():
    assert "supplier_vat_number" in AccountingTransaction.model_json_schema()["properties"]


def test_a_claim_total_is_only_what_the_claim_prints():
    client = FakeModel([transactions_json(ROW)])
    TransactionExtractor(client, business_name="Jo Bloggs", business_type="sole_trader").extract_accounting_data("x")
    system = client.calls[0]["messages"][0]["content"]
    assert "null when the claim prints no total" in system and "Never add the lines up to make one" in system


def test_a_row_says_how_many_its_food_was_for_and_what_else_it_could_be_on():
    from ledgersync.extractor import AccountingTransaction
    base = {"description": "Bagel Factory", "amount": 8.69, "direction": "out", "account": "7406 Subsistence"}
    row = AccountingTransaction(**base, people="One", alternatives=["8206 Staff Welfare", "7403 Entertainment",
                                                                    "8205 Refreshments"])
    assert (row.people, row.alternatives) == ("one", ["8206 Staff Welfare", "7403 Entertainment"])
    assert AccountingTransaction(**base, people="a few").people is None
    assert AccountingTransaction(**base, people=None, alternatives=None).alternatives == []


def test_a_row_says_what_kind_of_food_or_drink_was_bought():
    from ledgersync.extractor import AccountingTransaction
    base = {"description": "Tesco", "amount": 4.50, "direction": "out", "account": "7406 Subsistence"}
    assert AccountingTransaction(**base, bought="Groceries").bought == "groceries"
    assert AccountingTransaction(**base, bought="food to go").bought == "food_to_go"
    assert AccountingTransaction(**base, bought="a feast").bought is None
    assert AccountingTransaction(**base).bought is None


def test_a_row_says_when_it_was_bought_abroad():
    # A hotel stay in the UK carries UK VAT the ledger books before its invoice is in; one abroad carries none.
    from ledgersync.extractor import AccountingTransaction
    base = {"description": "Hotel Lutetia, Paris", "amount": 410.0, "direction": "out", "account": "7402 Hotels"}
    assert AccountingTransaction(**base, abroad="true").abroad is True
    assert AccountingTransaction(**base).abroad is False
    assert "abroad" in AccountingTransaction.model_json_schema()["properties"]
    client = FakeModel([transactions_json(ROW)])
    TransactionExtractor(client, business_name="Jo Bloggs", business_type="sole_trader").extract_accounting_data("x")
    system = client.calls[0]["messages"][0]["content"]
    assert "set abroad to true" in system and '"abroad": false' in system


# ─── Coding a statement read in code (design of 2026-11-23) ───────────────────

import datetime as _dt  # noqa: E402
import json as _json  # noqa: E402
from decimal import Decimal as _D  # noqa: E402

from ledgersync.extractor import CODING_BATCH  # noqa: E402
from ledgersync.tables import Line, Statement  # noqa: E402


def _statement(count):
    lines = [Line(date=_dt.date(2023, 4, 28), text=f"PAYEE {n}", amount=_D("10.00") + n, direction="out",
                  balance=None, currency="GBP", kind="BP") for n in range(1, count + 1)]
    return Statement(lines=lines, opening_balance=_D("100.00"), closing_balance=_D("50.00"), heading="HSBC Business")


def _coded(numbers, account="7502"):
    return _json.dumps({"lines": [{"n": n, "account": account, "counterparty": f"Payee {n}", "alternatives": [],
                                   "bought": None, "people": None} for n in numbers]})


def test_coding_a_statement_asks_only_for_accounts_and_keeps_the_figures():
    fake = FakeModel([_json.dumps({"lines": [
        {"n": 1, "account": "2220", "counterparty": "Leah Morgan", "alternatives": [], "bought": None, "people": None},
        {"n": 2, "account": "7502", "counterparty": "BT", "alternatives": ["7503"], "bought": None, "people": None}]})])
    statement = Statement(lines=[
        Line(date=_dt.date(2023, 4, 28), text="LEAH MORGAN SALARY", amount=_D("3149.87"), direction="out",
             balance=_D("8263.46"), currency="GBP", kind="BP"),
        Line(date=_dt.date(2023, 4, 29), text="BT GROUP", amount=_D("72.00"), direction="out", balance=None,
             currency="GBP", kind=None)], opening_balance=_D("11413.33"), closing_balance=_D("8191.46"), heading="")
    result = TransactionExtractor(fake).code_statement(statement, "current")
    first, second = result.data
    assert (first.date, first.amount, first.direction, first.account, first.counterparty, first.balance) == (
        "2023-04-28", 3149.87, "out", "2220", "Leah Morgan", 8263.46)
    assert {r.document_type for r in result.data} == {"statement"} and second.alternatives == ["7503"]
    assert (result.opening_balance, result.closing_balance) == (11413.33, 8191.46)
    [call] = fake.calls
    assert call["reasoning_effort"] == "low"
    assert "1 | 2023-04-28 | out | 3149.87 | BP LEAH MORGAN SALARY" in call["messages"][-1]["content"]
    assert set(call["schema"]["properties"]) == {"lines"}


def test_a_long_statement_is_coded_fifty_lines_a_request():
    assert CODING_BATCH == 50
    fake = FakeModel([_coded(range(1, 51)), _coded(range(51, 101)), _coded(range(101, 121))])
    result = TransactionExtractor(fake).code_statement(_statement(120), "current")
    assert len(fake.calls) == 3 and len(result.data) == 120 and result.data[119].counterparty == "Payee 120"


def test_a_line_the_answer_leaves_out_goes_to_suspense():
    fake = FakeModel([_coded([1, 3, 9])])
    result = TransactionExtractor(fake).code_statement(_statement(3), "current")
    assert [r.account for r in result.data] == ["7502", "9998", "7502"]
    assert len(result.warnings) == 1 and "Line 2" in result.warnings[0]
