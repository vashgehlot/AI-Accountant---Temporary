"""Small builders for the scoring tests."""
from __future__ import annotations

from testbooks_runner.align import Snapshot
from testbooks_runner.model import Key


def key(**tables) -> Key:
    return Key(**tables)


def row(id, upload_id, **fields) -> dict:
    out = {"id": id, "upload_id": upload_id, "direction": "out", "gross": "0.00",
           "document_type": "receipt", "decision_ids": []}
    out.update(fields)
    return out


# A ledger row's other fields as the app's API sends them on a row nobody has touched (a SavedRow with its defaults,
# serialised as GET .../ledger serialises every field). `include` is false on every such row.
API_DEFAULTS = {
    "description": "", "vat": None, "vat_treatment": None, "vat_posted": None, "net": None, "reverse_vat": None,
    "account_code": "", "contra_account_code": None, "bank_account": None, "currency": "GBP", "source": "text",
    "method": "llm", "evidence": None, "counterparty": None, "document_number": None, "agent": None,
    "owed_to": None, "document_total": None, "document_net": None, "not_vat_invoice": False, "cis_deducted": None,
    "total_worked_out": False, "document_ref": None, "include": False, "excluded": False, "removed": False,
    "superseded_by": None, "supplier_vat_number": None, "addressed_to": None, "accepted": [],
    "reverse_charge": False, "abroad": False, "total_accepted": None, "apart_from": [], "without_document": None,
    "vat_stated": False, "vat_from_claim": False, "vat_confirmed": False, "vat_not_reclaimed": None,
    "vat_not_reclaimed_why": None, "link": None, "balance": None, "opening_balance": None, "closing_balance": None,
    "paid_against": None, "pays": [], "candidates": [], "owed": None, "document_direction": None, "paid_by": [],
    "in_opening": False, "copy_of": None, "recorded_by": None, "claimed_in": None, "claim_note": None,
    "people": None, "bought": None, "alternatives": [], "presentation": [], "account_chosen": False,
    "documented_by": None, "recorded_by_refs": [], "left_off_claim": None, "vat_found": None, "date_found": None,
    "amount_found": None, "issues": [], "edited": False, "original": None, "account_name": "",
    "contra_account_name": None, "paid_against_name": None,
}


def api_row(id, upload_id, **fields) -> dict:
    """A row in the shape the app's API sends it: every field, with the app's defaults unless given."""
    return row(id, upload_id, **{**API_DEFAULTS, **fields})


def posted(row_id, code, debit="0", credit="0") -> dict:
    """One flat entry of the posted trial balance's journal."""
    return {"transaction": row_id, "code": code, "debit": debit, "credit": credit, "description": ""}


def snapshot(rows=(), posted_lines=(), uploads=(), questions=(), decisions=(), reviews=(), vat=None,
             invoices=(), tb_lines=(), opening=(), accounts=(), scored_year="2023-04-01", chat=None) -> Snapshot:
    return Snapshot(
        which="before", scored_year=scored_year,
        ledgers={scored_year: {"transactions": list(rows), "uploads": list(uploads)}},
        posted={scored_year: {"journal": list(posted_lines), "lines": list(tb_lines),
                              "opening": list(opening)}},
        vat=dict(vat or {}), invoices=list(invoices), questions=list(questions),
        decisions=list(decisions), reviews=list(reviews), accounts=list(accounts), chat=chat)


def uploads_progress(mapping: dict[str, int]) -> dict:
    """Progress.uploads for files saved as the given upload ids."""
    return {path: {"status": "saved", "job_id": "j", "upload_id": uid, "error": None,
                   "submitted": None, "finished": None, "tries": 1} for path, uid in mapping.items()}
