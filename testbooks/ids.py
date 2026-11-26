"""Made-up identifiers that look and check like real ones."""
from __future__ import annotations

import random

_WEIGHTS = (8, 7, 6, 5, 4, 3, 2)


def _weighted(digits: str) -> int:
    return sum(int(d) * w for d, w in zip(digits[:7], _WEIGHTS))


def vat_number_valid(s: str) -> bool:
    """A UK VAT number's check digits: the weighted first seven digits plus the last two are a multiple of 97,
    or are once 55 is added (the newer series)."""
    if len(s) != 9 or not s.isdigit():
        return False
    total = _weighted(s) + int(s[7:])
    return total % 97 == 0 or (total + 55) % 97 == 0


def vat_number(rng: random.Random) -> str:
    """Nine digits that pass the check."""
    first = str(rng.randint(1, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(6))
    return f"{first}{(-_weighted(first)) % 97:02d}"


_IE_LETTERS = "WABCDEFGHIJKLMNOPQRSTUV"


def ie_vat_number_valid(s: str) -> bool:
    """An Irish VAT number (the eight-character form, without IE): seven digits and a check letter, the weighted
    digits (8 down to 2) mod 23 picking the letter from W, A, B ... V."""
    if len(s) != 8 or not s[:7].isdigit() or not s[7].isalpha():
        return False
    return _IE_LETTERS[_weighted(s) % 23] == s[7].upper()


def ie_vat_number(rng: random.Random) -> str:
    digits = "".join(str(rng.randint(0, 9)) for _ in range(7))
    return digits + _IE_LETTERS[_weighted(digits) % 23]


def ni_number(rng: random.Random) -> str:
    """A National Insurance number with the QQ prefix, which HMRC never issues."""
    return "QQ" + "".join(str(rng.randint(0, 9)) for _ in range(6)) + rng.choice("ABCD")
