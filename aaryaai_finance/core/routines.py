"""Routines: small scheduled checks that run on their own while the app is open. None of them needs AI.

- They only *read* your data and write two things: a run summary, and proposals.
- A proposal changes nothing until you approve it on the Routines screen (or Home).
- If an AI provider is connected and "AI summary" is on, the monthly review adds a short plain-English
  summary written by it; the numbers always come from the app.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta

from . import ledger

ROUTINES = [
    {"id": "forecast_refresh", "label": "Forecast refresh", "every": "daily",
     "about": "Rebuilds the 12-month cash forecast and turns the funding plan into transfer proposals."},
    {"id": "deadline_sweep", "label": "Deadline sweep", "every": "weekly",
     "about": "Looks 30 days ahead for deadlines and proposes reminders for tax opportunities with a date."},
    {"id": "monthly_review", "label": "Monthly review", "every": "monthly",
     "about": "Last month's income, spending and savings rate; proposes goal changes that fit your surplus."},
    {"id": "tax_prep", "label": "Tax-year prep", "every": "monthly",
     "about": "Checks which documents for last year's return are still missing (from February for calendar years, from May for India)."},
    {"id": "exchange_rates", "label": "Exchange rates", "every": "daily",
     "about": "Refreshes European Central Bank rates. Skipped when you use manual rates."},
]
BY_ID = {r["id"]: r for r in ROUTINES}
_lock = threading.Lock()


def enabled(ctx, rid: str) -> bool:
    return ctx.db.settings().get(f"routine:{rid}", "1") != "0"


def last_run(ctx, rid: str) -> dict | None:
    runs = [r for r in ctx.db.list("routine_runs", "ran DESC") if r["routine"] == rid]
    return runs[0] if runs else None


def is_due(every: str, last: datetime | None, now: datetime) -> bool:
    if last is None:
        return True
    if every == "daily":
        return last.date() < now.date()
    if every == "weekly":
        return now - last >= timedelta(days=7)
    if every == "monthly":
        return (last.year, last.month) < (now.year, now.month)
    return False


def status(ctx) -> list[dict]:
    now = datetime.now()
    out = []
    for r in ROUTINES:
        lr = last_run(ctx, r["id"])
        last = datetime.fromisoformat(lr["ran"]) if lr else None
        summ = lr.get("summary") if lr else None
        if isinstance(summ, str):
            try:
                summ = json.loads(summ)
            except ValueError:
                summ = {"text": summ}
        out.append({**r, "enabled": enabled(ctx, r["id"]), "last_run": lr["ran"] if lr else None, "last_status": lr["status"] if lr else None,
                    "summary": summ, "due": is_due(r["every"], last, now)})
    return out


def run(ctx, rid: str, actor: str = "Routine") -> dict:
    fn = RUNNERS[rid]
    with _lock:
        try:
            summary = fn(ctx)
            st = "ok"
        except Exception as e:  # noqa: BLE001 — a failing routine is reported, never crashes the app
            summary, st = {"text": f"Didn't finish: {type(e).__name__}: {e}"}, "error"
        ctx.db.upsert("routine_runs", {"routine": rid, "ran": datetime.now().isoformat(timespec="seconds"), "status": st,
                                       "summary": json.dumps(summary, ensure_ascii=False, default=str)})
        ctx.audit(actor, f"Ran {BY_ID[rid]['label']}", summary.get("text", "") if isinstance(summary, dict) else "")
    return {"routine": rid, "status": st, "summary": summary}


def run_due(ctx) -> list[dict]:
    done = []
    for r in status(ctx):
        if r["enabled"] and r["due"]:
            done.append(run(ctx, r["id"]))
    return done


# ---------------------------------------------------------------- the routines
def _pick_account(accounts, ccy):
    c = [a for a in accounts if a["currency"] == ccy and a.get("liquid") and not a.get("archived")]
    return max(c, key=lambda a: a["balance"]) if c else None


def forecast_refresh(ctx) -> dict:
    f = ctx.forecast()
    accounts = ctx.accounts_with_balance()
    keys = set()
    for s in f["plan"]:
        key = f"transfer:{s['from_ccy']}:{s['ccy']}:{s['month']}"
        keys.add(key)
        frm, to = _pick_account(accounts, s["from_ccy"]), _pick_account(accounts, s["ccy"])
        because = "; ".join(f"{b['label']} {b['amount']:,.0f} {s['ccy']}" for b in s["because"])
        action = {"type": "add_planned", "row": {"date": s["date"], "kind": "transfer", "account_id": frm["id"], "to_account_id": to["id"],
                                                  "amount": s["send"], "to_amount": s["receive"], "category": "Transfer", "confidence": "planned",
                                                  "note": f"Funding plan for {s['month']}"}} if (frm and to) else {"type": "note"}
        ctx.propose(key, "Forecast refresh", f"Schedule a transfer of {s['send']:,.0f} {s['from_ccy']} → {s['ccy']} around {s['date']}",
                    f"Without it, {s['ccy']} would drop to {s['low_before']:,.0f} in {s['month']} (floor {s['floor']:,.0f}). Because of: {because}.",
                    f"keeps {s['ccy']} above its floor", action)
    for p in ctx.db.list("proposals"):
        if p["status"] == "pending" and p["key"].startswith("transfer:") and p["key"] not in keys:
            ctx.db.upsert("proposals", {"id": p["id"], "status": "skipped", "decided": datetime.now().isoformat(timespec="seconds")})
    lows = ", ".join(f"{c} lowest {v['low']:,.0f} in {v['month']}" for c, v in f["lowest"].items())
    return {"text": f"12 months ahead: {lows}. {len(f['plan'])} transfer(s) in the funding plan"
                    + (f"; {len(f['watch'])} currency still dips below its floor." if f["watch"] else "."),
            "plan": len(f["plan"]), "watch": len(f["watch"])}


def deadline_sweep(ctx) -> dict:
    today = date.today()
    soon = [d for d in ctx.calendar() if d["status"] == "open" and d["due"] and d["due"] != "ongoing"
            and today.isoformat() <= d["due"] <= (today + timedelta(days=30)).isoformat()]
    added = 0
    for c in ctx.opportunities()["cards"]:
        if c["deadline"] and c["deadline"] <= (today + timedelta(days=60)).isoformat() and c["effect_base"] > 0:
            key = f"opp:{c['rule']}:{c['deadline']}"
            if ctx.propose(key, "Deadline sweep", f"Add a reminder: {c['title']}", c["why"], c["effect"],
                           {"type": "add_deadline", "row": {"due": c["deadline"], "country": c["country"], "title": c["title"],
                                                            "detail": c["why"][:400], "key": key}}):
                added += 1
    return {"text": f"{len(soon)} deadline(s) in the next 30 days" + (f"; {added} opportunity reminder(s) proposed." if added else "."),
            "due_soon": [{"due": d["due"], "title": d["title"]} for d in soon[:6]]}


def monthly_review(ctx) -> dict:
    today = date.today()
    last = today.replace(day=1) - timedelta(days=1)
    s = ledger.summary(ctx.db, "month", last, ctx.base, ctx.rates)
    prev = ledger.monthly_actuals_period(ctx.db, ctx.base, ctx.rates, (last.replace(day=1) - timedelta(days=90)).replace(day=1), last.replace(day=1) - timedelta(days=1))
    rate = (s["income"] - s["expense"]) / s["income"] if s["income"] else None
    changes = []
    for cat, v in s["by_category"].items():
        before = (prev["by_category"].get(cat) or 0) / 3
        if before > 50 and v > before * 1.1:
            changes.append({"category": cat, "now": v, "before": round(before, 2), "change": round(v / before - 1, 3)})
    changes.sort(key=lambda c: -(c["now"] - c["before"]))
    g = ctx.goal_odds(whatif=False)
    room = g["unallocated"]
    proposed = 0
    for goal in g["goals"]:
        need = goal.get("monthly_for_85")
        if goal["probability"] < 0.7 and need and need > (goal["monthly"] or 0):
            extra = need - (goal["monthly"] or 0)
            try:
                extra_base = ctx.conv(extra, goal["currency"])
            except ValueError:
                continue
            if extra_base <= max(room, 0):
                room -= extra_base
                if ctx.propose(f"goal:{goal['id']}:{today:%Y-%m}", "Monthly review",
                               f"Raise “{goal['name']}” to {need:,.0f} {goal['currency']} a month",
                               f"Now {goal['probability']:.0%} likely at {goal['monthly']:,.0f}. At {need:,.0f} it is about {goal['odds_at_85']:.0%}. "
                               f"Fits in this month's unallocated surplus.", f"{goal['probability']:.0%} → {goal['odds_at_85']:.0%}",
                               {"type": "set_goal_monthly", "goal_id": goal["id"], "monthly": need}):
                    proposed += 1
    text = (f"{last:%B %Y}: in {s['income']:,.0f}, out {s['expense']:,.0f} {ctx.base}"
            + (f", saved {rate:.0%}" if rate is not None else "") + "."
            + (f" Biggest rise: {changes[0]['category']} +{changes[0]['change']:.0%}." if changes else "")
            + (f" {proposed} goal change(s) proposed." if proposed else ""))
    out = {"text": text, "month": f"{last:%Y-%m}", "income": s["income"], "expense": s["expense"], "savings_rate": rate,
           "changes": changes[:3], "proposed": proposed}
    ai_on = ctx.db.settings().get("routines:ai_summary", "1") != "0"
    if ai_on:
        try:
            from ..ai.providers import make_provider
            prov = make_provider(ctx.settings.config["ai"], ctx.settings.secret)
            if prov:
                prompt = ("Write 2-3 plain sentences summarising this month for the person, then one sentence on the single most useful "
                          "thing to act on. Use only these numbers, don't invent any:\n" + json.dumps(out, default=str))
                out["ai_summary"] = prov.complete(prompt)[:900]
                out["ai_provider"] = ctx.settings.config["ai"].get("provider")
        except Exception as e:  # noqa: BLE001
            out["ai_error"] = type(e).__name__
    return out


def tax_prep(ctx) -> dict:
    today = date.today()
    lines = []
    for code, p in ctx.packs.items():
        ws_def = p.get("tax_workspace")
        if not ws_def:
            continue
        start_month = 5 if ws_def.get("year") == "india_fy" else 2
        if today.month < start_month and ws_def.get("year") != "india_fy":
            continue
        try:
            ws = ctx.tax_workspace(code)
        except ValueError:
            continue
        missing = [d["label"] for d in ws["documents"] if d["status"] == "missing"]
        answered = sum(1 for q in ws["questions"] if q["answered"])
        lines.append(f"{ws['title']}: {answered}/{len(ws['questions'])} answered" + (f", missing {', '.join(missing)}" if missing else ", all documents found"))
    return {"text": "; ".join(lines) or "Nothing to prepare yet."}


def exchange_rates(ctx) -> dict:
    return {"text": ctx.refresh_fx()}


RUNNERS = {"forecast_refresh": forecast_refresh, "deadline_sweep": deadline_sweep, "monthly_review": monthly_review,
           "tax_prep": tax_prep, "exchange_rates": exchange_rates}


def start_background(get_ctx, every_seconds: int = 900) -> threading.Thread:
    """Run due routines shortly after start-up and then every 15 minutes while the app is open."""
    def loop():
        time.sleep(20)
        while True:
            try:
                c = get_ctx()
                if c.settings.is_configured:
                    run_due(c)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(every_seconds)
    t = threading.Thread(target=loop, name="aaryaai-routines", daemon=True)
    t.start()
    return t
