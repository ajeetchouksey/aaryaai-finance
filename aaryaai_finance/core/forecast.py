"""Cash forecast: what comes in, what goes out, and where each payment will come from.

Plain English:
- Starts from today's balances of the accounts you marked "available within a week", grouped by currency.
- Adds everything the app already knows is coming: repeating entries (salary, rent, savings plans),
  planned items you added (a bonus, a holiday, a transfer), and the stages of your staged purchases
  (a flat under construction).
- Adds what it has *learned*: your typical other spending per month in each currency (the median of
  the last six months, so one big month doesn't skew it).
- Every line carries how sure it is: known, planned, estimated or learned.
- Each currency has a floor (the least you want to keep). When a month would go below it, the funding
  plan proposes a transfer from a currency that has room, in time for the payment.

Same inputs → same result. Nothing here is advice; it is arithmetic on your own entries.
"""
from __future__ import annotations

import calendar
import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from . import ledger
from .fx import convert
from .trackers import summarize

CONF_ORDER = ["known", "planned", "estimated", "learned", "plan"]
SCENARIOS = {
    "base": "Base plan",
    "salary_late": "Salary a month late",
    "stage_early": "Next stage a month early",
    "no_estimated": "No estimated income",
    "fx_weak": "Base currency 7% weaker",
}


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def add_months(d: date, n: int, day: int | None = None) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day or d.day, calendar.monthrange(y, m)[1]))


def _nice_up(v: float) -> float:
    """Round a transfer up to a tidy number: 5,361 → 5,370; 5,28,150 → 5,29,000."""
    if v <= 0:
        return 0.0
    step = 10 ** max(int(math.log10(v)) - 2, 0)
    return float(math.ceil(v / step) * step)


def _parse_due(v) -> date | None:
    if not v:
        return None
    s = str(v)
    try:
        if len(s) == 7:
            return date(int(s[:4]), int(s[5:7]), 15)
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


class Flow(dict):
    """One dated money movement in one currency: {date, ccy, amount (+in/-out), label, confidence, source, why}."""


def collect_flows(accounts: list[dict], recurring: list[dict], planned: list[dict], trackers: list[dict],
                  transactions: list[dict], rates: dict, start: date, end: date, scenario: str = "base") -> tuple[list[Flow], dict]:
    """Every expected movement between start (exclusive) and end (inclusive) on liquid accounts."""
    acc = {a["id"]: a for a in accounts}
    liquid = {a["id"] for a in accounts if a.get("liquid") and not a.get("archived")}
    flows: list[Flow] = []

    def ccy(aid):
        return acc[aid]["currency"] if aid in acc else None

    def add(d, aid, amount, **kw):
        if aid in liquid and amount:
            flows.append(Flow(date=d, ccy=ccy(aid), amount=round(amount, 2), account=acc[aid]["name"], **kw))

    def transfer(d, frm, to, amount, to_amount, **kw):
        out_ccy, in_ccy = ccy(frm), ccy(to)
        if to_amount is None and out_ccy and in_ccy:
            to_amount = convert(amount, out_ccy, in_ccy, rates)
        add(d, frm, -amount, **kw)
        add(d, to, to_amount or 0, **kw)

    # repeating entries
    salary_shifted = set()
    for r in recurring:
        if not r.get("active"):
            continue
        r_end = date.fromisoformat(r["end_date"]) if r.get("end_date") else None
        dates = [d for d in ledger.occurrences(date.fromisoformat(r["start_date"]), r["frequency"], end, r_end) if d > start]
        is_salary = r["kind"] == "income" and "salary" in (r.get("category") or "").lower()
        if scenario == "salary_late" and is_salary and dates and r["id"] not in salary_shifted:
            salary_shifted.add(r["id"])
            dates[0] = add_months(dates[0], 1)
            dates = [d for d in dates if d <= end]
        label = r.get("note") or r.get("category") or r["kind"].title()
        why = f"repeats {r['frequency']}"
        for d in dates:
            if r["kind"] == "transfer":
                transfer(d, r["account_id"], r.get("to_account_id"), r["amount"], r.get("to_amount"), label=label,
                         confidence="known", source="repeating", why=why, category="Transfer")
            else:
                add(d, r["account_id"], r["amount"] if r["kind"] == "income" else -r["amount"], label=label,
                    confidence="known", source="repeating", why=why, category=r.get("category") or "")

    # planned items
    for p in planned:
        if p.get("done"):
            continue
        d = date.fromisoformat(p["date"])
        overdue = d <= start
        if overdue:
            d = start + timedelta(days=1)
        if d > end:
            continue
        conf = p.get("confidence") or "planned"
        if scenario == "no_estimated" and conf == "estimated" and p["kind"] == "income":
            continue
        label = p.get("note") or p.get("category") or p["kind"].title()
        why = "planned item" + (" (date passed — still not done)" if overdue else "")
        if p["kind"] == "transfer":
            transfer(d, p["account_id"], p.get("to_account_id"), p["amount"], p.get("to_amount"), label=label,
                     confidence=conf, source="planned", why=why, category="Transfer", planned_id=p["id"])
        else:
            add(d, p["account_id"], p["amount"] if p["kind"] == "income" else -p["amount"], label=label,
                confidence=conf, source="planned", why=why, category=p.get("category") or "", planned_id=p["id"])

    # staged purchases
    for t in trackers:
        if t.get("_error") or not t.get("currency"):
            continue
        s = summarize(t)
        rate = float(t.get("tax_rate_on_payments") or 0)
        tds = float(t.get("tds_rate") or 0)
        proj = {p["label"].replace(" (estimate)", ""): p for p in s["projection"]}
        first = True
        for st in s["stages"]:
            if st.get("paid"):
                continue
            due, amt = _parse_due(st.get("due")), st.get("amount")
            known = bool(due and amt)
            if not due:
                pr = proj.get(st.get("name", "Stage"))
                due = date.fromisoformat(pr["date"]) if pr else None
            if not due:
                continue
            if scenario == "stage_early" and first:
                due = add_months(due, -1)
            first = False
            if due <= start:
                due = start + timedelta(days=1)
            if due > end:
                continue
            base_amt = float(amt) if amt else s["next_stage"] / (1 + rate)
            total = base_amt * (1 + rate)
            flows.append(Flow(date=due, ccy=t["currency"], amount=-round(total, 2), account=t.get("pay_from") or t.get("name"),
                              label=f"{t.get('name', 'Purchase')}: {st.get('name', 'next stage')}",
                              confidence="known" if known else "estimated", source="tracker",
                              why=("due date and amount from the demand letter" if known else "estimated from the remaining price and possession date"),
                              category="Property payment",
                              tax_note=(f"includes {rate:.0%} tax on {base_amt:,.0f}" if rate else ""),
                              tds=round(base_amt * tds, 2) if tds else 0.0))

    # learned: typical other spending (not from repeating entries) per currency
    learned = {}
    by_month = defaultdict(lambda: defaultdict(float))
    first_full = add_months(start.replace(day=1), -6, 1)
    for tx in transactions:
        if tx["kind"] != "expense" or tx.get("recurring_id") or tx["account_id"] not in liquid:
            continue
        d = date.fromisoformat(tx["date"])
        if first_full <= d < start.replace(day=1):
            by_month[ccy(tx["account_id"])][month_key(d)] += tx["amount"]
    for c, months in by_month.items():
        vals = [months.get(month_key(add_months(first_full, i, 1)), 0.0) for i in range(6)]
        active = [v for v in vals if v > 0]
        if len(active) >= 2:
            learned[c] = round(statistics.median(vals), 2)
    if learned:
        d = start.replace(day=1)
        while d <= end:
            mid = d.replace(day=min(15, calendar.monthrange(d.year, d.month)[1]))
            if mid > start:
                for c, v in learned.items():
                    if v > 0:
                        flows.append(Flow(date=mid, ccy=c, amount=-v, account="", label="Other spending (typical month)",
                                          confidence="learned", source="learned", why="median of the last 6 months, excluding repeating entries",
                                          category="Other spending"))
            d = add_months(d, 1, 1)
    flows.sort(key=lambda f: (f["date"], f["amount"] < 0, f["label"]))
    return flows, learned


def simulate(start_bal: dict, flows: list[Flow], months: list[str]) -> dict:
    """Walk the flows in date order. Per currency and month: start, in, out, end and the lowest point."""
    ccys = sorted(set(start_bal) | {f["ccy"] for f in flows})
    bal = {c: float(start_bal.get(c, 0.0)) for c in ccys}
    series = {c: {m: {"month": m, "start": None, "in": 0.0, "out": 0.0, "end": None, "low": None} for m in months} for c in ccys}
    by_m = defaultdict(list)
    for f in flows:
        by_m[month_key(f["date"])].append(f)
    for m in months:
        for c in ccys:
            s = series[c][m]
            s["start"] = s["low"] = round(bal[c], 2)
        for f in by_m.get(m, []):
            c = f["ccy"]
            bal[c] += f["amount"]
            s = series[c][m]
            if f["amount"] >= 0:
                s["in"] += f["amount"]
            else:
                s["out"] -= f["amount"]
            s["low"] = min(s["low"], round(bal[c], 2))
        for c in ccys:
            s = series[c][m]
            s["end"] = round(bal[c], 2)
            s["in"], s["out"] = round(s["in"], 2), round(s["out"], 2)
    return {c: [series[c][m] for m in months] for c in ccys}


def default_floor(ccy: str, flows: list[Flow], months: int) -> float:
    """One month of this currency's typical outgoings (excluding big one-offs), rounded."""
    outs = [-f["amount"] for f in flows if f["ccy"] == ccy and f["amount"] < 0 and f["source"] in ("repeating", "learned") and f.get("category") != "Transfer"]
    return _nice_up(sum(outs) / max(months, 1)) if outs else 0.0


def forecast(accounts_with_balance: list[dict], recurring: list[dict], planned: list[dict], trackers: list[dict],
             transactions: list[dict], rates: dict, base: str, floors: dict | None = None, months: int = 12,
             today: date | None = None, scenario: str = "base") -> dict:
    today = today or date.today()
    scenario = scenario if scenario in SCENARIOS else "base"
    if scenario == "fx_weak":
        rates = {k: (v * 0.93 if isinstance(v, (int, float)) and k != base else v) for k, v in rates.items()}
    end_month = add_months(today.replace(day=1), months - 1, 1)
    end = end_month.replace(day=calendar.monthrange(end_month.year, end_month.month)[1])
    month_list = [month_key(add_months(today.replace(day=1), i, 1)) for i in range(months)]
    flows, learned = collect_flows(accounts_with_balance, recurring, planned, trackers, transactions, rates, today, end, scenario)
    start_bal = defaultdict(float)
    for a in accounts_with_balance:
        if a.get("liquid") and not a.get("archived"):
            start_bal[a["currency"]] += a["balance"]
    for f in flows:
        start_bal.setdefault(f["ccy"], 0.0)
    floors = dict(floors or {})
    floor_source = {}
    for c in start_bal:
        if floors.get(c) is None:
            floors[c] = default_floor(c, flows, months)
            floor_source[c] = "default: about one month of this currency's usual outgoings"
        else:
            floors[c] = float(floors[c])
            floor_source[c] = "your setting"

    def conv(v, frm, to):
        try:
            return convert(v, frm, to, rates)
        except ValueError:
            return None

    plan, unfunded = [], []
    work = list(flows)
    for _ in range(8):
        sim = simulate(start_bal, work, month_list)
        hit = None
        for i, m in enumerate(month_list):
            for c in sorted(sim):
                if sim[c][i]["low"] < floors[c] - 0.5 and not any(u["ccy"] == c and u["month"] == m for u in unfunded):
                    hit = (i, m, c)
                    break
            if hit:
                break
        if not hit:
            break
        i, m, c = hit
        need = floors[c] - sim[c][i]["low"]
        y, mo = int(m[:4]), int(m[5:])
        tdate = add_months(date(y, mo, 15), -1)
        if tdate <= today + timedelta(days=3):
            tdate = today + timedelta(days=3)
        month_items = sorted([f for f in work if f["ccy"] == c and month_key(f["date"]) == m and f["amount"] < 0], key=lambda f: f["amount"])[:2]
        best = None
        for d_c in sim:
            if d_c == c:
                continue
            j0 = month_list.index(month_key(tdate)) if month_key(tdate) in month_list else 0
            room = min(s["low"] for s in sim[d_c][j0:]) - floors[d_c]
            room_base = conv(room, d_c, base)
            if room_base is not None and room > 0 and (best is None or room_base > best[1]):
                best = (d_c, room_base, room)
        step = {"month": m, "ccy": c, "low_before": round(sim[c][i]["low"], 2), "floor": floors[c], "need": round(need, 2),
                "because": [{"label": f["label"], "amount": -f["amount"], "date": f["date"].isoformat(), "confidence": f["confidence"],
                             "tds": f.get("tds", 0), "tax_note": f.get("tax_note", "")} for f in month_items]}
        if not best:
            step["unfunded"] = True
            unfunded.append(step)
            continue
        d_c, _, room = best
        recv = _nice_up(need)
        send = conv(recv, c, d_c) * 1.01
        send = _nice_up(send)
        if send > room:
            send = math.floor(room)
            recv = conv(send / 1.01, d_c, c)
            step["partial"] = True
        step.update(from_ccy=d_c, send=round(send, 2), receive=round(recv, 2), date=tdate.isoformat(),
                    rate_note=f"at today's rate plus 1% for fees and rate moves")
        plan.append(step)
        work.append(Flow(date=tdate, ccy=d_c, amount=-send, account="", label=f"Planned transfer to {c}", confidence="plan",
                         source="plan", why="funding plan", category="Transfer"))
        work.append(Flow(date=tdate, ccy=c, amount=recv, account="", label=f"Transfer from {d_c}", confidence="plan",
                         source="plan", why="funding plan", category="Transfer"))
        work.sort(key=lambda f: (f["date"], f["amount"] < 0, f["label"]))
        if step.get("partial"):
            unfunded.append({**step, "unfunded": True})

    sim = simulate(start_bal, work, month_list)
    base_sim = simulate(start_bal, flows, month_list)
    lowest = {}
    for c, rows in sim.items():
        r = min(rows, key=lambda s: s["low"])
        lowest[c] = {"month": r["month"], "low": r["low"], "below_floor": r["low"] < floors[c] - 0.5,
                     "without_plan": min(s["low"] for s in base_sim[c])}
    watch = [{"ccy": c, **v} for c, v in lowest.items() if v["below_floor"]]
    options = _options(watch, work, accounts_with_balance, start_bal, month_list, floors) if watch else []

    horizon = today + timedelta(days=90)
    in90 = out90 = 0.0
    for f in flows:
        if f["date"] <= horizon and f.get("category") != "Transfer":
            v = conv(f["amount"], f["ccy"], base)
            if v is None:
                continue
            if v >= 0:
                in90 += v
            else:
                out90 -= v
    return {"today": today.isoformat(), "base": base, "months": month_list, "scenario": scenario, "scenarios": SCENARIOS,
            "start": {c: round(v, 2) for c, v in start_bal.items()}, "floors": floors, "floor_source": floor_source,
            "series": sim, "series_without_plan": base_sim, "lowest": lowest, "plan": plan, "unfunded": unfunded,
            "watch": watch, "options": options, "learned": learned,
            "next90": {"in": round(in90, 2), "out": round(out90, 2), "net": round(in90 - out90, 2)},
            "items": [_public(f) for f in work], "sources": sources(flows, months)}


def _public(f: Flow) -> dict:
    return {**{k: v for k, v in f.items() if k != "date"}, "date": f["date"].isoformat()}


def _options(watch, work, accounts, start_bal, month_list, floors) -> list[dict]:
    """Ways out when a currency still dips below its floor: shift a flexible payment or pause a savings transfer."""
    out = []
    for w in watch:
        c, m = w["ccy"], w["month"]
        cands = [f for f in work if f["ccy"] == c and month_key(f["date"]) == m and f["amount"] < 0
                 and f["confidence"] in ("planned", "estimated", "plan")]
        for f in sorted(cands, key=lambda f: f["amount"])[:2]:
            moved = [g for g in work if g is not f] + [Flow({**f, "date": add_months(f["date"], 1)})]
            moved.sort(key=lambda g: (g["date"], g["amount"] < 0, g["label"]))
            low = min(s["low"] for s in simulate(start_bal, moved, month_list)[c])
            out.append({"ccy": c, "text": f"Move “{f['label']}” one month later", "detail": f"{f['date']:%d %b} → next month",
                        "low_after": round(low, 2), "fixes": low >= floors[c] - 0.5})
        saving = [f for f in work if f["ccy"] == c and f["source"] == "repeating" and f.get("category") == "Transfer" and f["amount"] < 0]
        if saving:
            f = max(saving, key=lambda f: -f["amount"])
            idx = month_list.index(m)
            months_before = month_list[max(0, idx - 1): idx + 1]
            paused = [g for g in work if not (g["label"] == f["label"] and g["ccy"] == c and g["amount"] < 0 and month_key(g["date"]) in months_before)]
            low = min(s["low"] for s in simulate(start_bal, paused, month_list)[c])
            out.append({"ccy": c, "text": f"Pause “{f['label']}” for {len(months_before)} month(s)", "detail": f"{-f['amount']:,.0f} {c} each time",
                        "low_after": round(low, 2), "fixes": low >= floors[c] - 0.5})
    return out


def sources(flows: list[Flow], months: int) -> list[dict]:
    """One row per distinct line (label + currency): total over the horizon, monthly equivalent, confidence, why."""
    agg = {}
    for f in flows:
        k = (f["label"], f["ccy"], f["confidence"])
        a = agg.setdefault(k, {"label": f["label"], "ccy": f["ccy"], "confidence": f["confidence"], "why": f["why"],
                               "total": 0.0, "count": 0, "first": f["date"].isoformat(), "category": f.get("category", "")})
        a["total"] += f["amount"]
        a["count"] += 1
    rows = []
    for a in agg.values():
        a["total"] = round(a["total"], 2)
        if abs(a["total"]) < 0.5:          # transfers between two accounts in the same currency cancel out
            continue
        a["monthly"] = round(a["total"] / months, 2) if a["count"] > 1 else None
        rows.append(a)
    rows.sort(key=lambda a: (CONF_ORDER.index(a["confidence"]) if a["confidence"] in CONF_ORDER else 9, a["total"]))
    return rows
