"""Goal planning, net worth and cash-flow maths — all pure functions.

Plain-English glossary used across the app:
- Net worth: everything you own minus everything you owe.
- Savings rate: share of take-home pay you don't spend. 20%+ is healthy,
  30%+ builds wealth fast.
- Emergency fund: cash you can reach in days. Aim for 3-6 months of expenses.
- Expected return: a *guess* at yearly growth. Rough long-run guides:
  savings account 2-3%, Indian FD 6-7%, bonds 3-4%, global equity ETF 6-8%
  (with big ups and downs along the way).
- Inflation: prices rise ~2% a year in the eurozone, ~5% in India, so a goal
  10 years away costs more than today's price.
"""
from __future__ import annotations

from datetime import date


SYMBOLS = {"EUR": "€", "INR": "₹", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF ", "SGD": "S$", "AED": "AED ", "AUD": "A$", "CAD": "C$"}


def fmt(amount: float, currency: str = "EUR") -> str:
    """€12,345 / $12,345 or ₹12,34,567 (Indian lakh grouping)."""
    if currency != "INR":
        return f"{SYMBOLS.get(currency, currency + ' ')}{amount:,.0f}"
    neg, n = amount < 0, str(int(round(abs(amount))))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        n = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + n


def months_between(start: date, end: date) -> int:
    return max((end.year - start.year) * 12 + (end.month - start.month), 0)


def future_value(pv: float, monthly: float, annual_return: float, months: int) -> float:
    r = annual_return / 12
    if r == 0:
        return pv + monthly * months
    g = (1 + r) ** months
    return pv * g + monthly * (g - 1) / r


def required_monthly(target: float, pv: float, annual_return: float, months: int) -> float:
    if months <= 0:
        return max(target - pv, 0)
    r = annual_return / 12
    if r == 0:
        return max((target - pv) / months, 0)
    g = (1 + r) ** months
    return max((target - pv * g) * r / (g - 1), 0)


def plan_goal(name: str, target_today: float, target_date: date, saved: float,
              monthly: float, annual_return: float, inflation: float,
              currency: str = "EUR", today: date | None = None) -> dict:
    today = today or date.today()
    n = months_between(today, target_date)
    target_future = target_today * (1 + inflation) ** (n / 12)
    projected = future_value(saved, monthly, annual_return, n)
    need = required_monthly(target_future, saved, annual_return, n)
    pct = projected / target_future if target_future else 1
    if pct >= 1:
        status, verdict = "on_track", "On track"
    elif pct >= 0.85:
        status, verdict = "close", "Slightly behind"
    else:
        status, verdict = "behind", "Behind"
    f = lambda v: fmt(v, currency)  # noqa: E731
    gap = need - monthly
    expl = (
        f"You need {f(target_future)} in {n} months"
        + (f" (that's {f(target_today)} in today's money, grown by {inflation:.0%} yearly inflation)" if inflation else "")
        + f". Saving {f(monthly)}/month at {annual_return:.1%} growth gets you to about {f(projected)} ({pct:.0%} of target). "
    )
    if gap > 1:
        expl += f"To close the gap, save about {f(need)}/month ({f(gap)} more)."
    else:
        expl += f"You could even save {f(-gap)}/month less and still make it."
    # year-by-year projection for the chart
    path, bal = [], saved
    r = annual_return / 12
    for m in range(n + 1):
        if m % 3 == 0 or m == n:
            path.append({"month": m, "balance": round(bal, 2),
                         "target": round(target_today * (1 + inflation) ** (m / 12), 2)})
        bal = bal * (1 + r) + monthly
    return {"name": name, "months": n, "target_future": round(target_future, 2),
            "projected": round(projected, 2), "required_monthly": round(need, 2),
            "progress_pct": round(pct, 4), "status": status, "verdict": verdict,
            "explanation": expl, "path": path, "currency": currency}


def net_worth(items: list[dict], base: str, rates: dict) -> dict:
    """items: {name, kind: asset|liability, category, amount, currency, liquid} -> totals in the base currency."""
    from .fx import convert
    conv = lambda i: convert(i["amount"], i["currency"], base, rates)  # noqa: E731
    assets = [i for i in items if i["kind"] == "asset"]
    liabs = [i for i in items if i["kind"] == "liability"]
    ta, tl = sum(conv(i) for i in assets), sum(conv(i) for i in liabs)
    by_cat, by_ccy = {}, {}
    for i in assets:
        v = conv(i)
        by_cat[i["category"]] = by_cat.get(i["category"], 0) + v
        by_ccy[i["currency"]] = by_ccy.get(i["currency"], 0) + v
    liquid = sum(conv(i) for i in assets if i.get("liquid"))
    return {"base": base, "assets": round(ta, 2), "liabilities": round(tl, 2), "net_worth": round(ta - tl, 2),
            "liquid": round(liquid, 2),
            "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda x: -x[1])},
            "by_currency": {k: round(v, 2) for k, v in by_ccy.items()}}


def cash_flow(income_monthly: float, expenses: list[dict], liquid: float) -> dict:
    spend = sum(e["amount"] for e in expenses)
    savings = income_monthly - spend
    rate = savings / income_monthly if income_monthly else 0
    months_cover = liquid / spend if spend else 0
    tips = []
    if rate < 0.2:
        tips.append("Savings rate below 20% — look at your two biggest categories first; small cuts there beat many tiny cuts.")
    elif rate >= 0.3:
        tips.append("Savings rate 30%+ — excellent. Make sure the surplus is invested, not idling in a current account.")
    if months_cover < 3:
        tips.append(f"Cash covers only {months_cover:.1f} months of spending — build to 3-6 months before investing more in shares.")
    elif months_cover > 9:
        tips.append(f"You hold {months_cover:.0f} months of spending in cash — more than needed; the excess loses value to inflation.")
    return {"income": income_monthly, "spend": round(spend, 2), "savings": round(savings, 2),
            "savings_rate": round(rate, 4), "emergency_months": round(months_cover, 1), "tips": tips}
