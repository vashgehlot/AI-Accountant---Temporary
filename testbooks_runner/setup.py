"""Turns a client's profile and the key's opening tables into the bodies the app takes at set-up."""
from __future__ import annotations

from decimal import Decimal

from .mapping import app_code
from .model import Key, Period, money


class SetupError(Exception):
    """The profile can't be turned into a client the app will take."""


_BANK_RANGES = (("current", 1200, 1209), ("savings", 1210, 1219),
                ("petty_cash", 1230, 1239), ("credit_card", 1240, 1249))
_KINDS = {"ltd": "limited_company", "sole_trader": "sole_trader", "partnership": "partnership", "llp": "llp"}


def bank_kind(code: str) -> str | None:
    try:
        number = int(code)
    except (TypeError, ValueError):
        return None
    for kind, low, high in _BANK_RANGES:
        if low <= number <= high:
            return kind
    return None


def business_type(profile: dict) -> str:
    kind = profile.get("kind")
    if kind in _KINDS:
        return _KINDS[kind]
    if kind == "pack":
        name = (profile.get("name") or "").strip()
        if name.endswith(("Ltd", "Limited")):
            return "limited_company"
        if name.endswith("LLP"):
            return "llp"
        raise SetupError(f"can't tell the business type of pack {name!r} from its name")
    raise SetupError(f"unknown client kind {kind!r}")


def _percent(share: str) -> str:
    return format((Decimal(str(share)) * 100).normalize(), "f")


def client_fields(profile: dict, period: Period, review: str) -> dict:
    kind = business_type(profile)
    owners = profile.get("owners") or []
    vat_number = profile.get("vat_number") or ""
    # The client's capitalisation threshold, from its policies: equipment under it is a cost in its accounts.
    threshold = (profile.get("policies") or {}).get("capitalise_from")
    return {**({"capitalise_from": str(threshold)} if threshold else {}),
        "name": profile["name"],
        "business_type": kind,
        "contact_name": owners[0]["name"] if owners else profile["name"],
        "first_year_end": period.end.isoformat(),
        "vat_registered": bool(vat_number),
        "vat_number": vat_number,
        "company_number": profile.get("company_number") or "",
        "bank_accounts": [{"code": "", "name": a["name"], "kind": bank_kind(a["code"])}
                          for a in profile.get("accounts", []) if bank_kind(a["code"]) is not None],
        "owners": [] if kind == "sole_trader"
        else [{"name": o["name"], "share": _percent(o["share"])} for o in owners],
        "ai_review": review,
    }


def bank_codes(profile: dict, client: dict) -> dict[str, str]:
    created = {a["name"]: a["code"] for a in client.get("bank_accounts", [])}
    out = {}
    for account in profile.get("accounts", []):
        if bank_kind(account["code"]) is None:
            continue
        if account["name"] not in created:
            raise SetupError(f"the app made no bank account named {account['name']!r}")
        out[account["id"]] = created[account["name"]]
    return out


def statement_account(doc_id: str, profile: dict) -> str | None:
    first = doc_id.split("-")[0]
    return first if any(a["id"] == first for a in profile.get("accounts", [])) else None


def _fmt(value: Decimal) -> str:
    return f"{value:.2f}"


def opening_balances(key: Key, chart) -> tuple[dict, list[str]]:
    net: dict[str, Decimal] = {}
    for row in key.opening:
        code = app_code(chart, row["account"])
        net[code] = net.get(code, Decimal("0")) + money(row["debit"]) - money(row["credit"])
    lines = [{"code": code, "debit": _fmt(max(v, Decimal("0"))), "credit": _fmt(max(-v, Decimal("0")))}
             for code, v in net.items() if v != 0]
    items, warnings = opening_items(key)
    return {"lines": lines, "unpaid": items}, warnings


def _opening_side(key: Key, table: list[dict], control: str, credit_side: bool,
                  direction: str) -> tuple[list[dict], list[str]]:
    """Items for one side: named opening rows, then the first payments, if together they equal the balance."""
    balance = Decimal("0")
    for row in key.opening:
        if row["account"] == control:
            delta = money(row["debit"]) - money(row["credit"])
            balance += -delta if credit_side else delta
    named = []
    if table:
        first = min(r["as_at"] for r in table)
        for r in table:
            if r["as_at"] == first and r["doc_id"].startswith("OPENING-"):
                named.append({"direction": direction, "counterparty": r["counterparty"],
                              "amount": money(r["gross"]), "number": r["number"] or None,
                              "date": r["date"] or None})
    total = sum((i["amount"] for i in named), Decimal("0"))
    items = list(named)
    # Opening debtors are cleared by credits to 1100; opening creditors by debits to 2100.
    clearing = "credit" if not credit_side else "debit"
    payments = sorted((e for e in key.entries if e["phase"] == "books" and not e["doc_ids"]
                       and e["account"] == control and money(e[clearing]) != 0),
                      key=lambda e: e["date"])
    for e in payments:
        amount = money(e[clearing])
        if total + amount > balance:
            break
        items.append({"direction": direction, "counterparty": e["counterparty"], "amount": amount,
                      "number": None, "date": None})
        total += amount
    warnings = []
    if total != balance:
        warnings.append(f"opening items for {control} total {_fmt(total)} but the opening balance is "
                        f"{_fmt(balance)}; sending only the named items")
        items = named
    return items, warnings


def opening_items(key: Key) -> tuple[list[dict], list[str]]:
    debtors, w1 = _opening_side(key, key.debtors, "1100", False, "in")
    creditors, w2 = _opening_side(key, key.creditors, "2100", True, "out")
    items = []
    for n, item in enumerate(debtors + creditors, start=1):
        items.append({"id": f"open-{n}", "direction": item["direction"], "counterparty": item["counterparty"],
                      "amount": _fmt(item["amount"]), "number": item["number"], "date": item["date"]})
    return items, w1 + w2
