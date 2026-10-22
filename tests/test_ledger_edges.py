"""Ledger and forecast edge cases: skipped repeating entries, missing rates, overdue deadlines, short histories, bad settings."""
import copy
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance import model as M  # noqa: E402
from aaryaai_finance.core import forecast as fc, ledger  # noqa: E402
from aaryaai_finance.core.db import DB  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"}).status_code == 200
    c.ctx = c.app.state.get_ctx
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 5000,
                                          "opening_date": "2020-01-01", "liquid": 1}).json()["id"]
    return c


def test_a_removed_occurrence_stays_removed(client):
    start = ledger._add_months(date.today().replace(day=1), -3, 1)
    client.post("/api/recurring", json={"kind": "expense", "account_id": client.acc, "amount": 900, "category": "Rent",
                                        "frequency": "monthly", "start_date": start.isoformat()})
    txs = [t for t in client.get("/api/transactions").json() if t["recurring_id"]]
    assert len(txs) >= 3
    gone = txs[1]
    assert client.delete(f"/api/transactions/{gone['id']}").json()["ok"]
    ledger.materialize_recurring(client.ctx().db)
    client.get("/money/accounts")                                        # every screen load materialises again
    left = [t for t in client.get("/api/transactions").json() if t["recurring_id"]]
    assert len(left) == len(txs) - 1 and gone["date"] not in {t["date"] for t in left}
    assert gone["date"] in ledger.skipped_dates(client.get("/api/recurring").json()[0]["skip_dates"])


def test_moving_an_occurrence_does_not_create_a_duplicate(client):
    start = ledger._add_months(date.today().replace(day=1), -2, 31)
    client.post("/api/recurring", json={"kind": "income", "account_id": client.acc, "amount": 3000, "category": "Salary",
                                        "frequency": "monthly", "start_date": start.isoformat()})
    t = next(t for t in client.get("/api/transactions").json() if t["recurring_id"])
    moved = (date.fromisoformat(t["date"]) + timedelta(days=1)).isoformat()
    assert client.post("/api/transactions", json={**t, "date": moved}).status_code == 200
    ledger.materialize_recurring(client.ctx().db)
    dates = [x["date"] for x in client.get("/api/transactions").json() if x["recurring_id"]]
    assert moved in dates and t["date"] not in dates


def test_v3_database_gains_skip_dates_with_a_backup(tmp_path):
    v4, _ = M.build()
    v3 = copy.deepcopy(v4)
    v3["version"] = 3
    del v3["entities"]["recurring"]["fields"]["skip_dates"]
    v3["entities"].pop("loans", None)                                   # added later (v5)
    p = tmp_path / "finance.db"
    old = DB(p, v3)
    a = old.upsert("accounts", {"name": "Giro", "country": "DE", "currency": "EUR"})
    old.upsert("recurring", {"kind": "expense", "account_id": a, "amount": 10, "frequency": "monthly", "start_date": "2026-01-01"})
    new = DB(p, v4, tmp_path / "backups")
    assert "recurring" in new.sync_report["rebuilt"] and Path(new.sync_report["backup"]).exists()
    r = new.list("recurring")[0]
    assert r["amount"] == 10 and r["skip_dates"] is None
    assert sqlite3.connect(p).execute("PRAGMA user_version").fetchone() == (v4["version"],)


def test_forecast_survives_a_missing_exchange_rate():
    today = date(2026, 9, 30)
    accounts = [{"id": 1, "name": "Giro", "currency": "EUR", "balance": 5000, "liquid": 1, "archived": 0, "in_networth": 1},
                {"id": 2, "name": "US", "currency": "USD", "balance": 100, "liquid": 1, "archived": 0, "in_networth": 1}]
    planned = [{"id": 1, "date": "2026-11-01", "kind": "transfer", "account_id": 1, "to_account_id": 2, "amount": 500, "to_amount": None,
                "confidence": "planned", "done": 0, "note": "to US"},
               {"id": 2, "date": "2027-02-01", "kind": "expense", "account_id": 2, "amount": 4000, "confidence": "known", "done": 0, "note": "US bill"}]
    f = fc.forecast(accounts, [], planned, [], [], {"_base": "EUR", "EUR": 1.0}, "EUR", {"USD": 50}, 12, today=today)
    assert f["missing_rates"] == ["EUR→USD"]
    usd = [s for s in f["plan"] + f.get("unfunded", []) if s["ccy"] == "USD"]
    assert usd and all(s.get("unfunded") for s in usd)                       # can't size a transfer without a rate


def test_missed_deadlines_show_as_late_for_a_month(client):
    y = date.today().year
    client.post("/rules/user", json={"text": 'deadlines:\n  - id: my_jan\n    title: "My January form"\n    due: "{year}-01-15"\n    source: me\n'})
    rules = client.ctx().rules
    keys = lambda today: {d["key"] for d in rules.deadlines({}, today=today)}       # noqa: E731
    assert f"my_jan:{y}-01-15" in keys(date(y, 1, 20))                     # 5 days late: still listed
    assert f"my_jan:{y}-01-15" not in keys(date(y, 3, 1))                  # long gone


def test_averages_use_only_the_months_you_have(client):
    first = date.today().replace(day=1)
    last_month = ledger._add_months(first, -1, 10)
    client.post("/api/transactions", json={"date": last_month.isoformat(), "kind": "expense", "account_id": client.acc, "amount": 600})
    a = ledger.monthly_actuals(client.ctx().db, "EUR", {"_base": "EUR", "EUR": 1.0})
    assert a["months"] == 1 and a["expense"] == 600


@pytest.mark.parametrize("body", [{"monthly_income": "abc"}, {"paper_starting_cash": 0}, {"monthly_income": -5}])
def test_bad_settings_are_refused(client, body):
    assert client.post("/api-settings", json=body).status_code == 400


def test_clearing_monthly_income_falls_back_to_money(client):
    assert client.post("/api-settings", json={"monthly_income": 4000}).status_code == 200
    assert client.post("/api-settings", json={"monthly_income": ""}).status_code == 200
    assert client.ctx().db.settings()["monthly_income"] == ""


def test_bad_manual_rates_are_refused_and_never_break_screens(client):
    assert client.post("/config", json={"fx": {"manual_rates": {"INR": "lots"}}}).status_code == 400
    client.ctx().settings.config["fx"]["manual_rates"] = {"INR": "lots"}           # as if config.yaml was edited by hand
    assert client.get("/home").status_code == 200
