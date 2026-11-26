import re
from pathlib import Path

from openpyxl import load_workbook

from testbooks.catalogue import load_cases
from testbooks.clients import agency

DOC = Path(__file__).resolve().parents[2] / "docs/superpowers/specs/2026-11-18-test-books-edge-cases.md"


def test_catalogue_matches_the_edge_case_list():
    ids_in_doc = re.findall(r"^\| (EC-\d{4}) \|", DOC.read_text(), flags=re.M)
    cases = load_cases()
    assert [c.id for c in cases] == ids_in_doc and len(cases) == 353
    assert all(c.category == c.id[3:5] for c in cases)
    assert set(agency.STEP1_CASES) <= {c.id for c in cases if c.step == 1}
    assert {c.id for c in cases if c.layout_unconfirmed} >= {"EC-0134", "EC-0152"}


def test_review_folder(tmp_path):
    from testbooks.tests.test_build import built
    built(tmp_path, "a")
    review = tmp_path / "a" / "review"
    ws = load_workbook(review / "catalogue.xlsx").active
    header = [c.value for c in ws[1]]
    assert header[-3:] == ["Agree? (Y/N)", "Correct treatment", "Notes"] and ws.max_row == 354
    text = (review / "README.txt").read_text()
    assert "unreviewed" in text and "clients/agency/inbox" in text
    assert (review / "agency-2024-03-31" / "key.xlsx").exists()
    assert (tmp_path / "a" / "catalogue.csv").exists()
