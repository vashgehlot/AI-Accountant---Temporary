"""What is kept of a row, and how: the inputs a document or a person gave, with everything else worked out again
on every read. Shared by the store and the ledger."""
from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import NamedTuple, Optional

from .checks import is_derived
from .models import Transaction

# What is kept of a row: the inputs a document or a person gave. Everything else is worked out on read.
INPUTS = {"date", "description", "direction", "gross", "vat", "vat_treatment", "account_code", "contra_account_code",
          "bank_account", "currency", "source", "method", "evidence", "document_type", "counterparty",
          "document_number", "agent", "owed_to", "document_total", "document_net", "not_vat_invoice", "document_ref",
          "total_worked_out", "cis_deducted",
          "include", "apart_from", "link", "balance", "opening_balance", "closing_balance", "supplier_vat_number",
          "addressed_to", "reverse_charge", "abroad", "accepted", "vat_confirmed", "vat_stated",
          "excluded", "removed", "superseded_by", "decision_ids", "total_accepted", "people", "bought", "alternatives",
          "writes_off"}
# The fields a person can edit; a row's first edit keeps what they held as `original`.
EDITABLE = ("date", "description", "counterparty", "direction", "gross", "vat", "account_code", "document_type",
            "currency", "vat_treatment", "bank_account", "reverse_charge")
# Fields of a whole document: a change to one row changes every row with its document_ref. An expense claim's
# lines are separate expenses, each with its own receipt, so there Include books one line. The difference from its
# total that a person accepted is the document's too, so it outlasts any one of its rows.
WHOLE_DOCUMENT = {"counterparty", "document_type", "include", "total_accepted"}
# Rows read before 2026-10-08 kept their document's printed total only in the words of their warning.
OLD_TOTAL = re.compile(r"(?:its total is|it paid over) £(-?[\d,]+\.\d{2})")


class StoredRow(NamedTuple):
    id: int
    upload_id: int
    tx: Transaction
    original: Optional[dict]   # what the editable fields held before a person's first edit; None if never edited


def saved_form(tx: Transaction) -> dict:
    """A row as the database keeps it: its inputs, the issues the ledger doesn't work out itself, and a
    document reference (a manual entry arrives without one)."""
    data = tx.model_dump(mode="json", include=INPUTS)
    data["issues"] = [found.model_dump() for found in tx.issues if not is_derived(found)]
    data["document_ref"] = data.get("document_ref") or uuid.uuid4().hex[:12]
    return data


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
