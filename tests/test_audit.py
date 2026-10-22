"""Every change goes into the audit log (Routines → Audit log), and nothing secret goes with it."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance import server as srv  # noqa: E402
from conftest import local_client  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    c = local_client(srv.create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"}).status_code == 200
    c.ctx = c.app.state.get_ctx
    return c


def audit_rows(c):
    return c.ctx().db.list("audit")


def _file_a_document(c):
    a = c.post("/docs/analyze", json={"filename": "note.txt", "data": base64.b64encode(b"hello").decode()}).json()
    return c.post("/docs/file", json={**a, "folder": "Misc"})


def _deadline(c):
    key = next(d["key"] for d in c.get("/calendar").json())
    return c.post("/calendar/status", json={"key": key, "status": "done"})


def _chat(c):
    cid = c.ctx().db.chat_create("hi")
    return c.delete(f"/chat/{cid}")


CHANGES = {
    "Changed settings": lambda c: c.post("/config", json={"profile": {"name": "Robin"}, "secrets": {"github_token": "ghp_secret_value"}}),
    "Removed an API key": lambda c: c.post("/config/secret/clear", json={"key": "github_token"}),
    "Changed custom fields and record types": lambda c: c.post("/model/user", json={"text": ""}),
    "Changed your rules": lambda c: c.post("/rules/user", json={"text": ""}),
    "Changed income and paper-trading settings": lambda c: c.post("/api-settings", json={"monthly_income": 4000}),
    "Changed tax allowance figures": lambda c: c.post("/opportunities/inputs", json={"de_allowance_used": 200}),
    "Changed routine settings": lambda c: c.post("/routines/settings", json={"ai_summary": False}),
    "Changed a deadline's status": _deadline,
    "Filed a document": _file_a_document,
    "Changed the AI model": lambda c: c.post("/chat/model", json={"model": "x"}),
    "Deleted a chat": _chat,
}


@pytest.mark.parametrize("label", list(CHANGES))
def test_each_change_is_logged_once(client, label):
    before = len(audit_rows(client))
    assert CHANGES[label](client).status_code == 200
    new = audit_rows(client)[before:]
    assert [r["action"] for r in new if r["action"] == label] == [label]
    assert all("ghp_secret_value" not in (r["detail"] or "") + r["action"] for r in audit_rows(client))


def test_refused_changes_are_not_logged(client):
    before = len(audit_rows(client))
    assert client.post("/config", json={"documents_root": "/"}).status_code in (200, 400)
    assert client.post("/calendar/status", json={"status": "done"}).status_code == 400
    assert client.post("/calendar/status", json={"key": "nope", "status": "done"}).status_code == 404
    assert not any(r["action"] == "Changed a deadline's status" for r in audit_rows(client)[before:])


def test_every_audited_route_exists(tmp_path):
    app = srv.create_app(tmp_path / "d")
    routes = {(m, r.path) for r in app.routes for m in getattr(r, "methods", ())}
    assert set(srv.AUDITED) <= routes


def test_mcp_refused_calls_are_logged(client, tmp_path):
    from aaryaai_finance.mcp_server import Server
    s = Server(tmp_path / "d")
    r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "propose_transaction", "arguments": {
        "account": "nope", "kind": "expense", "amount": 5}}})
    assert r["result"]["isError"]
    assert any(a["action"] == "Called propose_transaction (refused)" for a in s.ctx.db.list("audit"))
