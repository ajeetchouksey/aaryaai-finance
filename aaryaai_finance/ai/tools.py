"""Read tools shared by the in-app assistant and the MCP server: one list, so both see the same numbers.

Each tool reads the app's own data or runs the same calculators the screens use. None of them changes anything:
the tools that suggest a change live with each surface (assistant.py, mcp_server.py) and only create proposals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from ..core import ledger, planning, trading


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    run: Callable[..., Any]                 # run(ctx, **arguments)
    label: str                              # shown under the chat reply, e.g. "Checked your deadlines"
    mcp_name: str = ""                      # the name MCP clients already know, when it differs
    surfaces: tuple = ("chat", "mcp")


def _obj(props: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": props or {}} | ({"required": required} if required else {})


def _forecast(ctx, scenario: str = "base"):
    f = ctx.forecast(scenario or "base")
    return {k: f[k] for k in ("today", "base", "scenario", "months", "floors", "lowest", "plan", "watch", "options", "next90")} | {
        "month_end": {c: [{"month": r["month"], "end": r["end"], "low": r["low"]} for r in rows] for c, rows in f["series"].items()}}


def _deadlines(ctx, include_done: bool = False, days: int | None = None):
    until = (date.today() + timedelta(days=int(days))).isoformat() if days else None
    items = [d for d in ctx.calendar() if (include_done or d["status"] != "done") and (not until or (d.get("due") and d["due"] <= until))]
    return {"today": date.today().isoformat(), "items": items}


def _diversification(ctx):
    d = ctx.diversify()
    return {k: d[k] for k in ("base", "total", "classes", "countries", "currencies", "sectors", "companies", "flags", "checks", "targets", "options")}


def _tax_status(ctx, country: str, year: int | None = None):
    ws = ctx.tax_workspace(str(country).upper(), year)
    return {k: ws[k] for k in ("title", "year_label", "steps", "documents", "questions", "derived", "checks", "sheet", "estimate")}


def _calculators(ctx):
    return [{"pack": c, "calculator": k["id"], "title": k.get("title"), "inputs": k.get("inputs", [])}
            for c, p in ctx.packs.items() for k in p.get("calculators", [])]


def _plan_goal(ctx, name, target_today, target_date, currency=None, saved=0, monthly=0, annual_return=0.05, inflation=0.02):
    r = planning.plan_goal(name, float(target_today), date.fromisoformat(target_date), float(saved), float(monthly),
                           float(annual_return), float(inflation), currency or ctx.base)
    r.pop("path", None)
    return r


def _proposals(ctx, status: str = "pending", limit: int = 20):
    keep = ("id", "created", "source", "title", "detail", "status", "decided")
    rows = [p for p in ctx.db.list("proposals", "created DESC") if status == "all" or p["status"] == status]
    return {"count": len(rows), "items": [{k: p[k] for k in keep} for p in rows[:max(1, min(int(limit), 100))]],
            "note": "Only the user can approve or skip these, in the app (Routines → Proposals)."}


def _money_summary(ctx, period: str = "month", date_in: str | None = None, currency: str | None = None):
    if period not in ("week", "month", "year"):
        raise ValueError("period must be week, month or year")
    ledger.materialize_recurring(ctx.db)
    s = ledger.summary(ctx.db, period, date.fromisoformat(date_in) if date_in else date.today(), (currency or ctx.base).upper(), ctx.rates)
    out = {k: s[k] for k in ("period", "start", "end", "display", "income", "expense", "net", "by_category", "by_currency", "trend")}
    out["count"] = len(s["transactions"])
    if period == "month" and not date_in:
        b = ledger.budget_status(ctx.db, ctx.base, ctx.rates)
        out["budget"] = {k: b[k] for k in ("month", "budget_total", "spent_total", "unbudgeted")} | {
            "lines": [{k: r[k] for k in ("category", "budget", "spent", "left", "status")} for r in b["rows"]]}
    return out


def _documents(ctx, query: str = "", category: str = "", year: int | None = None, limit: int = 25):
    words = str(query).lower().split()
    out = []
    for r in ctx.document_library():
        hay = " ".join(str(r.get(k) or "") for k in ("path", "category", "doc_type")).lower()
        if words and not all(w in hay for w in words):
            continue
        if category and str(r.get("category") or "").lower() != category.lower():
            continue
        if year and str(year) not in (r["path"] + " " + str(r.get("doc_date") or "")):
            continue
        out.append({k: r.get(k) for k in ("path", "name", "folder", "category", "doc_type", "doc_date", "modified", "logged")})
    n = max(1, min(int(limit), 100))
    return {"count": len(out), "items": out[:n], "note": "Names and folders only; the app never sends a document's contents here."}


def _backtest(ctx, ticker, strategy="sma_cross", years=10):
    p = trading.synthetic_prices(int(years)) if ticker.upper() == "DEMO" else trading.fetch_prices(ticker, f"{date.today().year - int(years)}-01-01")
    r = trading.backtest(p, strategy)
    r.pop("series", None)
    return r


TOOLS: list[Tool] = [
    Tool("get_financial_snapshot", "Current position: net worth (base currency), accounts with balances, other assets/debts, holdings, goals, "
         "this month's income/spending, trackers (e.g. property purchases), exchange rates.",
         _obj(), lambda ctx: ctx.snapshot(), "Looked at your finances", mcp_name="get_snapshot"),
    Tool("money_summary", "Income, spending and spending by category for a week, month or year (default: this month), with the 6 periods before it. "
         "This month also shows the budget lines against what was spent. Amounts in the base currency unless currency is given.",
         _obj({"period": {"type": "string", "enum": ["week", "month", "year"]}, "date": {"type": "string", "description": "any day in the period, YYYY-MM-DD"},
               "currency": {"type": "string"}}),
         lambda ctx, date=None, **a: _money_summary(ctx, date_in=date, **a), "Checked your spending"),
    Tool("cash_forecast", "12-month cash forecast per currency: month-end balances, lowest points against the user's minimum balances, and the funding "
         "plan (transfers between currencies).",
         _obj({"scenario": {"type": "string", "enum": ["base", "salary_late", "stage_early", "no_estimated", "fx_weak"]}}), _forecast, "Checked the cash forecast"),
    Tool("list_deadlines", "Tax and compliance deadlines from country packs, user rules and the user's own items. Open ones only unless include_done; "
         "days limits them to the next N days.",
         _obj({"include_done": {"type": "boolean"}, "days": {"type": "integer"}}), _deadlines, "Checked your deadlines"),
    Tool("goal_odds", "Each goal's probability of success from 2,000 simulated markets, the saving per month for 85%, the monthly surplus split "
         "and what-if scenarios.", _obj(), lambda ctx: ctx.goal_odds(), "Checked your goal odds"),
    Tool("diversification", "Holdings looked through to asset class, country, currency, sector and companies (inside index funds too); concentration "
         "flags against the user's rules; target mix and tax-cheapest rebalancing.", _obj(), _diversification, "Checked your diversification"),
    Tool("opportunities", "Tax-aware opportunities from the country packs: allowances, holding periods, deadlines. Facts, not buy/sell advice.",
         _obj(), lambda ctx: ctx.opportunities(), "Looked for tax opportunities"),
    Tool("tax_status", "Tax-year workspace for a country (DE, IN…): documents found/missing, answers, estimate, findings, filing-sheet lines.",
         _obj({"country": {"type": "string", "description": "2-letter code, e.g. DE or IN"}, "year": {"type": "integer"}}, ["country"]),
         _tax_status, "Opened your tax workspace"),
    Tool("list_calculators", "Calculators available from the user's country packs, with their input fields.", _obj(), _calculators, "Looked up calculators"),
    Tool("run_calculator", "Run a country-pack calculator (e.g. pack DE, calculator refund). Inputs by field id: call list_calculators first.",
         _obj({"pack": {"type": "string"}, "calculator": {"type": "string"}, "inputs": {"type": "object"}}, ["pack", "calculator", "inputs"]),
         lambda ctx, pack, calculator, inputs: ctx.run_calculator(pack, calculator, inputs), "Ran a calculator"),
    Tool("plan_goal", "What-if savings plan: required monthly saving and on-track verdict. Does not save.",
         _obj({"name": {"type": "string"}, "target_today": {"type": "number"}, "currency": {"type": "string"}, "target_date": {"type": "string"},
               "saved": {"type": "number"}, "monthly": {"type": "number"}, "annual_return": {"type": "number"}, "inflation": {"type": "number"}},
              ["name", "target_today", "target_date"]), _plan_goal, "Ran a savings plan"),
    Tool("list_proposals", "Suggested changes waiting for the user's approval (from routines, the assistant or MCP apps), newest first. "
         "status: pending (default), approved, skipped or all.",
         _obj({"status": {"type": "string", "enum": ["pending", "approved", "skipped", "all"]}, "limit": {"type": "integer"}}),
         _proposals, "Checked what waits for approval"),
    Tool("find_documents", "Find the user's saved documents (statements, payslips, tax papers, receipts) by words in the file name, folder, category "
         "or type, by category, or by year. Returns names and folders, not contents.",
         _obj({"query": {"type": "string"}, "category": {"type": "string"}, "year": {"type": "integer"}, "limit": {"type": "integer"}}),
         _documents, "Looked through your documents"),
    Tool("run_backtest", "Backtest a trading rule on past prices (paper only). ticker like VWCE.DE, ^NSEI or DEMO.",
         _obj({"ticker": {"type": "string"}, "strategy": {"type": "string", "enum": list(trading.STRATEGIES)}, "years": {"type": "integer"}}, ["ticker"]),
         _backtest, "Ran a backtest", surfaces=("chat",)),
]


def for_chat() -> list[dict]:
    return [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in TOOLS if "chat" in t.surfaces]


def for_mcp() -> list[dict]:
    return [{"name": t.mcp_name or t.name, "description": t.description, "inputSchema": t.schema} for t in TOOLS if "mcp" in t.surfaces]


def find(name: str, surface: str) -> Tool | None:
    for t in TOOLS:
        if surface in t.surfaces and name == ((t.mcp_name or t.name) if surface == "mcp" else t.name):
            return t
    return None
