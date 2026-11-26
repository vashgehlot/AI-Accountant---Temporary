"""Scores a client's year trial balance against one worked out by hand (eval/jobs/<case>/expected_trial_balance.json),
account by account, to the penny.

Each account is compared by its net: debit minus credit, so a credit balance is negative ("-72.00"). An account
whose net is zero is left out on both sides, so a missing account and one that nets to nothing are the same."""
from __future__ import annotations

from decimal import Decimal

PENNY = Decimal("0.01")
ZERO = Decimal("0.00")


def _money(amount: Decimal) -> str:
    """An amount as an exact string with its pennies: "60.00", "-60.00", and "0.00" for nothing."""
    amount = amount.quantize(PENNY)
    return str(amount if amount != 0 else ZERO)   # never "-0.00"


def net_by_account(trial_balance: dict) -> dict[str, Decimal]:
    """Each account's debit minus credit in a trial balance (its `lines`, money as exact strings), to two places,
    leaving out the accounts that net to zero."""
    nets: dict[str, Decimal] = {}
    for line in trial_balance.get("lines") or []:
        code = line["code"]
        nets[code] = nets.get(code, ZERO) + Decimal(line["debit"]) - Decimal(line["credit"])
    return {code: net.quantize(PENNY) for code, net in nets.items() if net != 0}


def compare(expected: dict[str, Decimal], actual: dict[str, Decimal]) -> list[dict]:
    """Every account whose net differs, sorted by code: what was expected, what the books give, and the difference
    (actual less expected), as money strings. An account missing on one side counts as "0.00" there."""
    differences = []
    for code in sorted(set(expected) | set(actual)):
        want, got = Decimal(expected.get(code, ZERO)), Decimal(actual.get(code, ZERO))
        if want != got:
            differences.append({"code": code, "expected": _money(want), "actual": _money(got),
                                "difference": _money(got - want)})
    return differences
