"""Budget vs actual: this month's spending against each budget line, and a warning on Home when one is over."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.core import ledger  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE", "IN"], "base_currency": "EUR"}).status_code == 200
    c.post("/config", json={"fx": {"source": "manual", "manual_rates": {"INR": 100}}})
    c.eur = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 5000, "liquid": 1}).json()["id"]
    c.inr = c.post("/api/accounts", json={"name": "NRE", "country": "IN", "currency": "INR", "opening_balance": 100000, "liquid": 1}).json()["id"]
    for cat, amt in (("Groceries", 400), ("Eating out", 100), ("Transport", 60)):
        c.post("/api/expenses", json={"category": cat, "amount": amt})
    c.today = date.today().isoformat()
    return c


def spend(c, acc, amount, cat):
    assert c.post("/api/transactions", json={"date": c.today, "kind": "expense", "account_id": acc, "amount": amount, "category": cat}).status_code == 200


def test_spent_is_compared_per_category_in_the_base_currency(client):
    spend(client, client.eur, 300, "Groceries")
    spend(client, client.inr, 15000, "Groceries")            # ₹15,000 = €150 at 100 → 450 of 400
    spend(client, client.eur, 92, "Eating out")              # 92% of 100
    spend(client, client.eur, 25, "Gifts")                   # no budget line
    s = client.get("/budget/status").json()
    rows = {r["category"]: r for r in s["rows"]}
    assert rows["Groceries"]["spent"] == 450 and rows["Groceries"]["status"] == "over" and rows["Groceries"]["left"] == -50
    assert rows["Eating out"]["status"] == "near" and rows["Transport"]["status"] == "ok" and rows["Transport"]["spent"] == 0
    spend(client, client.eur, 60, "Transport")                # exactly the budget, like a monthly ticket
    assert {r["category"]: r for r in client.get("/budget/status").json()["rows"]}["Transport"]["status"] == "full"
    assert s["unbudgeted"] == [{"category": "Gifts", "spent": 25}]
    assert s["budget_total"] == 560 and 0 < s["days_gone"] <= 1
    home = client.get("/home").json()
    assert [r["category"] for r in home["budget_over"]] == ["Groceries"]


def test_no_budget_lines_means_no_warning(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"})
    assert c.get("/budget/status").json()["rows"] == [] and c.get("/home").json()["budget_over"] == []


def test_wants_list_comes_from_the_server(client):
    cf = client.get("/calc/cashflow").json()
    assert "Eating out" in cf["wants"] and cf["base"] == "EUR"


def test_last_month_does_not_count(client):
    first = date.today().replace(day=1)
    last_month = ledger._add_months(first, -1, 15).isoformat()
    client.post("/api/transactions", json={"date": last_month, "kind": "expense", "account_id": client.eur, "amount": 999, "category": "Transport"})
    rows = {r["category"]: r for r in client.get("/budget/status").json()["rows"]}
    assert rows["Transport"]["spent"] == 0
