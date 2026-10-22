"""Spotting payments that come back every month, so they can become repeating entries (only with your approval).

Deterministic and explainable: entries from the same account, of the same type and with the same note (or
category), in at least three consecutive months, with amounts within 10% of each other and paid around the same
day of the month. Anything an active repeating entry already covers is left alone.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date

from ..rules.engine import squash
from .ledger import _add_months


def _label(t: dict) -> str:
    return squash(t.get("note") or "") or squash(t.get("category") or "")


def _months_apart(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def find_monthly(transactions: list[dict], recurring: list[dict], today: date, months: int = 6, min_hits: int = 3) -> list[dict]:
    start = _add_months(today.replace(day=1), -months, 1)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in transactions:
        if t.get("recurring_id") or t.get("kind") not in ("income", "expense"):
            continue
        d = date.fromisoformat(t["date"])
        lab = _label(t)
        if d < start or d > today or len(lab) < 3:
            continue
        groups[(t["account_id"], t["kind"], lab)].append({**t, "_d": d})
    active = [r for r in recurring if r.get("active") and r.get("frequency") == "monthly"]
    found = []
    for (acc, kind, lab), rows in groups.items():
        by_month = {}
        for r in sorted(rows, key=lambda x: x["_d"]):
            by_month.setdefault((r["_d"].year, r["_d"].month), r)      # one per month: the first
        seq = sorted(by_month.values(), key=lambda x: x["_d"])
        run = [seq[0]] if seq else []
        for r in seq[1:]:                                              # the latest run of consecutive months
            run = run + [r] if _months_apart(run[-1]["_d"], r["_d"]) == 1 else [r]
        if len(run) < min_hits:
            continue
        amounts = [float(r["amount"]) for r in run]
        med = statistics.median(amounts)
        if not med or any(abs(a - med) > 0.1 * med for a in amounts):
            continue
        days = [r["_d"].day for r in run]
        if max(days) - min(days) > 6:
            continue
        if any(r["account_id"] == acc and r["kind"] == kind and abs(float(r["amount"]) - med) <= 0.1 * med for r in active):
            continue
        last = run[-1]["_d"]
        day = int(statistics.median(days))
        nxt = _add_months(last, 1, day)
        while nxt <= today:                                            # start after today: nothing already logged is doubled
            nxt = _add_months(nxt, 1, day)
        found.append({"account_id": acc, "kind": kind, "amount": round(med, 2),
                      "category": Counter(r.get("category") or "" for r in run).most_common(1)[0][0],
                      "note": run[-1].get("note") or "", "day": day, "months": len(run),
                      "last_date": last.isoformat(), "next_date": nxt.isoformat(), "key": f"repeat:{acc}:{kind}:{lab}"})
    return sorted(found, key=lambda x: -x["amount"])
