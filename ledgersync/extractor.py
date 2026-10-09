"""Asks the model for a document's transactions: the prompt, the JSON schema its answer must follow,
and per-row validation."""
import json
import logging
import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

from .accounts import choosable, model_accounts
from .errors import ModelError
from .models import DOCUMENT_TYPES

logger = logging.getLogger(__name__)

# Every account a model may name, for any kind of business, as "<code> <name>"; the prompt lists the ones
# for the business being read.
ACCOUNT_CHOICES: tuple[str, ...] = tuple(f"{a.code} {a.name}" for a in model_accounts())
# The document types a model may give; anything else becomes "other" in the adapter.
MODEL_DOCUMENT_TYPES: tuple[str, ...] = tuple(t for t in DOCUMENT_TYPES if t != "other")
# How the prompt names each kind of business (models.BusinessType).
BUSINESS_WORDS = {"limited_company": "limited company", "sole_trader": "sole trader",
                  "partnership": "partnership", "llp": "limited liability partnership"}


class AccountingTransaction(BaseModel):
    """One row as the model returns it; its JSON schema holds the model's answer to this shape."""
    # The docstring above is sent to the model in the schema. model_client.strict_schema makes every
    # field required, so structured output always emits it (null when unknown).

    description: str = Field(..., description="Who was paid or who paid, and what for")
    date: Optional[str] = Field(None, description="YYYY-MM-DD, or null when the document shows no date")
    amount: float = Field(..., description="The money that moved, including VAT, as a positive number")
    direction: Literal["in", "out"] = Field(
        ..., description="in: money into the business's bank account; out: money paid out of it")
    # The schema lists the chart so the model picks from it; any other text still passes here, and the
    # ledger adapter sends it to Suspense for review instead of dropping the row.
    account: str = Field(..., description="The account from the chart of accounts",
                         json_schema_extra={"enum": list(ACCOUNT_CHOICES)})
    vat: Optional[float] = Field(None, description="The VAT amount printed on the document, or null")
    currency: Optional[str] = Field("GBP", description="Currency code, e.g. GBP")
    # Per receipt or invoice: lets the ledger flag rows that do not add up to the document's total,
    # and a document kept as one row because its VAT could not be divided between accounts.
    document_total: Optional[float] = Field(
        None, description="The printed total of the receipt or invoice this transaction comes from, the same "
                          "on every transaction from that document; null for bank statement or spreadsheet rows")
    document_vat: Optional[float] = Field(
        None, description="The total VAT printed on that receipt or invoice, the same on every transaction from "
                          "it; null when it shows no VAT, and for bank statement or spreadsheet rows")
    # Lets matching see VAT a receipt shows only in its prices, and when it can't be reclaimed with the receipt.
    document_net: Optional[float] = Field(
        None, description="The total before VAT printed on that receipt or invoice (a subtotal or price excluding "
                          "VAT), the same on every transaction from it; null when none is printed, and for bank "
                          "statement or spreadsheet rows")
    not_vat_invoice: bool = Field(False, description="true when the document says it is not a VAT invoice")
    mixed_items: bool = Field(False, description="true when this one transaction covers items of different "
                                                 "accounts because the document shows one VAT total that "
                                                 "cannot be divided between them")
    # Which kind of document the row comes from: the ledger books an unpaid invoice or claim as owed, and
    # leaves a quote, a pro forma or the like for a person to check. Any other text passes here; the
    # adapter treats it as a document that is not a transaction.
    document_type: str = Field("receipt", description="The kind of document this transaction comes from",
                               json_schema_extra={"enum": list(MODEL_DOCUMENT_TYPES)})
    counterparty: Optional[str] = Field(None, description="Who was paid or who paid, as printed: the supplier, "
                                                          "customer, employee or payee; null when not shown")
    # Lets the ledger see a document read twice, such as a reminder repeating a bill's number.
    document_number: Optional[str] = Field(None, description="The number printed on the invoice, credit note, "
                                                             "receipt or claim (its invoice, receipt or transaction "
                                                             "number), the same on every transaction from it; null "
                                                             "when none is printed, and for bank statement rows")
    # On a bank statement row: the balance printed on its line, so the ledger can check no line was missed or
    # misread. The statement's opening and closing balances come once, with the answer (ExtractedTransactions).
    balance: Optional[float] = Field(None, description="On a bank statement row: the running balance printed on "
                                                       "its line, after it; null when the line shows none, and on "
                                                       "every other kind of row")

    @field_validator("mixed_items", "not_vat_invoice", mode="before")
    @classmethod
    def _flag(cls, v):
        return v.strip().lower() == "true" if isinstance(v, str) else bool(v)

    @field_validator("direction", mode="before")
    @classmethod
    def _lowercase_direction(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("account", mode="before")
    @classmethod
    def _account_text(cls, v):
        return "" if v is None else str(v)

    @field_validator("document_type", mode="before")
    @classmethod
    def _document_type_text(cls, v):
        return "receipt" if v is None else str(v).strip().lower()

    @field_validator("document_number", mode="before")
    @classmethod
    def _document_number_text(cls, v):
        return None if v is None or isinstance(v, bool) else str(v).strip() or None


class ExtractedTransactions(BaseModel):
    """Top-level shape the model must return; its JSON schema goes to the model client."""
    transactions: List[AccountingTransaction]
    # A bank statement's own balances, given once: repeated on every row, they ran a 60-row statement past the
    # output limit.
    opening_balance: Optional[float] = Field(None, description="On a bank statement: its opening balance (brought "
                                                               "forward) as printed; null when not printed, and for "
                                                               "any other document")
    closing_balance: Optional[float] = Field(None, description="On a bank statement: its closing balance (carried "
                                                               "forward) as printed; null when not printed, and for "
                                                               "any other document")
    # Given once too: whose statement the agent_statement rows are, which the bank line of the net names.
    agent: Optional[str] = Field(None, description="On a letting or managing agent's statement: the agent's name, as "
                                                   "printed; null for any other document")


class TransactionExtractionResult(BaseModel):
    data: List[AccountingTransaction]
    warnings: List[str] = []
    model: Optional[str] = None
    opening_balance: Optional[float] = None   # a bank statement's, as printed
    closing_balance: Optional[float] = None
    agent: Optional[str] = None               # an agent's statement's agent

    @property
    def count(self) -> int:
        return len(self.data)


class TransactionExtractor:
    """Builds the prompt, calls the model through the model client and validates each row.

    There is deliberately no heuristic fallback: when the model is unavailable the caller gets
    ModelUnavailable / ModelTimeout instead of plausible-looking wrong numbers."""

    def __init__(self, client, business_name: str = "", business_type: Optional[str] = None):
        self.client = client
        self.business_name = business_name
        self.business_type = business_type   # models.BusinessType, or None when not known

    def extract_accounting_data(self, text_input: Optional[str] = None,
                                images: Optional[List[str]] = None) -> TransactionExtractionResult:
        messages = [{"role": "system", "content": self._instructions()},
                    {"role": "user", "content": self._document(text_input, images)}]
        raw_output = self.client.chat_json(messages, ExtractedTransactions.model_json_schema(), images=images)
        return self._validate_and_parse_json(raw_output)

    def _instructions(self) -> str:
        """What to extract and how; the document itself travels in a separate message."""
        name = self.business_name
        kind = f"a UK {BUSINESS_WORDS[self.business_type]}" if self.business_type in BUSINESS_WORDS else "a UK business"
        whose = f"{name}, {kind}" if name else kind
        invoices = (f" An invoice issued by {name} is a sale (in); an invoice or receipt addressed to {name} "
                    "is a purchase (out)." if name else "")
        chart = "\n".join(f"{a.code} {a.name}: {a.definition}" for a in choosable(self.business_type))
        return f"""You keep the books of {whose}. List each movement of money into or out of the business's bank account that the document records, as a JSON object with a "transactions" array.

Rules:
1. Direction: "in" is money the business received (sales, refunds from suppliers, loans received, capital paid in); "out" is money it paid (purchases, expenses, bills, wages, taxes to HMRC, refunds to customers, the owner's drawings, transfers to savings).{invoices}
2. Document type: give every transaction the type of the document it comes from. "receipt": a till or card receipt, or a ticket, paid when it was issued. "invoice": an invoice or bill asking for payment, even when it says paid; a credit note is an invoice with the money going the other way. "expense_claim": an expense claim or expense report. "statement": a bank statement, or bank lines pasted or typed. "agent_statement": a letting or managing agent's statement to the business (a landlord statement), of the rent or other money it collected for the business, the fees and bills it took off, and the net it paid over: give one transaction per item, with what it collected as "in" and each fee or bill it paid as "out", each on the account of what it was for and with who paid or was paid as counterparty; the net it paid over is not a transaction. Give every transaction from it the statement's date, the net paid over as document_total (negative when the business owes the agent), document_vat null, and the agent's name as "agent", once, next to the transactions array. A quote, a pro forma invoice, a purchase order, a remittance advice and a supplier's statement of account are not transactions: still list their amounts, with the type "quote", "pro_forma", "purchase_order", "remittance_advice" or "supplier_statement", so a person can check them. Give as counterparty who was paid or who paid, as printed: the supplier, the customer or the payee. Give the number printed on the document (its invoice, credit note, receipt, transaction or claim number) as document_number on each of its transactions; a reminder or a copy of a document keeps the original's number. Bank statement rows have none.
3. A receipt or an invoice is recorded whether it is still to be paid or already paid (an amount due of 0.00 means it has been paid, not that there is nothing to record). Give one transaction per account, not per item: add together the items that belong to the same account, so a receipt or invoice whose items all belong to one account is ONE transaction for its total, including VAT. When its items belong to different accounts, give one transaction per account for that account's share of the total, including its VAT, but only if the VAT can be divided between them (it is shown per item or per rate, or no VAT is shown). If the document shows a single VAT total that cannot be divided, give ONE transaction for the total on the account of the biggest items and set mixed_items to true. The transactions from one document add up to its total: give that printed total as document_total, and its printed VAT total as document_vat (null when none is shown), on each of them. Subtotals, discounts, cash tendered, change, card-payment, amount-paid and amount-due lines, and payment instructions, are not transactions.
4. An expense claim or expense report lists separate expenses, each with its own receipt, date and payee. Give one transaction per expense line, copying that line's date, payee, amount and the VAT printed on that line. List every line, even when its payee or amount repeats another line or a note queries it. Never add expense lines together, even when they belong to the same account. Subtotals and the claim total are not transactions. Give the claim's grand total as document_total on every line; document_vat is null, because each line carries its own VAT. The counterparty of every line is the person claiming, not the shop. Before answering, add up your lines and compare them with each subtotal and the total printed, and count them against any number of lines printed: if they don't agree, you have probably missed a line, often the last one before a subtotal, so look again and add it. Never add a line that isn't printed: when every printed line is listed and they still don't agree, leave them as printed.
5.A bank statement or spreadsheet has one transaction per payment row. The amount is the money that moved, as a positive number; take the direction from the paid in / paid out columns or the sign. Balances and totals are not transactions, and document_total and document_vat are null. On a bank statement, give the balance printed on each line as balance, and give the statement's opening balance (brought forward) and closing balance (carried forward) as opening_balance and closing_balance once, next to the transactions array; use null for any it does not print. An overdrawn balance (shown with OD, D or a minus sign) is negative.
6. Account: choose by what was bought and why, not by the shop, because most shops sell many kinds of things. On a receipt or invoice, go by the items listed. On a bank line that names only the payee, go by what that kind of business usually sells to a business like this one. Use "9998 Suspense" when the payee could be selling almost anything (such as an online marketplace or a department store) and nothing says what was bought, or when no account below fits. A card line at a cash machine is cash taken out: 1230 Petty Cash. Such a line often names a bank and a place (such as LOYD, HSBC, NWB or LINK) or a fee for the withdrawal; don't guess another kind of business from it.
7. VAT: the VAT amount printed on the document for that transaction, or null when none is printed. Never calculate VAT. The amount is what was charged or paid in all, VAT included: when a receipt prints the amount charged with its VAT on a line under it (Charged Amount £12.00, VAT £2.00), the VAT is part of that amount, so the amount is £12.00; never add the VAT to an amount charged or paid. When a receipt or invoice prints its total before VAT (a subtotal or price excluding VAT), give it as document_net; never work it out. When it says it is not a VAT invoice, set not_vat_invoice to true.
8. Dates are UK format (DD/MM/YYYY): "03/09/2026" is 3 September 2026, written "2026-09-03". Use null when there is no date.
9. If there are no transactions, return {{"transactions": []}}.

Chart of accounts:
{chart}

Answer with JSON only, in this shape (one object per transaction):
{{"transactions": [{{"description": "who was paid or who paid, and what for", "date": "YYYY-MM-DD" or null, "amount": 12.50, "direction": "in" or "out", "account": "<code> <name> from the chart, e.g. 7502 Telephone and Internet", "vat": 2.08 or null, "currency": "GBP", "document_total": 12.50 or null, "document_vat": 2.08 or null, "document_net": 10.42 or null, "not_vat_invoice": false, "mixed_items": false, "document_type": "receipt", "counterparty": "who was paid or who paid", "document_number": "INV-1042" or null, "balance": 1250.00 or null}}], "opening_balance": 1500.00 or null, "closing_balance": 980.50 or null, "agent": "the agent's name" or null}}"""

    @staticmethod
    def _document(text_input: Optional[str], images: Optional[List[str]]) -> str:
        if images:
            return f"The document is attached as {len(images)} image(s)."
        return f"<document>\n{text_input or ''}\n</document>"

    def _validate_and_parse_json(self, raw_text: str) -> TransactionExtractionResult:
        """Parses the model output. Rows that fail validation become warnings, not a failed batch."""
        cleaned = raw_text.strip()
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            raise ModelError("The AI model's answer was not valid JSON.", code="ai_output_invalid") from None
        rows = parsed.get("transactions") if isinstance(parsed, dict) else parsed
        if not isinstance(rows, list):
            raise ModelError("The AI model's answer did not contain a list of transactions.",
                             code="ai_output_invalid")

        valid, warnings = [], []
        for number, row in enumerate(rows, start=1):
            try:
                valid.append(AccountingTransaction.model_validate(row))
            except ValidationError as exc:
                reasons = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'row'}: {e['msg']}"
                                    for e in exc.errors())
                warnings.append(f"Row {number} skipped ({reasons}).")
        if warnings:
            logger.info("Skipped %d invalid row(s) from the model", len(warnings))
        top = parsed if isinstance(parsed, dict) else {}
        # Which host read it, when the answer names one: kept with the upload, so a host that misreads can be found.
        host = getattr(raw_text, "host", None)
        model = f"{self.client.model} via {host}" if host else self.client.model
        return TransactionExtractionResult(data=valid, warnings=warnings, model=model,
                                           opening_balance=_number(top.get("opening_balance")),
                                           closing_balance=_number(top.get("closing_balance")),
                                           agent=str(top.get("agent") or "").strip() or None)


def _number(value) -> Optional[float]:
    """A balance the model gave, or None when what it gave is not a number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
