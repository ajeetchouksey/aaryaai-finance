"""The in-app assistant only *proposes* changes: nothing is saved until the person approves, and both steps are audited."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance import server as srv  # noqa: E402
from aaryaai_finance.ai.providers import Event, Final  # noqa: E402
from conftest import local_client  # noqa: E402


class ScriptedProvider:
    """Plays back one tool call, then a short answer, like a real provider would."""
    def __init__(self, calls):
        self.calls, self.turn = calls, 0

    def stream(self, system, history, tools):
        self.turn += 1
        if self.turn == 1:
            blocks = []
            for i, (name, args) in enumerate(self.calls):
                yield Event("tool_start", name=name)
                blocks.append({"type": "tool_use", "id": f"t{i}", "name": name, "input": args})
            yield Final(blocks, "tool_use")
        else:
            yield Event("text", text="Proposed it for you.")
            yield Final([{"type": "text", "text": "Proposed it for you."}], "end_turn")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    c = local_client(srv.create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "data"), "name": "T", "countries": ["DE"], "base_currency": "EUR",
                                        "answers": {}}).status_code == 200
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 1000, "liquid": 1}).json()["id"]
    c.monkeypatch = monkeypatch
    return c


def chat(client, *calls):
    client.monkeypatch.setattr(srv, "make_provider", lambda cfg, secret: ScriptedProvider(list(calls)))
    r = client.post("/chat/send", json={"text": "please do it"})
    assert r.status_code == 200
    events = []
    for block in r.text.split("\n\n"):
        if block.startswith("event: "):
            ev, data = block.split("\n", 1)
            events.append((ev[7:], json.loads(data[6:])))
    return events


def test_add_transaction_waits_for_approval(client):
    before = len(client.get("/api/transactions").json())
    events = chat(client, ("add_transaction", {"kind": "expense", "account_id": client.acc, "amount": 42.5, "category": "Groceries"}))
    done = next(d for e, d in events if e == "tool_done")
    assert done["proposal"] and done["label"] == "Proposed an entry"
    assert len(client.get("/api/transactions").json()) == before                   # nothing saved yet
    routines = client.get("/routines").json()
    prop = next(p for p in routines["proposals"] if p["id"] == done["proposal"]["id"])
    assert prop["status"] == "pending" and prop["source"] == "AI assistant" and "42.50 EUR" in prop["title"]
    assert any(a["actor"] == "AI assistant" and a["action"].startswith("Proposed:") for a in routines["audit"])

    ok = client.post(f"/proposals/{prop['id']}", json={"decision": "approve"}).json()
    assert ok["ok"] and "transaction" in ok["result"]
    txs = client.get("/api/transactions").json()
    assert len(txs) == before + 1 and txs[-1]["amount"] == 42.5
    assert any(a["action"].startswith("Approved:") for a in client.get("/routines").json()["audit"])

    msgs = client.get(f"/chat/{next(d for e, d in events if e == 'chat')['id']}").json()["messages"]
    assert msgs[-1]["proposals"] == [{"id": prop["id"], "title": prop["title"], "status": "approved"}]


def test_each_change_tool_proposes_and_approval_applies(client):
    deadline = next(d for d in client.get("/calendar").json() if d["status"] != "done")
    events = chat(client,
                  ("save_goal", {"name": "Car", "target_today": 20000, "target_date": "2030-01-01"}),
                  ("add_account", {"name": "Tagesgeld", "currency": "eur"}),
                  ("add_transaction", {"kind": "income", "account_id": client.acc, "amount": 3000, "frequency": "monthly", "date": "2026-01-25"}),
                  ("update_deadline", {"key": deadline["key"], "status": "done"}))
    props = [d["proposal"] for e, d in events if e == "tool_done"]
    assert all(props) and len(props) == 4
    assert not any(g["name"] == "Car" for g in client.get("/api/goals").json())
    assert not any(a["name"] == "Tagesgeld" for a in client.get("/api/accounts").json())
    assert not client.get("/api/recurring").json()
    for p in props:
        assert client.post(f"/proposals/{p['id']}", json={"decision": "approve"}).json()["ok"]
    assert any(g["name"] == "Car" for g in client.get("/api/goals").json())
    assert next(a for a in client.get("/api/accounts").json() if a["name"] == "Tagesgeld")["currency"] == "EUR"
    assert client.get("/api/recurring").json()[0]["frequency"] == "monthly"
    assert next(d for d in client.get("/calendar").json() if d["key"] == deadline["key"])["status"] == "done"


@pytest.mark.parametrize("name,args", [
    ("add_transaction", {"kind": "expense", "account_id": 1, "amount": -5}),
    ("add_transaction", {"kind": "expense", "account_id": 999, "amount": 5}),
    ("add_transaction", {"kind": "transfer", "account_id": 1, "amount": 5}),
    ("add_account", {"id": 1, "name": "Giro", "currency": "EUR", "opening_balance": 1}),
    ("save_goal", {"id": 999, "name": "X", "target_today": 1, "target_date": "2030-01-01"}),
    ("update_deadline", {"key": "nope", "status": "done"}),
])
def test_bad_requests_create_no_proposal(client, name, args):
    events = chat(client, (name, args))
    done = next(d for e, d in events if e == "tool_done")
    assert done["proposal"] is None
    assert not client.get("/routines").json()["proposals"]


def test_web_search_and_ai_summary_are_opt_in(client):
    assert client.get("/config").json()["ai"]["web_search"] is False
    assert client.get("/routines").json()["ai_summary"] is False
