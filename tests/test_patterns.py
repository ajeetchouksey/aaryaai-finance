"""Spotting monthly payments: deterministic, never doubling what is logged, and only proposed."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.core.patterns import find_monthly  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402

TODAY = date(2026, 10, 22)


def tx(d, amount, note="Netflix", kind="expense", acc=1, cat="Subscriptions", **kw):
    return {"date": d, "amount": amount, "note": note, "kind": kind, "account_id": acc, "category": cat, **kw}


def test_three_months_in_a_row_with_similar_amount_and_day():
    rows = [tx("2026-07-05", 12.99), tx("2026-08-04", 12.99), tx("2026-09-06", 13.49), tx("2026-10-05", 13.49)]
    f = find_monthly(rows, [], TODAY)
    assert len(f) == 1
    assert f[0]["months"] == 4 and f[0]["day"] == 5 and f[0]["next_date"] == "2026-11-05" and f[0]["category"] == "Subscriptions"


@pytest.mark.parametrize("rows", [
    [tx("2026-08-05", 12.99), tx("2026-10-05", 12.99)],                                       # only two, with a gap
    [tx("2026-07-05", 10), tx("2026-08-05", 25), tx("2026-09-05", 10)],                       # amounts differ too much
    [tx("2026-07-01", 10), tx("2026-08-20", 10), tx("2026-09-10", 10)],                       # no regular day
    [tx("2026-07-05", 10, recurring_id=3), tx("2026-08-05", 10, recurring_id=3), tx("2026-09-05", 10, recurring_id=3)],   # already repeating
    [tx("2026-07-05", 10, note="", cat=""), tx("2026-08-05", 10, note="", cat=""), tx("2026-09-05", 10, note="", cat="")],  # nothing to name it by
])
def test_not_a_pattern(rows):
    assert find_monthly(rows, [], TODAY) == []


def test_covered_by_an_existing_repeating_entry():
    rows = [tx("2026-07-05", 12.99), tx("2026-08-05", 12.99), tx("2026-09-05", 12.99)]
    rec = [{"account_id": 1, "kind": "expense", "amount": 13.0, "frequency": "monthly", "active": 1}]
    assert find_monthly(rows, rec, TODAY) == []


def test_next_date_is_after_today():
    rows = [tx("2026-07-02", 800, note="Rent"), tx("2026-08-02", 800, note="Rent"), tx("2026-09-02", 800, note="Rent")]
    assert find_monthly(rows, [], TODAY)[0]["next_date"] == "2026-11-02"   # October's hasn't been logged yet: not invented


def test_routine_proposes_and_approval_adds_the_repeating_entry(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"})
    acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 0, "liquid": 1}).json()["id"]
    from aaryaai_finance.core.ledger import _add_months
    first = date.today().replace(day=1)
    for m in (-3, -2, -1):
        d = _add_months(first, m, 3).isoformat()
        c.post("/api/transactions", json={"date": d, "kind": "expense", "account_id": acc, "amount": 49.9, "category": "Utilities & internet", "note": "Gym membership"})
    r = c.post("/routines/run", json={"id": "repeat_finder"}).json()
    assert r["ran"][0]["status"] == "ok"
    prop = next(p for p in r["proposals"] if p["key"].startswith("repeat:"))
    assert "Gym membership" in prop["title"] and prop["status"] == "pending"
    before = len(c.get("/api/transactions").json())
    assert c.post(f"/proposals/{prop['id']}", json={"decision": "approve"}).json()["ok"]
    rec = c.get("/api/recurring").json()
    assert rec[0]["frequency"] == "monthly" and rec[0]["amount"] == 49.9 and rec[0]["start_date"] > date.today().isoformat()
    assert len(c.get("/api/transactions").json()) == before                  # nothing back-filled
    again = c.post("/routines/run", json={"id": "repeat_finder"}).json()       # covered now: not proposed again
    assert not [p for p in again["proposals"] if p["key"].startswith("repeat:") and p["status"] == "pending"]
