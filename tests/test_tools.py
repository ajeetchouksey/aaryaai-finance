"""One tool list for the in-app assistant and MCP apps: same read tools, same answers, and the new ones work."""
import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.ai import assistant, tools  # noqa: E402
from aaryaai_finance.mcp_server import TOOLS as MCP_TOOLS, Server  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE", "IN"], "base_currency": "EUR"}).status_code == 200
    c.ctx = c.app.state.get_ctx
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 1000, "liquid": 1}).json()["id"]
    c.srv = Server(tmp_path / "d")
    return c


def mcp(srv, name, args=None):
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
    if "error" in r:
        return True, r["error"]["message"]
    return r["result"]["isError"], r["result"]["content"][0]["text"]


def test_both_surfaces_list_the_same_read_tools():
    chat = {t["name"]: t["input_schema"] for t in assistant.TOOLS}
    for t in tools.TOOLS:
        assert t.label and (t.name in chat) == ("chat" in t.surfaces)
    shared = [t for t in tools.TOOLS if t.surfaces == ("chat", "mcp")]
    mcp_tools = {t["name"]: t["inputSchema"] for t in MCP_TOOLS}
    for t in shared:
        assert mcp_tools[t.mcp_name or t.name] == chat[t.name] == t.schema
    assert {"run_calculator", "list_proposals", "money_summary", "find_documents"} <= set(mcp_tools)
    assert "run_backtest" not in mcp_tools and "get_snapshot" in mcp_tools          # names MCP apps already use stay


def test_the_assistant_and_mcp_give_the_same_answer(client):
    box = assistant.Toolbox(client.ctx())
    err, text = mcp(client.srv, "list_deadlines", {"days": 400})
    assert not err and json.loads(text)["items"] == box.run("list_deadlines", {"days": 400})["items"]
    assert box.run("cash_forecast", {})["month_end"] and assistant.LABELS["money_summary"] == "Checked your spending"


def test_run_calculator_now_works_over_mcp(client):
    err, text = mcp(client.srv, "run_calculator", {"pack": "IN", "calculator": "regimes", "inputs": {"other_income": 800000}})
    assert not err and json.loads(text)["headline"] == "New regime"
    assert mcp(client.srv, "run_backtest", {"ticker": "DEMO"}) == (True, "Unknown tool run_backtest")     # chat only


def test_money_summary_totals_this_month_without_listing_every_payment(client):
    today = date.today().isoformat()
    client.post("/api/transactions", json={"date": today, "kind": "expense", "account_id": client.acc, "amount": 40, "category": "Groceries"})
    client.post("/api/transactions", json={"date": today, "kind": "income", "account_id": client.acc, "amount": 3000, "category": "Salary"})
    client.post("/api/expenses", json={"category": "Groceries", "amount": 400})
    s = assistant.Toolbox(client.ctx()).run("money_summary", {})
    assert s["expense"] == 40 and s["income"] == 3000 and s["by_category"] == {"Groceries": 40} and s["count"] == 2
    assert "transactions" not in s
    assert s["budget"]["lines"] == [{"category": "Groceries", "budget": 400, "spent": 40, "left": 360, "status": "ok"}]
    err, text = mcp(client.srv, "money_summary", {"period": "decade"})
    assert err and "week, month or year" in text


def test_list_proposals_shows_what_waits_from_any_source(client):
    err, _ = mcp(client.srv, "propose_transaction", {"account": "Giro", "kind": "expense", "amount": 12, "note": "Lunch"})
    assert not err
    p = assistant.Toolbox(client.ctx()).run("list_proposals", {})
    assert p["count"] == 1 and p["items"][0]["status"] == "pending" and "Lunch" in p["items"][0]["detail"]
    assert set(p["items"][0]) == {"id", "created", "source", "title", "detail", "status", "decided"}       # no raw action
    assert assistant.Toolbox(client.ctx()).run("list_proposals", {"status": "approved"})["count"] == 0


def test_find_documents_by_words_and_year_never_returns_contents(client):
    root = client.ctx().settings.documents_root
    (root / "Tax" / "2025").mkdir(parents=True, exist_ok=True)
    (root / "Tax" / "2025" / "Lohnsteuerbescheinigung_2025.pdf").write_bytes(b"%PDF-1.4 secret salary 54321")
    (root / "Receipts").mkdir(parents=True, exist_ok=True)
    (root / "Receipts" / "dentist_2024.pdf").write_bytes(b"%PDF-1.4")
    box = assistant.Toolbox(client.ctx())
    hit = box.run("find_documents", {"query": "lohnsteuer"})
    assert hit["count"] == 1 and hit["items"][0]["path"] == "Tax/2025/Lohnsteuerbescheinigung_2025.pdf"
    assert box.run("find_documents", {"year": 2024})["items"][0]["name"] == "dentist_2024.pdf"
    assert box.run("find_documents", {"query": "nothing-like-this"})["count"] == 0
    err, text = mcp(client.srv, "find_documents", {})
    assert not err and json.loads(text)["count"] == 2 and "54321" not in text
