"""Category rules: a payee or note sets the category, the same way every time; yours win over the packs'."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.core.categorize import categorize, check_category_rule  # noqa: E402
from aaryaai_finance.packs import available_packs  # noqa: E402
from aaryaai_finance.rules.engine import load_category_rules  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402


def _rules(folder=None):
    out, errs = load_category_rules(folder, {k: v for k, v in available_packs().items() if k in ("DE", "IN")})
    return out, errs


@pytest.mark.parametrize("text,kind,want", [
    ("REWE Markt GmbH, Berlin", "expense", "Groceries"), ("Hausverwaltung Muster · Miete Oktober", "expense", "Rent / Warmmiete"),
    ("Arbeitgeber GmbH · Gehalt Oktober", "income", "Salary"), ("UPI-BIGBASKET-ORDER", "expense", "Groceries"),
    ("Health insurance premium", "expense", None),          # "premium" must not look like an EMI
    ("Lohnsteuer Nachzahlung", "expense", None),            # salary words only count for income
    ("", "expense", None)])
def test_pack_rules(text, kind, want):
    rules, errs = _rules()
    assert not errs
    assert categorize(text, kind, rules)[0] == want


def test_your_rule_replaces_a_pack_rule_and_comes_first(tmp_path):
    (tmp_path / "mine.yaml").write_text(
        "category_rules:\n  - {id: de_groceries, category: Eating out, match: {text_any: [rewe]}}\n"
        "  - {id: pets, category: Pets, kind: expense, match: {text_any: [fressnapf]}}\n"
        "  - {id: bad, category: X, match: {text_any: [ab]}}\n", encoding="utf-8")
    rules, errs = _rules(tmp_path)
    assert categorize("REWE", "expense", rules) == ("Eating out", "de_groceries")
    assert categorize("Fressnapf Filiale", "expense", rules) == ("Pets", "pets")
    assert any("bad" in e and "3 letters" in e for e in errs)


def test_rule_checks():
    assert check_category_rule({"id": "x", "category": "A", "match": {"text_any": ["abc"]}}) == []
    assert check_category_rule({"id": "x", "match": {"text_any": ["abc"]}})
    assert check_category_rule({"id": "x", "category": "A", "match": {}})
    assert check_category_rule({"id": "x", "category": "A", "kind": "transfer", "match": {"text_any": ["abc"]}})


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"}).status_code == 200
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 0, "liquid": 1}).json()["id"]
    return c


def test_import_preview_fills_categories_and_apply_keeps_your_choice(client):
    csv = ("Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag\n"
           "02.10.2026;Einkauf;REWE Markt;-23,10\n03.10.2026;Kaffee;Cafe Beispiel;-3,20\n").encode()
    p = client.post("/import/preview", json={"account_id": client.acc, "data": base64.b64encode(csv).decode()}).json()
    assert [(r["category"], r["category_rule"]) for r in p["rows"]] == [("Groceries", "de_groceries"), (None, None)]
    rows = [p["rows"][0], {**p["rows"][1], "category": "Eating out"}]
    assert client.post("/import/apply", json={"account_id": client.acc, "rows": rows}).json()["imported"] == 2
    assert sorted(t["category"] for t in client.get("/api/transactions").json()) == ["Eating out", "Groceries"]


def test_categorize_endpoint_and_rule_categories_are_pickable(client):
    assert client.post("/categorize", json={"text": "Stadtwerke Abschlag", "kind": "expense"}).json() == {"category": "Utilities & internet", "rule": "de_utilities"}
    assert client.post("/categorize", json={"text": "nothing known", "kind": "expense"}).json()["category"] is None
    client.post("/rules/user", json={"text": "category_rules:\n  - {id: pets, category: Pets, kind: expense, match: {text_any: [fressnapf]}}\n"})
    assert "Pets" in client.get("/money/meta").json()["expense_categories"]
