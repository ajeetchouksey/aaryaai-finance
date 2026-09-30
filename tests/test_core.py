import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml  # noqa: E402
from aaryaai_finance.core import planning, trading  # noqa: E402
from aaryaai_finance.tax import engines  # noqa: E402

PACKS = Path(__file__).resolve().parents[1] / "aaryaai_finance" / "packs"
DE = {c["id"]: c for c in yaml.safe_load((PACKS / "DE" / "pack.yaml").read_text(encoding="utf-8"))["calculators"]}
IN = {c["id"]: c for c in yaml.safe_load((PACKS / "IN" / "pack.yaml").read_text(encoding="utf-8"))["calculators"]}
TARIFF = DE["refund"]["params"]["tariffs"]


def de_tax(zve, year, joint=False):
    t = TARIFF[year]
    return 2 * engines.de_income_tax(zve / 2, t) if joint else engines.de_income_tax(zve, t)


def in_tax(regime, **kw):
    return engines._in_regime(IN["regimes"]["params"], kw, regime)


def test_de_zero_below_allowance():
    assert de_tax(12348, 2026) == 0
    assert de_tax(12096, 2025) == 0


def test_de_zones_continuous():
    for y, (gfb, z2, a2, z3, a3, c3, c4, z4, c5) in TARIFF.items():
        for edge in (z2, z3, z4):
            assert abs(de_tax(edge + 1, y) - de_tax(edge, y)) <= 2, (y, edge)


def test_de_splitting_saves_money():
    assert de_tax(100000, 2026, joint=True) < de_tax(100000, 2026)


def test_de_top_rate():
    assert de_tax(300000, 2026) == int(0.45 * 300000 - 19470.38)


def test_de_refund_engine():
    r = engines.run("de_32a_refund", DE["refund"]["params"], {"year": 2025, "gross": 95000, "lohnsteuer": 19000,
                    "werbungskosten": 2500, "vorsorge": 12000, "joint": True}, "EUR")
    assert r["headline_label"] == "Estimated refund" and r["headline"] == "€4,200"


def test_in_new_regime_resident_rebate():
    assert in_tax("new", salary=1275000, resident=True)["total"] == 0


def test_in_nri_no_rebate():
    assert in_tax("new", other_income=800000, resident=False)["total"] == 20800


def test_in_old_regime_with_deductions():
    r = in_tax("old", salary=1500000, ded_80c=150000, ded_80d=25000, home_loan_interest=200000, resident=True)
    assert r["taxable"] == 1075000 and r["total"] == round(135000 * 1.04)


def test_in_ltcg_exemption():
    assert in_tax("new", ltcg_equity=225000, resident=False)["cg"] == 12500


def test_property_tds_due_date():
    r = engines.run("in_property_tds", IN["property_tds"]["params"], {"consideration": 14000000, "instalment": 700000, "paid_on": "2026-08-12"}, "INR")
    assert r["headline"] == "₹7,000" and ["Deposit by", "30 Sep 2026"] in r["rows"]


def test_required_monthly_hits_target():
    m = planning.required_monthly(100000, 10000, 0.06, 120)
    assert abs(planning.future_value(10000, m, 0.06, 120) - 100000) < 1


def test_goal_plan_status():
    g = planning.plan_goal("x", 10000, date(2030, 1, 1), 10000, 0, 0.0, 0.0, today=date(2026, 1, 1))
    assert g["status"] == "on_track"


def test_backtest_buy_hold_matches_price():
    p = trading.synthetic_prices(5)
    r = trading.backtest(p, "buy_hold", 10000, cost_pct=0)
    assert abs(r["metrics"]["final"] - 10000 * p.iloc[-1] / p.iloc[0]) < 1
    for s in trading.STRATEGIES:
        trading.backtest(p, s)


def test_paper_positions():
    trades = [{"ts": "1", "ticker": "A", "side": "buy", "qty": 10, "price": 100, "fee": 1},
              {"ts": "2", "ticker": "A", "side": "sell", "qty": 5, "price": 120, "fee": 1}]
    st = trading.paper_positions(trades, 10000)
    assert st["cash"] == 10000 - 1001 + 599
    assert st["positions"]["A"]["qty"] == 5
    assert st["realized_pnl"] == round(5 * (120 - 100.1) - 1, 2)
