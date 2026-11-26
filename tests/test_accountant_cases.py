"""Do the rules ask what an accountant would, for any kind of business? Each case in eval/accountant_cases is a
made-up client of a kind the app wasn't built on (a builder, a cafe, a landlord, a consultancy, a partnership), with
its rows as the reader would give them and what an accountant expects of each (eval/accountant_cases/README.md).
A failure is a rule that doesn't generalise: fix the rule, not the case."""
import datetime as dt
import json
from pathlib import Path

import pytest

from ledgersync import books, ledger
from ledgersync.models import ClientFields, Transaction

pytestmark = pytest.mark.mongo

CASES = Path(__file__).parent.parent / "eval" / "accountant_cases"
YEAR = dt.date(2026, 4, 1)


def _cases() -> list[Path]:
    return sorted(CASES.glob("*.json"))


def _expectations(path: Path, store) -> list[tuple[str, dict, object]]:
    """Loads the case into the store; each expected row's label, expectations and the row as the books show it."""
    case = json.loads(path.read_text())
    client = ledger.add_client(store, ClientFields(**case["client"]))
    expected: list[tuple[str, dict]] = []
    for upload in case["uploads"]:
        rows = []
        for raw in upload["rows"]:
            fields = {k: v for k, v in raw.items() if k != "expect"}
            rows.append(Transaction.model_validate(fields))
            if "expect" in raw:
                expected.append((f"{raw['description']} £{raw['gross']}", raw["expect"]))
        store.add_upload(client.id, upload["name"], "document", rows, year_start=YEAR)
    shown = {f"{r.description} £{r.gross:.2f}": r for r in books.ledger(store, client.id, YEAR).transactions}
    return [(label, expect, shown.get(label)) for label, expect in expected]


@pytest.mark.parametrize("path", _cases(), ids=lambda p: p.stem)
def test_an_accountant_would_ask_this_and_only_this(mongo_store, path):
    wrong = []
    for label, expect, row in _expectations(path, mongo_store):
        if row is None:
            wrong.append(f"{label}: not in the books")
            continue
        asked = {i.code for i in row.issues if i.severity in ("warning", "error")}
        every = {i.code for i in row.issues}
        for code in expect.get("asks", []):
            if code not in asked:
                wrong.append(f"{label}: an accountant would ask {code}; asked {sorted(asked)}")
        for code in expect.get("notes", []):
            if code not in every:
                wrong.append(f"{label}: should say {code}; says {sorted(every)}")
        for code in expect.get("never", []):
            if code in every:
                message = next(i.message for i in row.issues if i.code == code)
                wrong.append(f"{label}: no accountant would raise {code}: {message}")
        if "account" in expect and row.account_code != expect["account"]:
            wrong.append(f"{label}: belongs on {expect['account']}, is on {row.account_code}")
    assert not wrong, "\n".join(wrong)
