"""Money in pounds and pence: Decimal only, rounded half up to the penny."""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

PENNY = Decimal("0.01")
ZERO = Decimal("0.00")


def pennies(x: Decimal | str | int) -> Decimal:
    """The amount rounded to the penny, half up."""
    return Decimal(x).quantize(PENNY, rounding=ROUND_HALF_UP)


def vat_on(net: Decimal, rate: Decimal) -> Decimal:
    """VAT charged on a net amount."""
    return pennies(net * rate)


def vat_in(gross: Decimal, rate: Decimal) -> Decimal:
    """The VAT inside a gross amount (the VAT fraction)."""
    return pennies(gross * rate / (1 + rate))


def whole_pounds(x: Decimal) -> int:
    """Pence left out, as VAT return boxes 6 to 9 want: truncated toward zero."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_DOWN))
