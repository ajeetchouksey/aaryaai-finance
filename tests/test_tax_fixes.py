"""Tax edge cases: how answers are read, when a holding turns long-term, and tax years a pack doesn't have."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.packs import available_packs  # noqa: E402
from aaryaai_finance.rules.engine import _to_float  # noqa: E402
from aaryaai_finance.tax import engines, opportunities as op, workspace as tw  # noqa: E402


@pytest.mark.parametrize("text,value", [
    ("12,500", 12500), ("1,234", 1234), ("68.400,00", 68400), ("68,400.00", 68400), ("1,20,000", 120000),
    ("12,50", 12.5), ("12,5", 12.5), ("50000", 50000), ("€ 1.234,56", 1234.56), ("₹2,50,000", 250000), ("-5", -5)])
def test_numbers_are_read_the_same_everywhere(text, value):
    assert _to_float(text) == pytest.approx(value)
    assert tw._coerce({"type": "number"}, text) == pytest.approx(value)


def test_numeric_answers_and_blanks():
    assert tw._coerce({"type": "number"}, 4200) == 4200 and tw._coerce({"type": "number"}, "") is None
    assert tw._coerce({"type": "number"}, "abc") is None


@pytest.mark.parametrize("bought,first_long_term_day", [
    ("2025-01-31", "2026-02-01"), ("2025-01-28", "2026-01-29"), ("2024-02-29", "2025-03-01"), ("2025-12-31", "2027-01-01")])
def test_long_term_starts_the_day_after_the_anniversary(bought, first_long_term_day):
    assert op.long_term_from(date.fromisoformat(bought), 12).isoformat() == first_long_term_day


def test_india_countdown_for_a_month_end_purchase():
    h = {"name": "Nifty", "qty": 10, "avg_cost": 100, "last_price": 200, "currency": "INR", "country": "IN", "bought": "2025-01-31"}
    d = op.Data(date(2026, 1, 20), "EUR", {"_base": "EUR", "EUR": 1.0, "INR": 100.0}, {}, [], [h], {})
    cards, _ = op.run_all({"IN": available_packs()["IN"]}, d)
    cd = next(c for c in cards if c["rule"] == "in.short_to_long")
    assert cd["deadline"] == "2026-02-01" and cd["extra"]["days"] == 12        # was 29 Jan: selling then would be short-term


def test_sale_on_the_anniversary_is_still_short_term():
    packs = available_packs()
    h = {"qty": 10, "avg_cost": 100, "last_price": 200, "currency": "INR", "country": "IN", "bought": "2025-03-15"}
    _, on_day = op.tax_on_sale(packs, h, 2000, date(2026, 3, 15))
    _, after = op.tax_on_sale(packs, h, 2000, date(2026, 3, 16))
    assert "short-term" in on_day and "long-term" in after


def test_a_tax_year_the_pack_lacks_is_an_error_not_another_years_numbers():
    de = available_packs()["DE"]
    calc = next(c for c in de["calculators"] if c["engine"] == "de_32a_refund")
    years = sorted(int(y) for y in calc["params"]["tariffs"])
    ok = engines.run("de_32a_refund", calc["params"], {"year": years[-1], "gross": 50000, "lohnsteuer": 8000}, "EUR")
    assert ok["headline"]
    with pytest.raises(ValueError, match=f"no income tax tariff for {years[0] - 1}"):
        engines.run("de_32a_refund", calc["params"], {"year": years[0] - 1, "gross": 50000}, "EUR")
