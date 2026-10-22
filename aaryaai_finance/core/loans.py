"""Loans with a repayment schedule (annuity / EMI): what is still owed, what each month costs, when it ends.

The first instalment is due one month after the start date, then monthly on the same day. Give either the term or
the monthly instalment; the other is worked out. Rates are in percent a year, interest is charged monthly.
"""
from __future__ import annotations

import math
from datetime import date

from .ledger import _add_months


def schedule(loan: dict, today: date | None = None) -> dict:
    today = today or date.today()
    p = float(loan.get("principal") or 0)
    r = float(loan.get("annual_rate") or 0) / 100 / 12
    try:
        start = date.fromisoformat(str(loan.get("start_date") or ""))
    except ValueError:
        raise ValueError("Give the start date (YYYY-MM-DD).") from None
    n, emi = loan.get("term_months"), loan.get("emi")
    if p <= 0:
        raise ValueError("The amount borrowed must be more than zero.")
    if n:
        n = int(n)
        emi = p / n if r == 0 else p * r / (1 - (1 + r) ** -n)
    elif emi:
        emi = float(emi)
        if r and emi <= p * r:
            raise ValueError("That instalment doesn't even cover the interest, so the loan would never be repaid.")
        n = math.ceil(p / emi) if r == 0 else math.ceil(-math.log(1 - p * r / emi) / math.log(1 + r))
    else:
        raise ValueError("Give the term or the monthly instalment.")
    day = start.day
    paid = 0
    while paid < n and _add_months(start, paid + 1, day) <= today:
        paid += 1
    owed = max(p - emi * paid, 0.0) if r == 0 else max(p * (1 + r) ** paid - emi * ((1 + r) ** paid - 1) / r, 0.0)
    left = n - paid
    return {"emi": round(emi, 2), "term_months": n, "payments_made": paid, "months_left": left, "outstanding": round(owed, 2),
            "payoff_date": _add_months(start, n, day).isoformat(),
            "next_payment": _add_months(start, paid + 1, day).isoformat() if left else None,
            "interest_left": round(max(emi * left - owed, 0.0), 2), "total_interest": round(max(emi * n - p, 0.0), 2)}
