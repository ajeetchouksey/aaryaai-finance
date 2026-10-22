"""Loans: an annuity schedule, the debt in net worth, instalments in the forecast (never counted twice)."""
import copy
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance import model as M  # noqa: E402
from aaryaai_finance.core.db import DB  # noqa: E402
from aaryaai_finance.core.loans import schedule  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402


def test_emi_and_outstanding_match_the_annuity_formula():
    # ₹50 lakh over 20 years at 8.5%: the well-known EMI of about ₹43,391
    s = schedule({"principal": 5_000_000, "annual_rate": 8.5, "start_date": "2026-01-10", "term_months": 240}, today=date(2026, 1, 9))
    assert s["emi"] == pytest.approx(43391, abs=1) and s["payments_made"] == 0 and s["outstanding"] == 5_000_000
    later = schedule({"principal": 5_000_000, "annual_rate": 8.5, "start_date": "2026-01-10", "term_months": 240}, today=date(2027, 1, 10))
    assert later["payments_made"] == 12 and 4_850_000 < later["outstanding"] < 4_950_000 and later["months_left"] == 228
    assert later["payoff_date"] == "2046-01-10" and later["next_payment"] == "2027-02-10"


def test_term_is_worked_out_from_the_instalment_and_zero_rate_works():
    s = schedule({"principal": 12000, "annual_rate": 0, "start_date": "2026-01-31", "emi": 1000}, today=date(2026, 3, 31))
    assert s["term_months"] == 12 and s["payments_made"] == 2 and s["outstanding"] == 10000 and s["interest_left"] == 0
    s = schedule({"principal": 10000, "annual_rate": 6, "start_date": "2026-01-01", "emi": 500}, today=date(2026, 1, 1))
    assert s["term_months"] == 22                                   # 21.1 months, rounded up


@pytest.mark.parametrize("loan,msg", [
    ({"principal": 10000, "annual_rate": 12, "start_date": "2026-01-01", "emi": 50}, "never be repaid"),
    ({"principal": 10000, "annual_rate": 5, "start_date": "2026-01-01"}, "term or the monthly"),
    ({"principal": 0, "annual_rate": 5, "start_date": "2026-01-01", "term_months": 12}, "more than zero"),
    ({"principal": 1000, "annual_rate": 5, "term_months": 12}, "start date")])
def test_impossible_loans_explain_themselves(loan, msg):
    with pytest.raises(ValueError, match=msg):
        schedule(loan)


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"}).status_code == 200
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 20000, "liquid": 1}).json()["id"]
    return c


def test_a_loan_is_a_debt_and_its_instalments_are_in_the_forecast(client):
    nw0 = client.get("/calc/position").json()["net_worth"]["net_worth"]
    start = date(date.today().year - 1, date.today().month, 1).isoformat()
    r = client.post("/api/loans", json={"name": "Car loan", "currency": "EUR", "principal": 18000, "annual_rate": 4.9, "start_date": start,
                                        "term_months": 48, "account_id": client.acc, "active": 1})
    assert r.status_code == 200
    loan = client.get("/loans").json()[0]
    assert 13000 < loan["outstanding"] < 15000 and loan["payments_made"] == 12
    nw1 = client.get("/calc/position").json()["net_worth"]["net_worth"]
    assert nw1 == pytest.approx(nw0 - loan["outstanding"], abs=0.01)
    f = client.get("/forecast").json()
    flows = [x for x in f["items"] if "Car loan" in str(x.get("label", ""))]
    assert flows and all(x["amount"] == pytest.approx(-loan["emi"]) for x in flows)
    # paying it with a repeating entry already: the forecast doesn't count it twice
    client.post("/api/recurring", json={"kind": "expense", "account_id": client.acc, "amount": loan["emi"], "category": "Loan / EMI",
                                        "note": "Car loan EMI", "frequency": "monthly", "start_date": loan["next_payment"], "active": 1})
    f2 = client.get("/forecast").json()
    assert not [x for x in f2["items"] if "Car loan instalment" in str(x.get("label", ""))]


def test_saving_an_impossible_loan_is_refused(client):
    r = client.post("/api/loans", json={"name": "X", "currency": "EUR", "principal": 10000, "annual_rate": 12, "start_date": "2026-01-01", "emi": 10})
    assert r.status_code == 400 and "never be repaid" in r.json()["detail"]


def test_v4_database_gains_the_loans_table(tmp_path):
    v5, _ = M.build()
    v4 = copy.deepcopy(v5)
    v4["version"] = 4
    del v4["entities"]["loans"]
    p = tmp_path / "finance.db"
    old = DB(p, v4)
    old.upsert("accounts", {"name": "Giro", "country": "DE", "currency": "EUR"})
    new = DB(p, v5, tmp_path / "backups")
    assert "loans" in new.sync_report["created"] and new.list("accounts")[0]["name"] == "Giro"
    assert sqlite3.connect(p).execute("PRAGMA user_version").fetchone() == (5,)
