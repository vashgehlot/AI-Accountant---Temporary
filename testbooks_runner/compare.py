"""Compare a run's outcomes with an earlier run's, matched by Outcome.identity."""
from __future__ import annotations

from .cases import PRIORITY
from .checks import Outcome


def _rank(o: Outcome) -> int:
    return PRIORITY.index(o.status) if o.status in PRIORITY else len(PRIORITY)


def _worst(outcomes: list[Outcome]) -> dict[str, Outcome]:
    """One outcome per identity: the worst status, the first seen on a tie."""
    best: dict[str, Outcome] = {}
    for o in outcomes:
        if o.identity and (o.identity not in best or _rank(o) < _rank(best[o.identity])):
            best[o.identity] = o
    return best


def compare(current: list[Outcome], previous: list[Outcome]) -> dict[str, list[Outcome]]:
    now, before = _worst(current), _worst(previous)
    result: dict[str, list[Outcome]] = {"new": [], "flipped": [], "fixed": [], "still": []}
    for identity, o in now.items():
        old = before.get(identity)
        if o.status == "fail":
            if old is None or old.status not in ("pass", "fail"):
                result["new"].append(o)  # it wasn't a fault in the earlier run
            elif old.status == "pass":
                result["flipped"].append(o)
            else:
                result["still"].append(o)
        elif o.status == "pass" and old is not None and old.status == "fail":
            result["fixed"].append(o)
    return result
