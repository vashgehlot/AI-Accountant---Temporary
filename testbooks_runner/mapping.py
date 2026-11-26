"""The runner's own translation between the key's chart and the app's chart, and the VAT codes."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

TABLES = Path(__file__).parent / "tables"


class Unmapped(KeyError):
    """A key code the table has no row for."""


@dataclass(frozen=True)
class ChartRow:
    key_code: str
    key_name: str
    app_code: str
    also: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class VatRow:
    key_code: str
    label: str
    reverse_charge: bool


def _rows(path: Path):
    with Path(path).open(newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


def load_chart(path: Path = TABLES / "chart.csv") -> dict[str, ChartRow]:
    return {r["key_code"]: ChartRow(r["key_code"], r["key_name"], r["app_code"],
                                    tuple(c for c in r["also"].split(";") if c), r["note"])
            for r in _rows(path)}


def load_vat(path: Path = TABLES / "vat.csv") -> dict[str, VatRow]:
    return {r["key_code"]: VatRow(r["key_code"], r["label"], r["reverse_charge"] == "Y") for r in _rows(path)}


def app_code(chart: dict[str, ChartRow], key_code: str) -> str:
    try:
        return chart[key_code].app_code
    except KeyError:
        raise Unmapped(key_code) from None


def choices(chart: dict[str, ChartRow], key_code: str, also_ok: str = "") -> tuple[str, ...]:
    """The primary app code, then the table's `also`, then each `also_ok` key code mapped; no duplicates."""
    out = [app_code(chart, key_code), *chart[key_code].also]
    out += [app_code(chart, c) for c in also_ok.split(";") if c]
    return tuple(dict.fromkeys(out))
