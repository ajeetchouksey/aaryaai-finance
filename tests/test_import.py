"""Bank-statement import: profiles in YAML, a preview that marks duplicates, and an all-or-nothing save."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.core import importer  # noqa: E402
from aaryaai_finance.packs import available_packs  # noqa: E402
from aaryaai_finance.rules.engine import load_import_profiles  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402

# Invented sample data in the shape of common exports (no real people or accounts).
DE_CSV = ("Kontonummer;DE00 0000 0000 0000 0000 00\n"
          "Zeitraum;01.09.2026 - 30.09.2026\n\n"
          "Buchungstag;Valutadatum;Buchungstext;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag;Waehrung\n"
          "01.09.2026;01.09.2026;Lastschrift;Miete September;Hausverwaltung Muster;-1.150,00;EUR\n"
          "03.09.2026;03.09.2026;Kartenzahlung;Einkauf;Supermarkt Beispiel;-64,20;EUR\n"
          "03.09.2026;03.09.2026;Kartenzahlung;Einkauf;Supermarkt Beispiel;-64,20;EUR\n"
          "25.09.2026;25.09.2026;Gutschrift;Gehalt September;Arbeitgeber GmbH;3.400,00;EUR\n"
          ";;;Summe;;;\n").encode("cp1252")
IN_CSV = ("Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance\n"
          "02/09/26,UPI-GROCERY STORE,0001,02/09/26,1250.00,,98750.00\n"
          "05/09/26,NEFT-RENT RECEIVED,0002,05/09/26,,25000.00,123750.00\n"
          "06/09/26,ATM CASH,0003,06/09/26,\"2,000.00\",,121750.00\n").encode()


def _profiles():
    packs = {k: v for k, v in available_packs().items() if k in ("DE", "IN")}
    out, errs = load_import_profiles(None, packs)
    assert not errs
    return out


def test_german_export_with_account_lines_above_the_table():
    r = importer.parse(DE_CSV, _profiles())
    assert r["profile"]["id"] == "de_buchungstag_betrag"
    rows = r["rows"]
    assert [(x["date"], x["kind"], x["amount"]) for x in rows] == [
        ("2026-09-01", "expense", 1150.0), ("2026-09-03", "expense", 64.2), ("2026-09-03", "expense", 64.2), ("2026-09-25", "income", 3400.0)]
    assert rows[0]["description"] == "Hausverwaltung Muster · Miete September"
    assert r["skipped"] and r["skipped"][0]["reason"] == "no date"            # the "Summe" line


def test_indian_export_with_debit_and_credit_columns():
    r = importer.parse(IN_CSV, _profiles())
    assert r["profile"]["id"] == "in_narration_withdrawal_deposit"
    assert [(x["kind"], x["amount"]) for x in r["rows"]] == [("expense", 1250.0), ("income", 25000.0), ("expense", 2000.0)]


@pytest.mark.parametrize("text,value", [("-12,50", -12.5), ("12,50-", -12.5), ("(12.50)", -12.5), ("+1.234,56", 1234.56), ("−5", -5), ("EUR 7", 7)])
def test_amount_formats(text, value):
    assert importer._amount(text) == pytest.approx(value)


def test_an_unknown_file_says_so():
    r = importer.parse(b"foo;bar\n1;2\n", _profiles())
    assert r["profile"] is None and "None of the import profiles" in r["error"]


def test_duplicates_count_each_existing_entry_once():
    rows = importer.parse(DE_CSV, _profiles())["rows"]
    existing = [{"date": "2026-09-03", "kind": "expense", "amount": 64.2}, {"date": "2026-09-25", "kind": "income", "amount": 3400}]
    marked = importer.mark_duplicates(rows, existing)
    assert [m["duplicate"] for m in marked] == [False, True, False, True]    # the second coffee of the day is new


def test_bad_profiles_are_reported_not_used(tmp_path):
    (tmp_path / "mine.yaml").write_text("import_profiles:\n  - id: broken\n    columns: {amount: Betrag}\n"
                                        "  - id: ok\n    match: {headers_all: [Datum, Summe]}\n    columns: {date: Datum, amount: Summe}\n"
                                        "    date_format: '%d.%m.%Y'\n", encoding="utf-8")
    out, errs = load_import_profiles(tmp_path, {})
    assert [p["id"] for p in out][:1] == ["ok"] and any("broken" in e for e in errs)
    assert importer.parse("Datum;Summe\n02.01.2026;-3,00\n".encode(), out)["rows"][0]["amount"] == 3.0


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"}).status_code == 200
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 0, "liquid": 1}).json()["id"]
    return c


def _b64(b):
    return "data:text/csv;base64," + base64.b64encode(b).decode()


def test_preview_then_apply_then_preview_again_shows_duplicates(client):
    p = client.post("/import/preview", json={"account_id": client.acc, "filename": "sept.csv", "data": _b64(DE_CSV)}).json()
    assert p["new"] == 4 and p["account"]["currency"] == "EUR"
    assert client.get("/api/transactions").json() == []                       # a preview saves nothing
    r = client.post("/import/apply", json={"account_id": client.acc, "filename": "sept.csv", "rows": p["rows"]}).json()
    assert r["imported"] == 4
    txs = client.get("/api/transactions").json()
    assert len(txs) == 4 and {t["note"] for t in txs} >= {"Arbeitgeber GmbH · Gehalt September"}
    again = client.post("/import/preview", json={"account_id": client.acc, "filename": "sept.csv", "data": _b64(DE_CSV)}).json()
    assert again["new"] == 0 and all(x["duplicate"] for x in again["rows"])
    audit = client.app.state.get_ctx().db.list("audit")
    assert any(a["action"] == "Imported 4 entries into Giro" for a in audit)


def test_apply_is_all_or_nothing(client):
    rows = [{"date": "2026-09-01", "kind": "expense", "amount": 5, "description": "ok"},
            {"date": "not a date", "kind": "expense", "amount": 6, "description": "bad"}]
    r = client.post("/import/apply", json={"account_id": client.acc, "rows": rows})
    assert r.status_code == 400 and "Nothing was saved" in r.json()["detail"]
    assert client.get("/api/transactions").json() == []
    assert client.post("/import/apply", json={"account_id": client.acc, "rows": [{"date": "2026-09-01", "kind": "transfer", "amount": 5}]}).status_code == 400
    assert client.post("/import/apply", json={"account_id": client.acc, "rows": [{"date": "2026-09-01", "kind": "expense", "amount": -5}]}).status_code == 400


def test_preview_needs_an_account_and_a_readable_file(client):
    assert client.post("/import/preview", json={"account_id": 999, "data": _b64(DE_CSV)}).status_code == 400
    r = client.post("/import/preview", json={"account_id": client.acc, "data": _b64(b"nothing,useful\n1,2\n")})
    assert r.status_code == 400 and "import profiles" in r.json()["detail"]
    assert client.post("/import/preview", json={"account_id": client.acc, "data": "%%%"}).status_code == 400
    assert [p["id"] for p in client.get("/import/profiles").json()][-1] == "generic_date_description_amount"
