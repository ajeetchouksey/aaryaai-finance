"""Accounts, income/expense transactions and repeating entries — in any currency.

Plain English:
- Each account lives in one country and one currency (a Deutsche Bank Girokonto
  in EUR, an ICICI NRO account in INR). Its balance = opening balance + income
  - expenses +/- transfers.
- A transfer moves money between two of your accounts. If the currencies differ
  (e.g. EUR -> INR remittance) you record both sides: €1,000 out, ₹1,08,000 in.
- Repeating entries (salary monthly, rent monthly, SIP monthly, insurance
  yearly, daily coffee...) are written into the ledger automatically up to
  today, once per date — never twice.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from .db import DB
from .fx import convert

FREQUENCIES = ["daily", "weekly", "monthly", "quarterly", "yearly"]

DEFAULT_INCOME_CATEGORIES = ["Salary", "Bonus", "Interest", "Dividends", "Rent received", "Tax refund", "Gift", "Sale of asset", "Other income"]
DEFAULT_EXPENSE_CATEGORIES = ["Rent / Warmmiete", "Utilities & internet", "Groceries", "Transport", "Insurance", "Childcare & school",
                      "Eating out", "Shopping", "Travel", "Subscriptions", "Health", "Support to family",
                      "Loan / EMI", "Property payment", "Taxes & fees", "Investments / SIP", "Other"]
DEFAULT_ACCOUNT_TYPES = ["Current account", "Savings account", "Fixed deposit", "Credit card", "Broker / Depot", "Cash", "Loan", "Other"]


def _add_months(d: date, n: int, day: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def occurrences(start: date, freq: str, until: date, end: date | None = None) -> list[date]:
    """All dates of a repeating entry from start up to `until` (inclusive)."""
    stop = min(until, end) if end else until
    out, i = [], 0
    while True:
        if freq == "daily":
            d = start + timedelta(days=i)
        elif freq == "weekly":
            d = start + timedelta(weeks=i)
        elif freq == "monthly":
            d = _add_months(start, i, start.day)
        elif freq == "quarterly":
            d = _add_months(start, 3 * i, start.day)
        elif freq == "yearly":
            d = _add_months(start, 12 * i, start.day)
        else:
            raise ValueError(freq)
        if d > stop:
            return out
        out.append(d)
        i += 1
        if i > 5000:
            return out


def materialize_recurring(db: DB, today: date | None = None) -> int:
    """Write any due occurrences of repeating entries into transactions (idempotent)."""
    today = today or date.today()
    n = 0
    with db.conn() as c:
        for r in c.execute("SELECT * FROM recurring WHERE active=1").fetchall():
            end = date.fromisoformat(r["end_date"]) if r["end_date"] else None
            for d in occurrences(date.fromisoformat(r["start_date"]), r["frequency"], today, end):
                cur = c.execute(
                    "INSERT OR IGNORE INTO transactions (date, account_id, kind, amount, category, note, to_account_id, to_amount, recurring_id, created) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (d.isoformat(), r["account_id"], r["kind"], r["amount"], r["category"], r["note"],
                     r["to_account_id"], r["to_amount"], r["id"], datetime.now().isoformat(timespec="seconds")))
                n += cur.rowcount
    return n


def balances(db: DB) -> list[dict]:
    accts = {a["id"]: dict(a, balance=a["opening_balance"] or 0.0, income=0.0, expense=0.0) for a in db.list("accounts")}
    for t in db.list("transactions", "date"):
        a = accts.get(t["account_id"])
        if t["kind"] == "income" and a:
            a["balance"] += t["amount"]; a["income"] += t["amount"]
        elif t["kind"] == "expense" and a:
            a["balance"] -= t["amount"]; a["expense"] += t["amount"]
        elif t["kind"] == "transfer":
            if a:
                a["balance"] -= t["amount"]
            b = accts.get(t["to_account_id"])
            if b:
                b["balance"] += t["to_amount"] if t["to_amount"] is not None else t["amount"]
    for a in accts.values():
        a["balance"] = round(a["balance"], 2)
    return list(accts.values())


def to_ccy(amount: float, frm: str, to: str, rates: dict) -> float:
    return convert(amount, frm, to, rates)


def period_bounds(period: str, anchor: date) -> tuple[date, date]:
    if period == "day":
        return anchor, anchor
    if period == "week":
        s = anchor - timedelta(days=anchor.weekday())
        return s, s + timedelta(days=6)
    if period == "month":
        return anchor.replace(day=1), anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
    if period == "year":
        return date(anchor.year, 1, 1), date(anchor.year, 12, 31)
    raise ValueError(period)


def summary(db: DB, period: str, anchor: date, display: str, rates: dict, account_id: int | None = None) -> dict:
    """Income, expenses and categories for a period, converted to the `display` currency."""
    start, end = period_bounds(period, anchor)
    accts = {a["id"]: a for a in db.list("accounts")}
    rows = [t for t in db.list("transactions", "date DESC, id DESC")
            if start.isoformat() <= t["date"] <= end.isoformat()
            and (account_id is None or t["account_id"] == account_id or t["to_account_id"] == account_id)]
    inc = exp = 0.0
    by_cat, by_ccy = defaultdict(float), defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for t in rows:
        a = accts.get(t["account_id"])
        ccy = a["currency"] if a else display
        t["currency"] = ccy
        t["account"] = a["name"] if a else "?"
        if t["kind"] == "transfer":
            b = accts.get(t["to_account_id"])
            t["to_account"] = b["name"] if b else "?"
            t["to_currency"] = b["currency"] if b else ccy
            continue
        v = to_ccy(t["amount"], ccy, display, rates)
        by_ccy[ccy][t["kind"]] += t["amount"]
        if t["kind"] == "income":
            inc += v
        else:
            exp += v
            by_cat[t["category"] or "Other"] += v
    # trend: last 6 buckets of the same period type
    trend = []
    a = anchor
    for _ in range(6):
        s, e = period_bounds(period, a)
        i = x = 0.0
        for t in db.list("transactions"):
            if t["kind"] == "transfer" or not (s.isoformat() <= t["date"] <= e.isoformat()):
                continue
            if account_id is not None and t["account_id"] != account_id:
                continue
            acc = accts.get(t["account_id"])
            v = to_ccy(t["amount"], acc["currency"] if acc else display, display, rates)
            if t["kind"] == "income":
                i += v
            else:
                x += v
        label = {"day": s.strftime("%d %b"), "week": "Wk " + s.strftime("%d %b"), "month": s.strftime("%b %y"), "year": str(s.year)}[period]
        trend.insert(0, {"label": label, "income": round(i, 2), "expense": round(x, 2)})
        a = s - timedelta(days=1)
    return {"period": period, "start": start.isoformat(), "end": end.isoformat(), "display": display,
            "income": round(inc, 2), "expense": round(exp, 2), "net": round(inc - exp, 2),
            "by_category": {k: round(v, 2) for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])},
            "by_currency": dict(by_ccy), "transactions": rows, "trend": trend}


def monthly_actuals(db: DB, base: str, rates: dict, months: int = 3) -> dict:
    """Average monthly income/expense (base currency) over the last N full months — feeds the Plan tab."""
    today = date.today()
    first = today.replace(day=1)
    start = _add_months(first, -months, 1)
    accts = {a["id"]: a for a in db.list("accounts")}
    inc = exp = 0.0
    cats = defaultdict(float)
    n = 0
    for t in db.list("transactions"):
        if t["kind"] == "transfer" or not (start.isoformat() <= t["date"] < first.isoformat()):
            continue
        n += 1
        a = accts.get(t["account_id"])
        v = to_ccy(t["amount"], a["currency"] if a else base, base, rates)
        if t["kind"] == "income":
            inc += v
        else:
            exp += v
            cats[t["category"] or "Other"] += v
    if n == 0 and months:  # brand-new ledger: use this month so far rather than showing nothing
        cur = monthly_actuals_period(db, base, rates, first, today)
        if cur["count"]:
            return cur
    return {"months": months, "count": n, "income": round(inc / months, 2), "expense": round(exp / months, 2),
            "by_category": {k: round(v / months, 2) for k, v in cats.items()}, "basis": f"average of the last {months} full months"}


def monthly_actuals_period(db: DB, base: str, rates: dict, start: date, end: date) -> dict:
    accts = {a["id"]: a for a in db.list("accounts")}
    inc = exp = 0.0
    cats = defaultdict(float)
    n = 0
    for t in db.list("transactions"):
        if t["kind"] == "transfer" or not (start.isoformat() <= t["date"] <= end.isoformat()):
            continue
        n += 1
        a = accts.get(t["account_id"])
        v = to_ccy(t["amount"], a["currency"] if a else base, base, rates)
        if t["kind"] == "income":
            inc += v
        else:
            exp += v
            cats[t["category"] or "Other"] += v
    return {"months": 1, "count": n, "income": round(inc, 2), "expense": round(exp, 2),
            "by_category": {k: round(v, 2) for k, v in cats.items()}, "basis": "this month so far"}
