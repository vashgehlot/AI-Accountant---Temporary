"""Checks on the written test books. They read only the files a user receives (the key's CSVs, the statement
exports, the PDFs, the previous accountant's trial balance), never the generator's own objects, so a fault in
writing or rendering is caught too."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader

from testbooks.render.documents import money_text
from testbooks.render.statements import hsbc_amount

UNREVIEWED = "Key unreviewed: an accountant has not yet checked these treatments"
CASES_FILE = Path(__file__).parent / "catalogue" / "cases.csv"
ZERO = Decimal("0")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _d(text: str) -> Decimal:
    return Decimal(text) if text else ZERO


def _iso(text: str) -> date:
    return date.fromisoformat(text)


class _Key:
    def __init__(self, client_dir: Path, period_end: date):
        self.dir = client_dir
        self.key = client_dir / "key" / f"{period_end:%Y-%m-%d}"
        self.end = period_end
        self.profile = json.loads((client_dir / "profile.json").read_text())
        self._cache: dict[str, list[dict]] = {}

    def __call__(self, name: str) -> list[dict]:
        if name not in self._cache:
            self._cache[name] = _rows(self.key / f"{name}.csv")
        return self._cache[name]

    def balance(self, code: str, as_at: date) -> Decimal:
        return sum((_d(e["debit"]) - _d(e["credit"]) for e in self("entries")
                    if e["account"] == code and e["phase"] in ("opening", "books", "answers")
                    and _iso(e["date"]) <= as_at), ZERO)

    def month_ends(self) -> list[date]:
        return sorted({_iso(r["month_end"]) for r in self("bank-recs")})


def _statement_rows(k: _Key, account: dict) -> list[tuple[date, Decimal, tuple]]:
    """Every distinct line in the account's statement files: (date, client-side amount, the row itself)."""
    seen, out = set(), []
    for path in sorted(k.dir.joinpath("inbox").rglob(f"*_{account['id']}-statement_*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                key = tuple(row)
                if not row or key in seen:
                    continue
                seen.add(key)
                if account["layout"] == "hsbc_csv":
                    out.append((datetime.strptime(row[0], "%d %b %Y").date(), Decimal(row[3]), key))
                elif account["layout"] == "amex_csv":
                    out.append((datetime.strptime(row[0], "%d/%m/%Y").date(), -Decimal(row[2]), key))
                else:
                    out.append((_iso(row[3][:10]), Decimal(row[7]), key))
    return out


def tb_balances(k: _Key) -> CheckResult:
    tb = k("trial-balance")
    bad = [c for c in ("opening", "books", "before_answers", "year_end", "final")
           if sum((_d(r[c]) for r in tb), ZERO) != 0]
    return CheckResult("tb_balances", not bad, f"columns not summing to zero: {bad}" if bad else "every column sums to 0")


def bank_recs_tie(k: _Key) -> CheckResult:
    opening = {r["account"]: _d(r["debit"]) - _d(r["credit"]) for r in k("opening-balances")}
    recs = defaultdict(list)
    for r in k("bank-recs"):
        recs[(r["account"], r["month_end"])].append(r)
    problems = []
    for account in k.profile["accounts"]:
        lines = _statement_rows(k, account)
        for me in k.month_ends():
            rows = recs.get((account["id"], me.isoformat()), [])
            if not rows:
                continue
            statement = opening.get(account["code"], ZERO) + sum((a for d, a, _ in lines if d <= me), ZERO)
            stated, book = _d(rows[0]["statement_balance"]), _d(rows[0]["book_balance"])
            items = sum((_d(r["item_amount"]) for r in rows), ZERO)
            if statement != stated or stated - book != items or book != k.balance(account["code"], me):
                problems.append(f"{account['id']} {me}")
    return CheckResult("bank_recs_tie", not problems, f"don't tie: {problems[:5]}" if problems else "all tie")


def vat_control_ties(k: _Key) -> CheckResult:
    moved = defaultdict(lambda: ZERO)
    for e in k("entries"):
        if e["journal_id"].startswith("VAT-") and e["account"] == "2202":
            moved[e["journal_id"][4:14]] += _d(e["credit"]) - _d(e["debit"])
    bad = [r["period_end"] for r in k("vat-returns") if moved[r["period_end"]] != _d(r["box5"])]
    return CheckResult("vat_control_ties", not bad, f"returns not agreeing: {bad}" if bad else "every return agrees")


def debtors_creditors_tie(k: _Key) -> CheckResult:
    bad = []
    for name, code, sign in (("debtors", "1100", 1), ("creditors", "2100", -1)):
        owed = defaultdict(lambda: ZERO)
        for r in k(name):
            owed[r["as_at"]] += _d(r["owed"])
        for me in k.month_ends():
            if owed[me.isoformat()] != sign * k.balance(code, me):
                bad.append(f"{name} {me}")
    return CheckResult("debtors_creditors_tie", not bad, f"don't tie: {bad[:5]}" if bad else "both tie every month")


def printed_figures(k: _Key) -> CheckResult:
    bad = []
    for r in k("documents"):
        if not r["file"].endswith(".pdf") or not (r["net"] or r["vat"] or r["gross"]):
            continue
        text = "".join(p.extract_text() for p in PdfReader(k.dir / r["file"]).pages)
        for col in ("net", "vat", "gross"):
            if r[col] and money_text(Decimal(r[col]), r["currency"]) not in text:
                bad.append(f"{r['doc_id']} {col}")
    return CheckResult("printed_figures", not bad, f"missing: {bad[:5]}" if bad else "every figure is printed")


def _shown(layout: str, d: date, row: tuple) -> tuple:
    """What identifies a statement row: its date, description and amount as that layout prints them."""
    if layout == "hsbc_csv":
        return d, row[2], row[3]
    if layout == "amex_csv":
        return d, row[1], row[2]
    return d, row[9], row[8]


def _expected(layout: str, line: dict) -> tuple:
    d, amount = _iso(line["date"]), Decimal(line["amount"])
    if layout == "hsbc_csv":
        return d, line["description"], hsbc_amount(amount)
    if layout == "amex_csv":
        return d, line["description"], f"{-amount:.2f}"
    kind = {"charge": "charge", "fee": "charge", "payout": "payout"}.get(line["type"], "other_adjustment")
    return d, line["description"], kind


def statements_parse(k: _Key) -> CheckResult:
    accounts = {a["id"]: a for a in k.profile["accounts"]}
    shown = {a: {_shown(acc["layout"], d, row) for d, _, row in _statement_rows(k, acc)} for a, acc in accounts.items()}
    bad = [r["line_id"] for r in k("statement-lines")
           if _expected(accounts[r["account"]]["layout"], r) not in shown[r["account"]]]
    return CheckResult("statements_parse", not bad, f"not in a statement: {bad[:5]}" if bad else "every line is there")


def statement_balances_chain(k: _Key) -> CheckResult:
    """In every HSBC-layout export (newest line first), each line's balance is the one before it plus its amount."""
    bad = []
    for account in k.profile["accounts"]:
        if account["layout"] != "hsbc_csv":
            continue
        for path in sorted(k.dir.joinpath("inbox").rglob(f"*_{account['id']}-statement_*.csv")):
            with open(path, newline="", encoding="utf-8") as f:
                rows = [r for r in list(csv.reader(f))[1:] if r]
            oldest_first = list(reversed(rows))
            if any(Decimal(prev[4]) + Decimal(row[3]) != Decimal(row[4])
                   for prev, row in zip(oldest_first, oldest_first[1:])):
                bad.append(path.name)
    return CheckResult("statement_balances_chain", not bad, f"broken: {bad[:5]}" if bad else "every balance chains")


def payroll_controls_clear(k: _Key) -> CheckResult:
    paye, pension = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for r in k("payroll"):
        m = r["pay_date"][:7]
        paye[m] += _d(r["tax"]) + _d(r["ee_ni"]) + _d(r["er_ni"]) - _d(r["ea_used"])
        pension[m] += _d(r["ee_pension"]) + _d(r["er_pension"])
    bad = []
    for me in k.month_ends():
        m = f"{me:%Y-%m}"
        if (k.balance("2220", me) != 0 or -k.balance("2210", me) != paye[m] or
                -k.balance("2230", me) != pension[m]):
            bad.append(str(me))
    return CheckResult("payroll_controls_clear", not bad, f"don't clear: {bad[:5]}" if bad else "all clear")


def opening_matches_prior_tb(k: _Key) -> CheckResult:
    prior = [r for r in k("documents") if r["kind"] == "prior_tb"]
    if not prior:
        return CheckResult("opening_matches_prior_tb", True, "skipped: no previous accountant's trial balance")
    ws = load_workbook(k.dir / prior[0]["file"]).active
    theirs = {str(row[0]): Decimal(str(row[2] or 0)) - Decimal(str(row[3] or 0))
              for row in ws.iter_rows(min_row=2, values_only=True)}
    ours = {r["account"]: _d(r["debit"]) - _d(r["credit"]) for r in k("opening-balances")}
    bad = sorted(c for c in set(theirs) | set(ours) if theirs.get(c, ZERO).quantize(Decimal("0.01")) != ours.get(c, ZERO))
    return CheckResult("opening_matches_prior_tb", not bad, f"differ: {bad}" if bad else "they agree")


def answers_after_arrival(k: _Key) -> CheckResult:
    """No answer is dated before the first paperwork that prompts its question has arrived: the deal's own
    documents, or the statement showing its payment."""
    docs = {r["doc_id"]: r for r in k("documents")}
    statements = []
    for r in k("documents"):
        if r["kind"] == "bank_statement":
            name = Path(r["file"]).name
            account = name[11:name.index("-statement_")]
            statements.append((account, _iso(name[:10]), _iso(name[-14:-4]), _iso(r["arrived"])))
    lines = defaultdict(list)
    for r in k("statement-lines"):
        lines[r["deal_id"]].append((r["account"], _iso(r["date"])))
    bad = []
    for q in k("queries"):
        deal_id, *doc_ids = q["about"].split(";")
        arrivals = [_iso(docs[d]["arrived"]) for d in doc_ids if d in docs]
        arrivals += [arrived for account, on in lines[deal_id] for acc, start, end, arrived in statements
                     if acc == account and start <= on <= end]
        if arrivals and _iso(q["answer_date"]) < min(arrivals):
            bad.append(q["query_id"])
    return CheckResult("answers_after_arrival", not bad, f"answered too early: {bad}" if bad else "all after")


def fixed_assets_tie(k: _Key) -> CheckResult:
    register = k("fixed-assets")
    final = {r["account"]: _d(r["final"]) for r in k("trial-balance")}
    cost = sum((_d(r["cost"]) for r in register), ZERO)
    accumulated = sum((_d(r["accumulated"]) for r in register), ZERO)
    ok = (cost == final.get("0030", ZERO) + final.get("0040", ZERO) and
          accumulated == -(final.get("0031", ZERO) + final.get("0041", ZERO)))
    return CheckResult("fixed_assets_tie", ok, "register ties" if ok else
                       f"register cost {cost}, accumulated {accumulated} don't tie to the trial balance")


def catalogue_refs(k: _Key) -> CheckResult:
    if not CASES_FILE.exists():
        return CheckResult("catalogue_refs", True, "skipped: no catalogue yet")
    known = {r["id"] for r in _rows(CASES_FILE)}
    used = {c for name in ("entries", "documents") for r in k(name) for c in r["cases"].split(";") if c}
    unknown = sorted(used - known)
    return CheckResult("catalogue_refs", not unknown, f"unknown cases: {unknown}" if unknown else "all known")


CHECKS = (tb_balances, bank_recs_tie, vat_control_ties, debtors_creditors_tie, printed_figures, statements_parse,
          statement_balances_chain,
          payroll_controls_clear, opening_matches_prior_tb, answers_after_arrival, fixed_assets_tie, catalogue_refs)


def run_checks(client_dir: Path, period_end: date) -> list[CheckResult]:
    k = _Key(client_dir, period_end)
    return [check(k) for check in CHECKS]


def write_report(client_dir: Path, period_end: date) -> list[CheckResult]:
    results = run_checks(client_dir, period_end)
    lines = [UNREVIEWED] + [f"{'PASS' if r.ok else 'FAIL'} {r.name}: {r.detail}" for r in results]
    (client_dir / "key" / f"{period_end:%Y-%m-%d}" / "checks.txt").write_text("\n".join(lines) + "\n")
    return results
