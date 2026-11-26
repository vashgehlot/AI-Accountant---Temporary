"""Plain data the runner passes around."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Period:
    start: date
    end: date


@dataclass(frozen=True)
class Unit:
    """One thing to run: a client's year, or a pack. kind is "client" or "pack"."""

    name: str
    kind: str
    folder: Path
    period: Period
    repeat: int = 1

    @property
    def key_dir(self) -> Path:
        return self.folder / "key" / self.period.end.isoformat()

    @property
    def slug(self) -> str:
        return f"{self.name}-{self.period.end}-r{self.repeat}"

    @property
    def ref(self) -> str:
        return f"{self.name}:{self.period.end}"


@dataclass
class Key:
    documents: list[dict[str, str]] = field(default_factory=list)
    entries: list[dict[str, str]] = field(default_factory=list)
    lines: list[dict[str, str]] = field(default_factory=list)
    queries: list[dict[str, str]] = field(default_factory=list)
    vat_returns: list[dict[str, str]] = field(default_factory=list)
    trial_balance: list[dict[str, str]] = field(default_factory=list)
    opening: list[dict[str, str]] = field(default_factory=list)
    debtors: list[dict[str, str]] = field(default_factory=list)
    creditors: list[dict[str, str]] = field(default_factory=list)


def money(text: str) -> Decimal:
    text = (text or "").strip()
    return Decimal(text) if text else Decimal("0")
