import csv
from pathlib import Path

import pytest

from testbooks_runner import mapping

FIX = Path(__file__).parent / "fixtures" / "set"
PACK = FIX / "packs" / "EC-0346-receipt-over-250"


def test_every_generator_account_is_mapped():
    chart = mapping.load_chart()
    with open(PACK / "chart.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            assert mapping.app_code(chart, row["code"])


@pytest.mark.parametrize("key,app", [("4906", "4902"), ("3260", "3250"), ("7550", "8201"), ("7905", "7901"),
                                     ("8205", "8206"), ("8250", "8207"), ("9100", "8800"), ("2125", "2105"),
                                     ("7410", "7304"), ("5100", "5002"), ("4010", "4000"), ("7504", "7504")])
def test_codes_whose_meaning_differs(key, app):
    assert mapping.app_code(mapping.load_chart(), key) == app


def test_choices_add_also_ok():
    assert mapping.choices(mapping.load_chart(), "9998", also_ok="7504") == ("9998", "7504")


def test_choices_include_the_tables_also_without_duplicates():
    chart = mapping.load_chart()
    assert mapping.choices(chart, "8205", also_ok="8205") == ("8206", "8205")
    assert mapping.choices(chart, "1290") == ("9998", "1200", "1210")


def test_unmapped_code_raises():
    with pytest.raises(mapping.Unmapped):
        mapping.app_code(mapping.load_chart(), "1234")


def test_vat_table():
    vat = mapping.load_vat()
    assert vat["reverse_charge"].reverse_charge and vat["standard"].label == "VAT at 20%"
    assert not vat["blocked_half"].reverse_charge and len(vat) == 10
