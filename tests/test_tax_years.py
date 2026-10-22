"""Tax packs: year tables cover the years people file now, deadlines are complete, weekends roll to Monday."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.packs import available_packs  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from aaryaai_finance.tax import engines  # noqa: E402
from conftest import local_client  # noqa: E402


def _calc(pack, engine):
    return next(c for c in available_packs()[pack]["calculators"] if c["engine"] == engine)


def test_german_year_tables_cover_last_year_and_this_year():
    """Fails when a new year starts and the pack hasn't been updated: last year's return and this year's estimate need it."""
    p = _calc("DE", "de_32a_refund")["params"]
    y = date.today().year
    for table in ("tariffs", "soli_freigrenze"):
        have = {int(k) for k in p[table]}
        assert {y - 1, y} <= have, f"DE {table} needs {y - 1} and {y} (has {sorted(have)})"


def test_soli_rates_come_from_the_pack():
    p = dict(_calc("DE", "de_32a_refund")["params"])
    year = max(int(k) for k in p["tariffs"])
    base = engines.run("de_32a_refund", p, {"year": year, "gross": 120000, "lohnsteuer": 30000}, "EUR")
    p["soli_rate"] = 0.0
    p["soli_zone_rate"] = 0.0
    none = engines.run("de_32a_refund", p, {"year": year, "gross": 120000, "lohnsteuer": 30000}, "EUR")
    assert dict(base["rows"])["Soli"] != dict(none["rows"])["Soli"] and dict(none["rows"])["Soli"].endswith("0")


def test_india_calculator_says_which_financial_year():
    c = _calc("IN", "in_regimes")
    r = engines.run("in_regimes", c["params"], {"resident": True, "other_income": 900000}, "INR")
    assert ["Rates for financial year", "2025-26"] in r["rows"] and "FY 2025-26" in r["explanation"]


def _client(tmp_path, countries, answers):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": countries, "base_currency": "EUR", "answers": answers}).status_code == 200
    return c


def test_india_advance_tax_has_all_four_instalments_and_form16(tmp_path):
    c = _client(tmp_path, ["IN"], {"in_advance_tax": True, "in_salary": True})
    rules = c.app.state.get_ctx().rules
    got = {d["rule_id"] for d in rules.deadlines({"in_advance_tax": True, "in_salary": True}, today=date(2026, 5, 1))}
    assert {"in_advance_tax_q1", "in_advance_tax_q2", "in_advance_tax_q3", "in_advance_tax_q4", "in_form16"} <= got
    assert not {"in_advance_tax_q1", "in_form16"} & {d["rule_id"] for d in rules.deadlines({}, today=date(2026, 5, 1))}


def test_german_prepayments_and_weekend_roll(tmp_path):
    c = _client(tmp_path, ["DE"], {"de_prepayments": True, "de_mandatory_filing": True})
    rules = c.app.state.get_ctx().rules
    dls = rules.deadlines({"de_prepayments": True, "de_mandatory_filing": True}, today=date(2027, 1, 5))
    q = {d["due"] for d in dls if d["rule_id"].startswith("de_prepay_")}
    assert {"2027-03-10", "2027-06-10", "2027-09-10", "2027-12-10"} <= q
    ret = next(d for d in dls if d["rule_id"] == "de_return_mandatory" and d["moved_from"] == "2027-07-31")   # a Saturday
    assert ret["due"] == "2027-08-02" and ret["key"] == "de_return_mandatory:2027-07-31" and "weekend" in ret["detail"]
    weekday = next(d for d in dls if d["rule_id"] == "de_prepay_q1" and d["due"] == "2027-03-10")         # a Wednesday: unchanged
    assert weekday["moved_from"] is None
