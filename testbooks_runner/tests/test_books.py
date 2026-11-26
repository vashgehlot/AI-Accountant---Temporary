from pathlib import Path

from testbooks_runner import books

FIX = Path(__file__).parent / "fixtures" / "set"
PACK = FIX / "packs" / "EC-0346-receipt-over-250"


def test_load_key_reads_every_table():
    key = books.load_key(PACK / "key" / "2024-06-30")
    assert len(key.documents) == 6 and key.vat_returns is not None and len(key.queries) == 1
    assert len(key.vat_returns) == 1 and key.creditors == []


def test_load_key_missing_csv_gives_empty_list(tmp_path):
    assert books.load_key(tmp_path).documents == []


def test_batches_are_in_date_order():
    assert [d.isoformat() for d, _ in books.batches(PACK)] == [
        "2024-06-04", "2024-06-11", "2024-06-12", "2024-06-20", "2024-07-01"]


def test_answer_folders_list_their_files():
    [(day, files)] = books.answer_folders(PACK)
    assert day.isoformat() == "2024-06-14" and len(files) == 2


def test_signed_off_only_with_the_file(tmp_path):
    assert books.signed_off(FIX) is False
    (tmp_path / "review").mkdir()
    (tmp_path / "review" / "signed-off.txt").write_text("x")
    assert books.signed_off(tmp_path) is True


def test_catalogue_is_keyed_by_id():
    cat = books.load_catalogue(FIX)
    assert cat["EC-0346"]["id"] == "EC-0346" and "title" in cat["EC-0346"]


def test_load_profile_and_key_hash_follows_the_key(tmp_path):
    import shutil
    from testbooks_runner.model import Period, Unit
    from datetime import date
    pack = tmp_path / "p"
    shutil.copytree(PACK, pack)
    assert books.load_profile(pack)["name"] == "Fernbrook Consulting Ltd"
    u = Unit("p", "pack", pack, Period(date(2024, 6, 1), date(2024, 6, 30)))
    before = books.key_hash(u)
    assert before == books.key_hash(u) and len(before) == 64
    with (u.key_dir / "documents.csv").open("a") as fh:
        fh.write("\n")
    assert books.key_hash(u) != before


def test_a_clients_policies_come_with_its_profile(tmp_path):
    # The agency's policies.json says it capitalises equipment from £500 net: the app needs that at set-up.
    folder = tmp_path / "agency"
    folder.mkdir()
    (folder / "profile.json").write_text('{"name": "Kestrel & Finch Digital Ltd"}', encoding="utf-8")
    assert books.load_profile(folder).get("policies") is None
    (folder / "policies.json").write_text('{"capitalise_from": "500"}', encoding="utf-8")
    assert books.load_profile(folder)["policies"] == {"capitalise_from": "500"}
