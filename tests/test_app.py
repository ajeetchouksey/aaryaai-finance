"""End-to-end tests through the HTTP API with a throw-away data folder."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from aaryaai_finance.ai.providers import to_openai_messages, to_openai_tools  # noqa: E402
from aaryaai_finance.core import ledger  # noqa: E402
from aaryaai_finance.rules.engine import RuleSet, validate_rules_yaml, _render_text  # noqa: E402
from aaryaai_finance.server import create_app
from conftest import local_client  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "appdata"))
    c = local_client(create_app(tmp_path / "boot"))
    r = c.post("/setup/apply", json={"data_dir": str(tmp_path / "data"), "name": "Test User", "countries": ["DE", "IN"],
                                    "base_currency": "EUR", "answers": {"in_nri": True, "de_mandatory_filing": False}})
    assert r.status_code == 200, r.text
    # deterministic FX for tests
    c.post("/config", json={"fx": {"source": "manual", "manual_rates": {"INR": 100}}})
    return c


def test_setup_and_config(client, tmp_path):
    cfg = client.get("/config").json()
    assert cfg["configured"] and cfg["currencies"] == ["EUR", "INR"]
    assert (tmp_path / "data" / "config.yaml").exists()
    assert "secret" not in (tmp_path / "data" / "config.yaml").read_text()


def test_secrets_never_returned(client):
    client.post("/config", json={"ai": {"provider": "anthropic"}, "secrets": {"anthropic_api_key": "sk-ant-test-1234"}})
    body = client.get("/config").text
    assert "sk-ant-test-1234" not in body and '"anthropic_api_key":true' in body.replace(" ", "")


def test_money_multi_currency(client):
    eur = client.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "type": "Current account", "opening_balance": 1000, "liquid": 1, "in_networth": 1}).json()["id"]
    inr = client.post("/api/accounts", json={"name": "NRE", "country": "IN", "currency": "INR", "type": "NRE account", "opening_balance": 0, "liquid": 1, "in_networth": 1}).json()["id"]
    assert client.post("/api/transactions", json={"date": "2026-09-03", "account_id": eur, "kind": "transfer", "amount": 100, "to_account_id": inr}).status_code == 200
    acc = client.get("/money/accounts").json()
    assert acc["totals"] == {"EUR": 900.0, "INR": 10000.0} and acc["total_base"] == 1000.0
    nw = client.get("/calc/position").json()["net_worth"]
    assert nw["net_worth"] == 1000.0 and nw["base"] == "EUR"
    assert client.post("/api/transactions", json={"date": "2026-09-03", "account_id": eur, "kind": "expense", "amount": 0}).status_code == 400


def test_calendar_from_packs_and_status(client):
    cal = client.get("/calendar").json()
    keys = [d["key"] for d in cal]
    assert any(k.startswith("in_itr_belated:") for k in keys)            # India pack
    assert any(k.startswith("de_return_voluntary_last:") for k in keys)  # answer de_mandatory_filing = False
    assert not any(k.startswith("de_return_mandatory:") for k in keys)
    k = keys[0]
    client.post("/calendar/status", json={"key": k, "status": "done"})
    assert next(d for d in client.get("/calendar").json() if d["key"] == k)["status"] == "done"


def test_tax_calculators_from_packs(client):
    calcs = client.get("/tax/calculators").json()["calculators"]
    assert {(c["pack"], c["id"]) for c in calcs} >= {("DE", "refund"), ("IN", "regimes")}
    r = client.post("/tax/run", json={"pack": "IN", "calculator": "regimes", "inputs": {"other_income": 800000}}).json()
    assert r["headline"] == "New regime"


def test_user_rules_override_and_validate(client):
    bad = client.post("/rules/user", json={"text": "document_rules:\n  - id: x\n    match: {}\n"})
    assert bad.status_code == 400
    good = "document_rules:\n  - id: my_gym\n    label: Gym invoice\n    category: Receipts & bills\n    confidence: 0.9\n    match: {text_any: [fitnessfirst]}\n    route: {folder: 'Receipts/Gym', filename: '{first_date}_gym{ext}'}\n"
    assert client.post("/rules/user", json={"text": good}).status_code == 200
    data = base64.b64encode(b"Fitness First Rechnung 12.09.2026 total").decode()
    a = client.post("/rules/test", json={"filename": "scan.txt", "data": data}).json()
    assert a["doc_type"] == "my_gym" and a["folder"] == "Receipts/Gym" and a["filename"] == "2026-09-12_gym.txt"


def test_document_file_and_review(client, tmp_path):
    txt = "Lohnsteuerbescheinigung für 2024 Bruttoarbeitslohn".encode()
    a = client.post("/docs/analyze", json={"filename": "scan.txt", "data": base64.b64encode(txt).decode()}).json()
    assert a["doc_type"] == "de_lohnsteuerbescheinigung" and a["folder"] == "Germany" and a["filename"] == "Lohnsteuerbescheinigung 2024.txt"
    r = client.post("/docs/file", json={**a, "folder": "Misfiled"}).json()
    assert (tmp_path / "data" / "documents" / "Misfiled" / "Lohnsteuerbescheinigung 2024.txt").exists()
    rev = client.get("/docs/review").json()
    assert rev["suggestions"][0]["suggested_folder"] == "Germany"
    assert client.post("/docs/file", json={**a, "folder": "../../escape"}).status_code == 400


def test_chat_needs_provider(client):
    assert client.get("/chat/meta").json()["ready"] is False
    assert client.post("/chat/send", json={"text": "hi"}).status_code == 400


def test_openai_conversion_roundtrip():
    hist = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "checking"}, {"type": "tool_use", "id": "t1", "name": "list_deadlines", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]}]
    m = to_openai_messages("sys", hist)
    assert [x["role"] for x in m] == ["system", "user", "assistant", "tool"]
    assert m[2]["tool_calls"][0]["function"]["name"] == "list_deadlines"
    assert to_openai_tools([{"name": "a", "input_schema": {"type": "object"}}, {"type": "web_search_20250305", "name": "web_search"}])[0]["function"]["name"] == "a"


def test_deadline_templates():
    assert _render_text("{tax_year+1}-07-31 FY {tax_year}-{tax_year_next2}", 2025) == "2026-07-31 FY 2025-26"
    assert validate_rules_yaml("deadlines:\n  - id: a\n") != []


def test_recurring_idempotent(tmp_path):
    from aaryaai_finance.core.db import DB
    from datetime import date
    db = DB(tmp_path / "t.db")
    a = db.upsert("accounts", {"name": "A", "country": "DE", "currency": "EUR", "type": "x", "opening_balance": 0, "liquid": 1, "in_networth": 1})
    db.upsert("recurring", {"kind": "expense", "account_id": a, "amount": 5, "category": "x", "frequency": "monthly", "start_date": "2026-01-31", "active": 1})
    assert ledger.materialize_recurring(db, date(2026, 4, 30)) == 4 and ledger.materialize_recurring(db, date(2026, 4, 30)) == 0
