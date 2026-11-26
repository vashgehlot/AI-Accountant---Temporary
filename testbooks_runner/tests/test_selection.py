import shutil
from datetime import date
from pathlib import Path

import pytest

from testbooks_runner import books, selection
from testbooks_runner.model import Key, Period, Unit, money
from testbooks_runner.selection import SelectionError
from testbooks_runner.tests.helpers import write_mini_client

FIX = Path(__file__).parent / "fixtures" / "set"


@pytest.fixture
def mini_set(tmp_path):
    shutil.copytree(FIX, tmp_path / "set")
    write_mini_client(tmp_path / "set")
    return tmp_path / "set"


def test_select_pack_by_case_id():
    [u] = selection.select_units(FIX, packs=["EC-0346"])
    assert (u.name, u.kind, u.period.start.isoformat(), u.period.end.isoformat()) == (
        "EC-0346-receipt-over-250", "pack", "2024-06-01", "2024-06-30")


def test_select_client_defaults_to_its_first_period(mini_set):
    [u] = selection.select_units(mini_set, client="mini")
    assert u.period.end.isoformat() == "2024-03-31" and u.kind == "client"
    assert u.key_dir == mini_set / "clients" / "mini" / "key" / "2024-03-31"


def test_later_period_is_refused(mini_set):
    with pytest.raises(SelectionError, match="earlier years"):
        selection.select_units(mini_set, client="mini", period=date(2025, 3, 31))


def test_unknown_pack_and_missing_smoke_list_are_refused():
    with pytest.raises(SelectionError, match="EC-9999"):
        selection.select_units(FIX, packs=["EC-9999"])
    with pytest.raises(SelectionError, match="smoke.txt"):
        selection.select_units(FIX, smoke=True)


def test_all_packs_and_nothing_selected():
    names = [u.name for u in selection.select_units(FIX, all_packs=True)]
    assert names == ["EC-0346-receipt-over-250"]
    with pytest.raises(SelectionError):
        selection.select_units(FIX)


def test_repeat_numbers_the_units():
    assert [u.slug for u in selection.select_units(FIX, packs=["EC-0346"], repeat=2)] == [
        "EC-0346-receipt-over-250-2024-06-30-r1", "EC-0346-receipt-over-250-2024-06-30-r2"]


def test_unit_ref():
    u = Unit("mini", "client", Path("x"), Period(date(2023, 4, 1), date(2024, 3, 31)))
    assert u.ref == "mini:2024-03-31"


def test_money():
    from decimal import Decimal
    assert money("") == Decimal("0") and money("-12.50") == Decimal("-12.50")
    assert Key().documents == []


def test_next_year_files_left_out_unless_asked(mini_set):
    [u] = selection.select_units(mini_set, client="mini")
    key = books.load_key(u.key_dir)
    sent = [p.name for _, fs in selection.files_to_send(u, key, False) for p in fs]
    assert "2024-04-01_cabot_99999.pdf" not in sent and "2023-04-15_cabot_62874.pdf" in sent
    assert not any(n.endswith("woi-1.pdf") or n.endswith(".txt") for n in sent)
    with_next = [p.name for _, fs in selection.files_to_send(u, key, True) for p in fs]
    assert "2024-04-01_cabot_99999.pdf" in with_next
    assert not any(n.endswith("woi-1.pdf") or n.endswith(".txt") for n in with_next)


def test_set_under_a_path_with_spaces(tmp_path):
    root = tmp_path / "ACTING OFFICE- WORK" / "set"
    shutil.copytree(FIX, root)
    [u] = selection.select_units(root, packs=["EC-0346"])
    assert len(books.batches(u.folder)) == 5
