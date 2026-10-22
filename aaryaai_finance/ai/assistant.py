"""The in-app assistant: a provider-agnostic tool loop over your local data.

Only what you type and what a tool returns is sent to the AI provider you chose.
Tools read the app's own database and run the same deterministic calculators the app uses.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Callable, Iterator

from ..core import ledger, planning, trading
from .providers import Final

BASE_SYSTEM = """You are the personal-finance companion inside aaryaai-finance, a local app.

How to answer:
- Plain English first, short sentences; define jargon the first time. Lead with the answer or action, then why.
- Ground answers in the user's data: call get_financial_snapshot / list_deadlines before answering about their situation,
  and use run_calculator / plan_goal for any tax or savings number. Never do tax arithmetic in your head.
- Use the user's currencies; say which currency each amount is in.
- If data is missing, say what's missing and where to add it in the app (tab + button).
- Tax: explain rules for the user's countries (below). Say what is certain vs an estimate. For filings, corrections or
  penalties, recommend confirming with a local tax adviser — once, briefly.
- Investing: explain risk honestly; never promise returns; don't recommend individual securities. You are not a licensed adviser.
- Only suggest changes (save_goal, add_account, add_transaction, update_deadline) when the user asks. These tools never save anything:
  each creates a proposal the user approves with a button under your reply. Say in one line what you proposed and that it waits for their approval.

Today is {today}.
About the user: {about}
Countries switched on: {countries}. Base currency: {base}.
{pack_notes}"""

TOOLS = [
    {"name": "get_financial_snapshot", "description": "Current position: net worth (base currency), accounts with balances, other assets/debts, holdings, goals, this month's income/spending, trackers (e.g. property purchases), exchange rates.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_deadlines", "description": "Tax & compliance deadlines from country packs, user rules and the user's own items.",
     "input_schema": {"type": "object", "properties": {"include_done": {"type": "boolean"}}}},
    {"name": "list_calculators", "description": "Calculators available from the user's country packs, with their input fields.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_calculator", "description": "Run a country-pack calculator (e.g. pack DE, calculator refund). Inputs by field id — call list_calculators first.",
     "input_schema": {"type": "object", "required": ["pack", "calculator", "inputs"], "properties": {
         "pack": {"type": "string"}, "calculator": {"type": "string"}, "inputs": {"type": "object"}}}},
    {"name": "plan_goal", "description": "What-if savings plan: required monthly saving and on-track verdict. Does not save.",
     "input_schema": {"type": "object", "required": ["name", "target_today", "target_date"], "properties": {
         "name": {"type": "string"}, "target_today": {"type": "number"}, "currency": {"type": "string"}, "target_date": {"type": "string"},
         "saved": {"type": "number"}, "monthly": {"type": "number"}, "annual_return": {"type": "number"}, "inflation": {"type": "number"}}}},
    {"name": "save_goal", "description": "Propose a new goal or a change to one (only when asked); the user approves it in the app. Pass id to update.",
     "input_schema": {"type": "object", "required": ["name", "target_today", "target_date"], "properties": {
         "id": {"type": "integer"}, "name": {"type": "string"}, "target_today": {"type": "number"}, "currency": {"type": "string"},
         "target_date": {"type": "string"}, "saved": {"type": "number"}, "monthly": {"type": "number"}, "annual_return": {"type": "number"},
         "inflation": {"type": "number"}, "priority": {"type": "integer"}, "note": {"type": "string"}}}},
    {"name": "add_transaction", "description": "Propose income, an expense or a transfer in one of the user's accounts (only when asked); the user approves it in the app. Amount in the account's currency; optional frequency makes it repeat.",
     "input_schema": {"type": "object", "required": ["kind", "account_id", "amount"], "properties": {
         "kind": {"type": "string", "enum": ["income", "expense", "transfer"]}, "account_id": {"type": "integer"}, "amount": {"type": "number"},
         "category": {"type": "string"}, "date": {"type": "string"}, "note": {"type": "string"}, "to_account_id": {"type": "integer"},
         "to_amount": {"type": "number"}, "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly", "quarterly", "yearly"]},
         "end_date": {"type": "string"}}}},
    {"name": "add_account", "description": "Propose a new bank/savings/loan account (only when asked); the user approves it in the app. Existing accounts can't be changed here.",
     "input_schema": {"type": "object", "required": ["name", "currency"], "properties": {
         "name": {"type": "string"}, "institution": {"type": "string"}, "country": {"type": "string"},
         "currency": {"type": "string"}, "type": {"type": "string"}, "opening_balance": {"type": "number"}, "opening_date": {"type": "string"},
         "liquid": {"type": "boolean"}}}},
    {"name": "update_deadline", "description": "Propose marking a deadline done or open (only when asked); the user approves it in the app. Use the key from list_deadlines.",
     "input_schema": {"type": "object", "required": ["key", "status"], "properties": {"key": {"type": "string"}, "status": {"type": "string", "enum": ["open", "done"]}}}},
    {"name": "cash_forecast", "description": "12-month cash forecast per currency with lowest points, the user's minimum balances and the funding plan (transfers between currencies). Scenarios: base, salary_late, stage_early, no_estimated, fx_weak.",
     "input_schema": {"type": "object", "properties": {"scenario": {"type": "string"}}}},
    {"name": "goal_odds", "description": "Probability of reaching each goal (2,000 simulated markets), saving needed for 85%, monthly surplus split and what-if scenarios.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "diversification", "description": "Holdings looked through to asset class, country, currency, sector and companies; concentration flags vs the user's rules; target mix and tax-cheapest rebalancing.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "opportunities", "description": "Tax-aware opportunities from the country packs (allowances, holding periods, deadlines).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "tax_status", "description": "Tax-year workspace for a country (DE, IN…): documents found/missing, answers, estimate, findings, filing-sheet lines.",
     "input_schema": {"type": "object", "required": ["country"], "properties": {"country": {"type": "string"}, "year": {"type": "integer"}}}},
    {"name": "run_backtest", "description": "Backtest a trading rule on past prices (paper only). ticker like VWCE.DE, ^NSEI or DEMO.",
     "input_schema": {"type": "object", "required": ["ticker"], "properties": {"ticker": {"type": "string"}, "strategy": {"type": "string", "enum": list(trading.STRATEGIES)}, "years": {"type": "integer"}}}},
]

LABELS = {"get_financial_snapshot": "Looked at your finances", "list_deadlines": "Checked your deadlines", "list_calculators": "Looked up calculators",
          "run_calculator": "Ran a calculator", "plan_goal": "Ran a savings plan", "save_goal": "Proposed a goal", "add_transaction": "Proposed an entry",
          "add_account": "Proposed an account", "update_deadline": "Proposed a deadline change", "run_backtest": "Ran a backtest", "web_search": "Searched the web",
          "cash_forecast": "Checked the cash forecast", "goal_odds": "Checked your goal odds", "diversification": "Checked your diversification",
          "opportunities": "Looked for tax opportunities", "tax_status": "Opened your tax workspace"}


def system_prompt(ctx) -> str:
    cfg = ctx.settings.config
    notes = "\n".join(f"{p.get('flag', '')} {p.get('name')}: {p.get('ai_notes', '').strip()}" for p in ctx.packs.values() if p.get("ai_notes"))
    about = (cfg["profile"].get("name") or "the user") + (". " + cfg["profile"]["about"] if cfg["profile"].get("about") else "")
    return BASE_SYSTEM.format(today=date.today().strftime("%A %d %B %Y"), about=about,
                              countries=", ".join(f"{p.get('name')} ({c})" for c, p in ctx.packs.items()) or "none",
                              base=cfg["base_currency"], pack_notes=notes)


class Toolbox:
    def __init__(self, ctx):
        self.ctx = ctx

    def run(self, name: str, args: dict):
        fn = getattr(self, "t_" + name, None)
        if not fn:
            return {"error": f"unknown tool {name}"}
        try:
            return fn(**(args or {}))
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}"}

    def t_get_financial_snapshot(self):
        return self.ctx.snapshot()

    def t_cash_forecast(self, scenario: str = "base"):
        f = self.ctx.forecast(scenario)
        return {k: f[k] for k in ("today", "base", "scenario", "floors", "lowest", "plan", "watch", "options", "next90")} | {
            "month_end": {c: [{"month": r["month"], "end": r["end"], "low": r["low"]} for r in rows] for c, rows in f["series"].items()}}

    def t_goal_odds(self):
        return self.ctx.goal_odds()

    def t_diversification(self):
        d = self.ctx.diversify()
        return {k: d[k] for k in ("base", "total", "classes", "countries", "currencies", "sectors", "companies", "flags", "checks", "targets", "options")}

    def t_opportunities(self):
        return self.ctx.opportunities()

    def t_tax_status(self, country: str, year: int | None = None):
        ws = self.ctx.tax_workspace(country.upper(), year)
        return {k: ws[k] for k in ("title", "year_label", "steps", "documents", "questions", "derived", "checks", "sheet", "estimate")}

    def t_list_deadlines(self, include_done: bool = False):
        return {"today": date.today().isoformat(), "items": [d for d in self.ctx.calendar() if include_done or d["status"] != "done"]}

    def t_list_calculators(self):
        return [{"pack": c, "calculator": k["id"], "title": k.get("title"), "inputs": k.get("inputs", [])}
                for c, p in self.ctx.packs.items() for k in p.get("calculators", [])]

    def t_run_calculator(self, pack, calculator, inputs):
        return self.ctx.run_calculator(pack, calculator, inputs)

    def t_plan_goal(self, name, target_today, target_date, currency=None, saved=0, monthly=0, annual_return=0.05, inflation=0.02):
        r = planning.plan_goal(name, float(target_today), date.fromisoformat(target_date), float(saved), float(monthly),
                               float(annual_return), float(inflation), currency or self.ctx.base)
        r.pop("path", None)
        return r

    # ---------------- changes: the assistant only proposes them; the user approves each one
    def _propose(self, tool: str, title: str, detail: str, action: dict) -> dict:
        pid = self.ctx.propose(f"ai:{tool}:{uuid.uuid4().hex[:12]}", "AI assistant", title, detail, "suggested in chat", action)
        self.ctx.audit("AI assistant", f"Proposed: {title}", detail)
        return {"proposal_id": pid, "title": title,
                "status": "waiting for the user's approval: an Approve button appears under your reply (also on Routines). Nothing is saved until they approve."}

    def t_save_goal(self, **g):
        g = {k: v for k, v in g.items() if v is not None}
        old = None
        if g.get("id"):
            old = next((x for x in self.ctx.db.list("goals") if x["id"] == g["id"]), None)
            if not old:
                return {"error": f"no goal #{g['id']}; call get_financial_snapshot for ids"}
            g = {k: v for k, v in old.items() if k not in ("extra",)} | g
        g.setdefault("currency", self.ctx.base); g.setdefault("annual_return", 0.05); g.setdefault("inflation", 0.02)
        g.setdefault("saved", 0); g.setdefault("monthly", 0); g.setdefault("priority", 2)
        if float(g.get("target_today") or 0) <= 0:
            return {"error": "target_today must be more than zero"}
        date.fromisoformat(str(g["target_date"]))
        verb = "Update goal" if old else "New goal"
        title = f"{verb}: {g['name']}, {float(g['target_today']):,.0f} {g['currency']} by {g['target_date']}"
        detail = f"saving {float(g['monthly']):,.0f} {g['currency']} a month, {float(g['saved']):,.0f} saved so far"
        return self._propose("save_goal", title, detail, {"type": "save_goal", "row": g})

    def t_add_account(self, **a):
        if a.get("id"):
            return {"error": "the assistant can add new accounts but not change existing ones; the user can edit them in Money"}
        ccy = str(a.get("currency") or "").upper()
        if len(ccy) != 3 or not ccy.isalpha():
            return {"error": "currency must be a 3-letter code such as EUR or INR"}
        a["currency"] = ccy
        a.setdefault("country", next((c for c, p in self.ctx.packs.items() if p.get("currency") == ccy), ""))
        a["liquid"] = 1 if a.get("liquid", True) else 0
        a.setdefault("in_networth", 1); a.setdefault("opening_balance", 0); a.setdefault("opening_date", date.today().isoformat())
        a.setdefault("type", "Current account")
        date.fromisoformat(str(a["opening_date"]))
        title = f"New account: {a['name']} ({ccy})"
        detail = f"{a['type']}, opening balance {float(a['opening_balance']):,.2f} {ccy} on {a['opening_date']}"
        return self._propose("add_account", title, detail, {"type": "add_account", "row": a})

    def t_add_transaction(self, kind, account_id, amount, category=None, date=None, note=None, to_account_id=None, to_amount=None,
                          frequency=None, end_date=None):
        from datetime import date as _d
        accts = {a["id"]: a for a in self.ctx.db.list("accounts")}
        if account_id not in accts:
            return {"error": "unknown account_id: call get_financial_snapshot for ids"}
        if kind not in ("income", "expense", "transfer"):
            return {"error": "kind must be income, expense or transfer"}
        amount = float(amount)
        if amount <= 0:
            return {"error": "amount must be more than zero"}
        acc = accts[account_id]
        if kind == "transfer":
            if to_account_id not in accts or to_account_id == account_id:
                return {"error": "a transfer needs a different to_account_id"}
            if to_amount is None:
                to_amount = round(ledger.to_ccy(amount, acc["currency"], accts[to_account_id]["currency"], self.ctx.rates), 2)
        row = {"kind": kind, "account_id": account_id, "amount": amount, "category": category or "", "note": note or "",
               "to_account_id": to_account_id if kind == "transfer" else None, "to_amount": to_amount if kind == "transfer" else None}
        when = date or _d.today().isoformat()
        _d.fromisoformat(when)
        what = f"{kind.title()} {amount:,.2f} {acc['currency']}" + (f" to {accts[to_account_id]['name']}" if kind == "transfer" else "")
        detail = " · ".join(x for x in (category, note) if x)
        if frequency:
            if frequency not in ("daily", "weekly", "monthly", "quarterly", "yearly"):
                return {"error": "frequency must be daily, weekly, monthly, quarterly or yearly"}
            if end_date:
                _d.fromisoformat(end_date)
            title = f"Repeating {what} {frequency} from {when} ({acc['name']})"
            return self._propose("add_transaction", title, detail, {"type": "add_recurring", "row": {
                **row, "frequency": frequency, "start_date": when, "end_date": end_date, "active": 1}})
        title = f"{what} on {when} ({acc['name']})"
        return self._propose("add_transaction", title, detail, {"type": "add_transaction", "row": {**row, "date": when}})

    def t_update_deadline(self, key, status):
        if status not in ("open", "done"):
            return {"error": "status must be open or done"}
        d = next((x for x in self.ctx.calendar() if x["key"] == key), None)
        if not d:
            return {"error": "no such deadline: use a key from list_deadlines"}
        title = f"Mark deadline {'done' if status == 'done' else 'open'}: {d['title']}"
        return self._propose("update_deadline", title, f"due {d.get('due') or 'ongoing'}",
                             {"type": "set_deadline_status", "key": key, "status": status})

    def t_run_backtest(self, ticker, strategy="sma_cross", years=10):
        p = trading.synthetic_prices(int(years)) if ticker.upper() == "DEMO" else trading.fetch_prices(ticker, f"{date.today().year - int(years)}-01-01")
        r = trading.backtest(p, strategy)
        r.pop("series", None)
        return r


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def sanitize(history: list) -> None:
    fixed = []
    for i, m in enumerate(history):
        nxt = history[i + 1] if i + 1 < len(history) else None
        if m["role"] == "assistant" and any(b.get("type") == "tool_use" for b in m["content"]):
            if not (nxt and nxt["role"] == "user" and isinstance(nxt["content"], list)):
                continue
        if m["role"] == "user" and isinstance(m["content"], list) and not (fixed and fixed[-1]["role"] == "assistant"):
            continue
        if fixed and fixed[-1]["role"] == m["role"] == "user" and isinstance(m["content"], str) and isinstance(fixed[-1]["content"], str):
            fixed[-1] = {"role": "user", "content": fixed[-1]["content"] + "\n\n" + m["content"]}
            continue
        if fixed and fixed[-1]["role"] == m["role"] == "assistant":
            fixed[-1] = {"role": "assistant", "content": fixed[-1]["content"] + m["content"]}
            continue
        fixed.append(m)
    history[:] = fixed


def chat_stream(provider, ctx, history: list, on_message: Callable[[dict], None]) -> Iterator[str]:
    sanitize(history)
    toolbox, system = Toolbox(ctx), system_prompt(ctx)
    for _ in range(12):
        final = None
        for ev in provider.stream(system, history, TOOLS):
            if isinstance(ev, Final):
                final = ev
            elif ev.kind == "text":
                yield _sse("text", {"t": ev.text})
            elif ev.kind == "tool_start":
                yield _sse("tool", {"name": ev.name, "label": LABELS.get(ev.name, ev.name)})
            elif ev.kind == "error":
                yield _sse("error", {"message": ev.text})
                return
        if final is None:
            yield _sse("error", {"message": "The AI provider ended the reply unexpectedly."})
            return
        amsg = {"role": "assistant", "content": final.content}
        history.append(amsg)
        on_message(amsg)
        if final.stop != "tool_use":
            yield _sse("done", {"usage": final.usage})
            return
        results = []
        for b in final.content:
            if b.get("type") == "tool_use":
                out = toolbox.run(b["name"], b.get("input") or {})
                res = {"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out, ensure_ascii=False, default=str)[:60000]}
                if isinstance(out, dict) and "error" in out:
                    res["is_error"] = True
                results.append(res)
                prop = {"id": out["proposal_id"], "title": out.get("title", "")} if isinstance(out, dict) and out.get("proposal_id") else None
                yield _sse("tool_done", {"name": b["name"], "label": LABELS.get(b["name"], b["name"]), "proposal": prop})
        umsg = {"role": "user", "content": results}
        history.append(umsg)
        on_message(umsg)
        yield _sse("text", {"t": "\n\n"})
    yield _sse("done", {})


def display_messages(history: list) -> list:
    out = []
    for m in history:
        if m["role"] == "user":
            if isinstance(m["content"], str):
                out.append({"role": "user", "text": m["content"]})
            elif out and out[-1]["role"] == "assistant":
                out[-1]["proposals"] += _proposals_in(m["content"])
            continue
        text = "".join(b.get("text", "") for b in m["content"] if b.get("type") == "text")
        tools = [LABELS.get(b["name"], b["name"]) for b in m["content"] if b.get("type") in ("tool_use", "server_tool_use")]
        if out and out[-1]["role"] == "assistant":
            out[-1]["text"] += ("\n\n" if out[-1]["text"] and text else "") + text
            out[-1]["tools"] += tools
        else:
            out.append({"role": "assistant", "text": text, "tools": tools, "proposals": []})
    return out


def _proposals_in(blocks: list) -> list:
    """Proposals the assistant created, read back from the tool results stored in the chat."""
    found = []
    for b in blocks:
        if b.get("type") != "tool_result" or b.get("is_error"):
            continue
        try:
            r = json.loads(b.get("content") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(r, dict) and r.get("proposal_id"):
            found.append({"id": r["proposal_id"], "title": r.get("title", "")})
    return found
