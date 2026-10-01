"""MCP server: lets an AI assistant on this computer (Claude Desktop, VS Code with GitHub Copilot, …) read your numbers.

It runs only when your assistant starts it, as a local process talking over stdin/stdout (the "stdio"
transport) — there is no network port. It reads the same data folder as the app.

- Read tools: snapshot, cash forecast, deadlines, goal odds, diversification, opportunities, tax status.
- Two "propose_" tools can suggest a transaction or a planned item. They change nothing: the proposal waits
  for your approval on the Routines screen. Every call is written to the audit log.

Start it by hand to test:  aaryaai-finance mcp --data-dir PATH   (then type JSON-RPC lines)
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import __version__

PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]

TOOLS = [
    {"name": "get_snapshot", "description": "Net worth, accounts with balances, assets and debts, holdings, goals, this month's income and spending, staged purchases, exchange rates.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "cash_forecast", "description": "12-month cash forecast per currency: month-end balances, lowest points against the user's floors, and the funding plan (transfers between currencies).",
     "inputSchema": {"type": "object", "properties": {"scenario": {"type": "string", "enum": ["base", "salary_late", "stage_early", "no_estimated", "fx_weak"]}}}},
    {"name": "list_deadlines", "description": "Open tax and compliance deadlines in the next N days (default 60).",
     "inputSchema": {"type": "object", "properties": {"days": {"type": "integer"}}}},
    {"name": "goal_odds", "description": "Each goal's probability of success from 2,000 simulated markets, the saving per month for 85%, and what-if scenarios.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "diversification", "description": "What the user owns by asset class, country, currency and sector (looking inside index funds), concentration flags and the user's own rules.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "opportunities", "description": "Tax-aware opportunities from the user's country packs: allowances, holding periods, deadlines. Facts, not buy/sell advice.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "tax_status", "description": "Tax-year workspace status for a country: documents found/missing, answers, estimate, findings and filing-sheet lines.",
     "inputSchema": {"type": "object", "properties": {"country": {"type": "string", "description": "2-letter code, e.g. DE or IN"}, "year": {"type": "integer"}}, "required": ["country"]}},
    {"name": "propose_transaction", "description": "Suggest a transaction. Nothing is saved until the user approves it in the app (Routines → Proposals).",
     "inputSchema": {"type": "object", "required": ["account", "kind", "amount"], "properties": {
         "account": {"type": "string", "description": "account name or id"}, "kind": {"type": "string", "enum": ["income", "expense"]},
         "amount": {"type": "number"}, "date": {"type": "string"}, "category": {"type": "string"}, "note": {"type": "string"}}}},
    {"name": "propose_planned_item", "description": "Suggest a future planned income, expense or transfer for the forecast. Waits for the user's approval.",
     "inputSchema": {"type": "object", "required": ["account", "kind", "amount", "date"], "properties": {
         "account": {"type": "string"}, "kind": {"type": "string", "enum": ["income", "expense", "transfer"]}, "amount": {"type": "number"},
         "date": {"type": "string"}, "to_account": {"type": "string"}, "category": {"type": "string"}, "note": {"type": "string"},
         "confidence": {"type": "string", "enum": ["known", "planned", "estimated"]}}}},
]


class Server:
    def __init__(self, data_dir: Path | None = None):
        from .config import Settings, default_data_dir, remembered_data_dir
        from .context import Ctx
        self.ctx = Ctx(Settings(data_dir or remembered_data_dir() or default_data_dir()))
        self.client = "assistant"

    # ---------------------------------------------------------------- tools
    def _account(self, ref) -> dict:
        accts = self.ctx.accounts_with_balance()
        for a in accts:
            if str(a["id"]) == str(ref) or a["name"].lower() == str(ref).lower():
                return a
        raise ValueError(f"No account '{ref}'. Accounts: " + ", ".join(a["name"] for a in accts))

    def call(self, name: str, a: dict):
        c = self.ctx
        if name == "get_snapshot":
            return c.snapshot()
        if name == "cash_forecast":
            f = c.forecast(a.get("scenario") or "base")
            return {k: f[k] for k in ("today", "base", "scenario", "months", "floors", "lowest", "plan", "watch", "options", "next90")} | {
                "month_end": {ccy: [{"month": r["month"], "end": r["end"], "low": r["low"]} for r in rows] for ccy, rows in f["series"].items()}}
        if name == "list_deadlines":
            until = (date.today() + timedelta(days=int(a.get("days") or 60))).isoformat()
            return [d for d in c.calendar() if d["status"] == "open" and d["due"] and d["due"] <= until]
        if name == "goal_odds":
            return c.goal_odds()
        if name == "diversification":
            d = c.diversify()
            return {k: d[k] for k in ("base", "total", "classes", "countries", "currencies", "sectors", "companies", "flags", "checks", "targets", "options")}
        if name == "opportunities":
            return c.opportunities()
        if name == "tax_status":
            ws = c.tax_workspace(str(a["country"]).upper(), a.get("year"))
            return {k: ws[k] for k in ("title", "year_label", "steps", "documents", "questions", "derived", "checks", "sheet", "estimate")}
        if name in ("propose_transaction", "propose_planned_item"):
            acc = self._account(a["account"])
            amt = float(a["amount"])
            if amt <= 0:
                raise ValueError("amount must be more than zero")
            d = a.get("date") or date.today().isoformat()
            date.fromisoformat(d)
            row = {"date": d, "kind": a["kind"], "account_id": acc["id"], "amount": amt, "category": a.get("category") or "", "note": a.get("note") or ""}
            if name == "propose_planned_item":
                if a["kind"] == "transfer":
                    row["to_account_id"] = self._account(a.get("to_account") or "")["id"]
                row["confidence"] = a.get("confidence") or "planned"
                action, what = {"type": "add_planned", "row": row}, "planned"
            else:
                if a["kind"] not in ("income", "expense"):
                    raise ValueError("kind must be income or expense")
                action, what = {"type": "add_transaction", "row": row}, "transaction"
            key = f"mcp:{what}:{acc['id']}:{d}:{amt}:{a['kind']}"
            pid = c.propose(key, f"MCP · {self.client}", f"{a['kind'].title()} {amt:,.2f} {acc['currency']} on {d} ({acc['name']})",
                            a.get("note") or "", f"suggested by {self.client}", action)
            return {"proposal_id": pid, "status": "waiting for the user's approval in the app (Routines → Proposals)"}
        raise KeyError(name)

    # ---------------------------------------------------------------- JSON-RPC
    def handle(self, msg: dict) -> dict | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:                      # notification (e.g. notifications/initialized): no reply
            return None
        try:
            if method == "initialize":
                self.client = (params.get("clientInfo") or {}).get("name") or "assistant"
                want = params.get("protocolVersion")
                return self._ok(mid, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                                      "capabilities": {"tools": {"listChanged": False}},
                                      "serverInfo": {"name": "aaryaai-finance", "version": __version__},
                                      "instructions": "Personal finance data from the user's own computer. Amounts are in the currency named next to them. "
                                                      "Use propose_* tools only when the user asks; proposals need their approval in the app. Don't give buy/sell advice."})
            if method == "ping":
                return self._ok(mid, {})
            if method == "tools/list":
                return self._ok(mid, {"tools": TOOLS})
            if method == "tools/call":
                name, args = params.get("name"), params.get("arguments") or {}
                if name not in {t["name"] for t in TOOLS}:
                    return self._err(mid, -32602, f"Unknown tool {name}")
                try:
                    result = self.call(name, args)
                    self.ctx.audit(f"MCP · {self.client}", f"Called {name}", json.dumps(args)[:200])
                    return self._ok(mid, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}], "isError": False})
                except (ValueError, KeyError, TypeError) as e:
                    return self._ok(mid, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
            return self._err(mid, -32601, f"Method not found: {method}")
        except Exception as e:  # noqa: BLE001
            return self._err(mid, -32603, f"{type(e).__name__}: {e}")

    @staticmethod
    def _ok(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _err(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def serve(self, inp=None, out=None):
        if inp is None:
            # MCP messages are UTF-8. On Windows a piped stdin/stdout defaults to the console code page (e.g. cp1252).
            for stream in (sys.stdin, sys.stdout):
                try:
                    stream.reconfigure(encoding="utf-8", newline="\n")
                except (AttributeError, ValueError):
                    pass
        inp, out = inp or sys.stdin, out or sys.stdout
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                out.write(json.dumps(self._err(None, -32700, "Parse error")) + "\n"); out.flush()
                continue
            batch = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (self.handle(m) for m in batch if isinstance(m, dict)) if r]
            if replies:
                # ASCII-only JSON (non-ASCII as \\uXXXX) is valid for every client and can't fail on any console encoding
                out.write(json.dumps(replies if isinstance(msg, list) else replies[0], ensure_ascii=True, default=str) + "\n")
                out.flush()


def config_snippet(data_dir: Path) -> dict:
    """What to paste into Claude Desktop's claude_desktop_config.json (or VS Code's mcp.json 'servers')."""
    return {"mcpServers": {"aaryaai-finance": {"command": sys.executable, "args": ["-m", "aaryaai_finance", "mcp", "--data-dir", str(data_dir)]}}}
