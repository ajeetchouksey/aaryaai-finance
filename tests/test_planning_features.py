"""0.5 planning features: cash forecast, goal odds, diversification, opportunities, tax workspace, routines, MCP."""
import io
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance.core import forecast as fc, odds as od, portfolio as pf  # noqa: E402
from aaryaai_finance.tax import opportunities as op, workspace as tw  # noqa: E402
from aaryaai_finance.packs import available_packs  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402

TODAY = date(2026, 9, 30)
RATES = {"_base": "EUR", "EUR": 1.0, "INR": 100.0}


def acct(i, name, ccy, bal, liquid=1, country=None):
    return {"id": i, "name": name, "currency": ccy, "balance": bal, "liquid": liquid, "archived": 0, "country": country or ("IN" if ccy == "INR" else "DE"),
            "in_networth": 1}


# ---------------------------------------------------------------- forecast
def test_forecast_funds_a_big_inr_payment_from_eur():
    accounts = [acct(1, "Giro", "EUR", 20000), acct(2, "NRE", "INR", 100000)]
    rec = [{"id": 1, "kind": "income", "account_id": 1, "amount": 4000, "category": "Salary", "note": "Salary", "frequency": "monthly",
            "start_date": "2026-01-25", "end_date": None, "active": 1, "to_account_id": None, "to_amount": None},
           {"id": 2, "kind": "expense", "account_id": 1, "amount": 1500, "category": "Rent", "note": "Rent", "frequency": "monthly",
            "start_date": "2026-01-01", "end_date": None, "active": 1, "to_account_id": None, "to_amount": None}]
    planned = [{"id": 1, "date": "2027-03-10", "kind": "expense", "account_id": 2, "amount": 700000, "category": "Property", "note": "Stage 12",
                "confidence": "known", "done": 0, "to_account_id": None, "to_amount": None}]
    f = fc.forecast(accounts, rec, planned, [], [], RATES, "EUR", {"EUR": 3000, "INR": 50000}, 12, today=TODAY)
    assert f["months"][0] == "2026-09" and len(f["months"]) == 12
    assert len(f["plan"]) == 1
    step = f["plan"][0]
    assert step["month"] == "2027-03" and step["ccy"] == "INR" and step["from_ccy"] == "EUR"
    assert step["date"] == "2027-02-15"                                       # a month ahead of the payment
    assert step["receive"] >= 650000 and step["send"] >= step["receive"] / 100   # covers the gap to the floor, fees included
    assert f["lowest"]["INR"]["low"] >= 50000 - 1 and f["lowest"]["INR"]["without_plan"] < 0
    assert not f["watch"]
    assert f["sources"][0]["confidence"] == "known"


def test_forecast_scenarios_and_learned_spending():
    accounts = [acct(1, "Giro", "EUR", 1000)]
    rec = [{"id": 7, "kind": "income", "account_id": 1, "amount": 3000, "category": "Salary", "note": "Salary", "frequency": "monthly",
            "start_date": "2026-01-28", "end_date": None, "active": 1, "to_account_id": None, "to_amount": None}]
    tx = [{"date": f"2026-0{m}-10", "kind": "expense", "account_id": 1, "amount": a, "recurring_id": None} for m, a in [(3, 400), (4, 500), (5, 450), (6, 3000), (7, 420), (8, 480)]]
    base = fc.forecast(accounts, rec, [], [], tx, RATES, "EUR", {"EUR": 0}, 3, today=TODAY)
    assert base["learned"]["EUR"] == pytest.approx(465)            # median, so the 3,000 month doesn't skew it
    late = fc.forecast(accounts, rec, [], [], tx, RATES, "EUR", {"EUR": 0}, 3, today=TODAY, scenario="salary_late")
    oct_base = base["series"]["EUR"][1]
    oct_late = late["series"]["EUR"][1]
    assert oct_late["in"] == 0 and oct_base["in"] == 3000
    assert late["series"]["EUR"][2]["in"] == 6000


def test_forecast_uses_tracker_stage_with_tds():
    t = {"id": "f", "name": "Flat", "currency": "INR", "price": 1000000, "tax_rate_on_payments": 0.05, "tds_rate": 0.01,
         "possession_date": "2028-06-30", "stages": [{"name": "Booking", "paid": "2025-01"}, {"name": "Slab", "due": "2026-12-10", "amount": 200000}],
         "payments": [{"date": "2025-01-15", "cumulative": 100000}]}
    f = fc.forecast([acct(2, "NRE", "INR", 500000)], [], [], [t], [], RATES, "EUR", {"INR": 0}, 6, today=TODAY)
    item = next(i for i in f["items"] if i["source"] == "tracker")
    assert item["amount"] == -210000 and item["tds"] == 2000 and item["confidence"] == "known" and item["date"] == "2026-12-10"


# ---------------------------------------------------------------- goal odds
def test_goal_odds_are_deterministic_and_monotonic():
    g = {"id": 3, "target_today": 40000, "target_date": "2038-09-01", "saved": 7000, "monthly": 250, "annual_return": 0.045, "inflation": 0.02, "risk": "balanced"}
    a, b = od.odds(g, TODAY), od.odds(g, TODAY)
    assert a == b
    more = od.odds(g, TODAY, monthly=400)
    assert more["probability"] > a["probability"] and a["p10"] < a["p50"] < a["p90"]
    need = od.monthly_for(g, 0.85, TODAY)
    assert need and od.odds(g, TODAY, monthly=need, runs=400)["probability"] >= 0.85
    cash = {**g, "risk": "cash", "annual_return": 0.0, "inflation": 0.0, "target_today": 1000, "saved": 1000, "monthly": 0}
    assert od.odds(cash, TODAY)["probability"] > 0.4
    rows = od.whatif([g], TODAY)
    assert rows[0]["id"] == "today" and rows[1]["probabilities"][0] >= rows[0]["probabilities"][0]


# ---------------------------------------------------------------- diversify
def test_diversify_looks_inside_funds_and_flags_overlap():
    lib = pf.load_library()
    assert pf.match_index({"name": "Vanguard FTSE All-World", "ticker": "VWCE.DE"}, lib) == "ftse_all_world"
    assert pf.match_index({"name": "iShares Core MSCI World"}, lib) == "msci_world"
    holdings = [{"name": "All-World", "ticker": "VWCE", "qty": 100, "last_price": 100, "currency": "EUR", "country": "DE"},
                {"name": "Nasdaq 100", "ticker": "EQQQ", "qty": 10, "last_price": 500, "currency": "EUR", "country": "DE"},
                {"name": "Mystery fund", "qty": 10, "last_price": 100, "currency": "EUR", "country": "DE", "asset_type": "Fund"}]
    items = [{"name": "Flat", "kind": "asset", "category": "Property (under construction)", "amount": 2000000, "currency": "INR", "country": "IN"},
             {"name": "Car", "kind": "asset", "category": "Vehicle", "amount": 9000, "currency": "EUR"}]
    r = pf.analyse([acct(1, "Giro", "EUR", 5000)], holdings, items, "EUR", RATES, lib, targets={"shares": 60, "cash": 10}, monthly_spend=1000)
    assert r["total"] == pytest.approx(5000 + 10000 + 5000 + 1000 + 20000)   # car left out
    assert abs(sum(c["share"] for c in r["classes"]) - 1) < 0.001
    assert any(c["name"] == "Nvidia" and len(c["via"]) == 2 for c in r["overlap"])
    assert any("Mystery fund" in f["detail"] for f in r["flags"])
    assert any(f["title"].startswith("Flat is") for f in r["flags"])
    cash_check = next(c for c in r["checks"] if c["rule"] == "min_cash_months")
    assert not cash_check["ok"] and cash_check["value"] == "5.0 months"
    assert next(t for t in r["targets"] if t["key"] == "shares")["gap"] > 0


# ---------------------------------------------------------------- opportunities
def _packs():
    return available_packs()


def test_opportunities_germany_and_india():
    accounts = [acct(1, "Tagesgeld", "EUR", 10000) | {"de_freistellungsauftrag": 800, "de_capital_income_ytd": 140},
                acct(2, "Broker", "EUR", 100) | {"de_freistellungsauftrag": 200, "de_capital_income_ytd": 1240},
                acct(3, "Bank B", "EUR", 100) | {"de_losses_ytd": 320}]
    holdings = [{"name": "Nifty old", "qty": 1000, "avg_cost": 100, "last_price": 200, "currency": "INR", "country": "IN", "bought": "2024-01-10"},
                {"name": "Nifty new", "qty": 100, "avg_cost": 150, "last_price": 200, "currency": "INR", "country": "IN", "bought": "2025-10-20"},
                {"name": "World ETF", "qty": 100, "avg_cost": 80, "last_price": 100, "currency": "EUR", "country": "DE", "payout": "accumulating"}]
    d = op.Data(TODAY, "EUR", RATES, {"de_joint": False, "in_nri": True}, accounts, holdings, {"in_ltcg_used": "38000"})
    packs = {k: v for k, v in _packs().items() if k in ("DE", "IN")}
    cards, errs = op.run_all(packs, d)
    assert not errs
    by = {c["rule"]: c for c in cards}
    fsa = by["de.fsa_rebalance"]
    assert fsa["effect_value"] == pytest.approx(660 * 0.26375, abs=0.01)             # 1,040 over at the broker, 660 spare at Tagesgeld
    assert by["de.loss_certificate"]["effect_value"] == pytest.approx(320 * 0.26375, abs=0.01)
    h = by["in.ltcg_harvest"]
    assert h["extra"]["room"] == 87000 and h["effect_value"] == pytest.approx(87000 * 0.125) and h["caveat"]
    cd = by["in.short_to_long"]
    assert cd["extra"]["days"] == 21 and cd["deadline"] == "2026-10-21"
    assert by["de.vorabpauschale"]["effect_value"] < 0


def test_tax_on_sale_india_and_germany():
    packs = _packs()
    t, _ = op.tax_on_sale(packs, {"qty": 10, "avg_cost": 100, "last_price": 200, "currency": "EUR", "country": "DE"}, 2000, TODAY)
    assert t == pytest.approx(max(1000 * 0.7 - 1000, 0) * 0.26375)
    t, _ = op.tax_on_sale(packs, {"qty": 1000, "avg_cost": 100, "last_price": 400, "currency": "INR", "country": "IN", "bought": "2024-01-01"}, 400000, TODAY)
    assert t == pytest.approx((300000 - 125000) * 0.125)


# ---------------------------------------------------------------- tax workspace
@pytest.mark.parametrize("bad", ["__import__('os')", "a.b", "open('x')", "[1,2]", "'text'", "x[0]", "(lambda: 1)()"])
def test_formula_evaluator_refuses_anything_but_arithmetic(bad):
    with pytest.raises(tw.FormulaError):
        tw.evaluate(bad, {})


def test_formula_evaluator_arithmetic():
    env = {"a": 10, "b": None, "flag": True}
    assert tw.evaluate("min(a, 20) * 0.3 + max(b - 1, 0)", env) == pytest.approx(3.0)
    assert tw.evaluate("a / 0", env) == 0.0
    assert tw.evaluate("5 if flag and a > 3 else 7", env) == 5
    assert tw.evaluate("unknown_name + 1", env) == 1


def test_germany_workspace_builds_sheet_and_estimate():
    from aaryaai_finance.tax import engines
    de = _packs()["DE"]
    calcs = {c["id"]: c for c in de["calculators"]}
    run = lambda cid, i: engines.run(calcs[cid]["engine"], calcs[cid]["params"], i, "EUR")  # noqa: E731
    docs = [{"stored_path": "Germany/Lohnsteuerbescheinigung 2025.pdf", "doc_type": "de_lohnsteuerbescheinigung",
             "fields": json.dumps({"tax_year": "2025", "gross": "68.400,00", "lohnsteuer": "11.982,00"})}]
    ws = tw.build(de, 2025, {"commute_km": 18, "commute_days": 42, "homeoffice_days": 180, "other_work": 390,
                             "capital_income": 1240, "foreign_interest": 620, "foreign_tax": 62}, docs, {"de_joint": True}, run)
    q = {x["id"]: x for x in ws["questions"]}
    assert q["gross"]["value"] == 68400 and q["gross"]["source"].startswith("from ")
    assert q["joint"]["value"] is True
    d = {x["id"]: x["value"] for x in ws["derived"]}
    assert d["commute"] == pytest.approx(42 * 18 * 0.30) and d["homeoffice"] == 1080 and d["foreign_credit"] == 62
    assert ws["documents"][0]["status"] == "found" and ws["steps"][0]["done"]
    assert ws["estimate"]["data"]["refund"] > 0
    ids = {c["id"] for c in ws["checks"]}
    assert {"above_lump_sum", "foreign_credit"} <= ids
    sheet = {r["field"]: r for r in ws["sheet"]}
    assert sheet["Bruttoarbeitslohn"]["shown"] == "€68,400" and "Weitere Werbungskosten" in sheet
    csv = tw.sheet_csv(ws)
    assert "Anlage N,Bruttoarbeitslohn" in csv


# ---------------------------------------------------------------- API, routines, proposals, MCP
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "appdata"))
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "data"), "name": "T", "countries": ["DE", "IN"], "base_currency": "EUR",
                                        "answers": {"in_nri": True, "de_joint": False}}).status_code == 200
    c.post("/config", json={"fx": {"source": "manual", "manual_rates": {"INR": 100}}})
    eur = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 20000, "liquid": 1}).json()["id"]
    inr = c.post("/api/accounts", json={"name": "NRE", "country": "IN", "currency": "INR", "opening_balance": 10000, "liquid": 1}).json()["id"]
    c.post("/api/planned", json={"date": (date.today() + timedelta(days=75)).isoformat(), "kind": "expense", "account_id": inr, "amount": 500000,
                                 "note": "Stage payment", "confidence": "known"})
    c.post("/api/goals", json={"name": "Uni", "target_today": 40000, "target_date": "2038-09-01", "saved": 1000, "monthly": 100})
    c.eur, c.inr = eur, inr
    return c


def test_api_screens_answer(client):
    h = client.get("/home").json()
    assert h["attention"] and h["attention"][0]["ccy"] == "INR" and h["goals"][0]["name"] == "Uni"
    f = client.get("/forecast?scenario=salary_late").json()
    assert f["scenario"] == "salary_late" and f["plan"] and f["accounts"]
    r = client.post("/forecast/floors", json={"INR": 20000}).json()
    assert r["floors"]["INR"] == 20000
    assert client.post("/forecast/floors", json={"inr; drop": 1}).status_code == 400
    o = client.get("/plan/odds").json()
    assert o["goals"][0]["probability"] <= 1 and len(o["whatif"]) == 5
    t = client.post("/plan/odds/try", json={"goal_id": o["goals"][0]["id"], "monthly": 900}).json()
    assert t["probability"] >= o["goals"][0]["probability"]
    d = client.post("/diversify/settings", json={"targets": {"shares": 50, "cash": 20}, "monthly_investable": 500}).json()
    assert any(x["key"] == "shares" for x in d["targets"])
    assert client.post("/diversify/settings", json={"targets": {"shares": 90, "cash": 20}}).status_code == 400
    assert "cards" in client.get("/opportunities").json()
    ws = client.get("/taxws?country=DE").json()
    assert ws["country"] == "DE" and len(ws["available"]) == 2
    ws = client.post("/taxws/answers", json={"country": "DE", "year": ws["year"], "answers": {"gross": 50000, "lohnsteuer": 8000}}).json()
    assert next(q for q in ws["questions"] if q["id"] == "gross")["value"] == 50000 and ws["estimate"]
    csv = client.get(f"/taxws/export?country=DE&year={ws['year']}&fmt=csv")
    assert csv.status_code == 200 and "Bruttoarbeitslohn" in csv.text
    assert client.post("/taxws/ask", json={"country": "DE", "year": ws["year"]}).status_code == 400   # no AI connected: clear message


def test_routines_proposals_and_audit(client):
    r = client.post("/routines/run", json={"id": "all"}).json()
    assert {x["routine"] for x in r["ran"]} >= {"forecast_refresh", "monthly_review", "deadline_sweep"}
    assert all(x["status"] == "ok" for x in r["ran"]), r["ran"]
    again = client.post("/routines/run", json={"id": "all"}).json()
    assert again["ran"] == []                                  # nothing due twice in a day
    prop = next(p for p in r["proposals"] if p["key"].startswith("transfer:EUR:INR"))
    assert prop["status"] == "pending"
    before = client.get("/forecast").json()
    ok = client.post(f"/proposals/{prop['id']}", json={"decision": "approve"}).json()
    assert ok["ok"] and "planned item" in ok["result"]
    after = client.get("/forecast").json()
    assert not after["plan"] and before["plan"]                 # the approved transfer now covers the payment
    assert client.post(f"/proposals/{prop['id']}", json={"decision": "approve"}).status_code == 400
    audit = client.get("/routines").json()["audit"]
    assert any(a["action"].startswith("Approved:") for a in audit) and any(a["action"] == "Ran Forecast refresh" for a in audit)
    s = client.post("/routines/settings", json={"enabled": {"monthly_review": False}, "ai_summary": False}).json()
    assert not next(x for x in s["routines"] if x["id"] == "monthly_review")["enabled"] and not s["ai_summary"]


def test_mcp_server_over_stdio(client, tmp_path):
    from aaryaai_finance.mcp_server import Server
    srv = Server(tmp_path / "data")
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "Claude Desktop"}}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "cash_forecast", "arguments": {}}},
             {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "propose_transaction", "arguments": {"account": "Giro", "kind": "expense", "amount": 42.5, "note": "Books"}}},
             {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "propose_transaction", "arguments": {"account": "Nope", "kind": "expense", "amount": 1}}},
             {"jsonrpc": "2.0", "id": 6, "method": "nope"}]
    out = io.StringIO()
    srv.serve(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\nnot json\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, 3, 4, 5, 6, None]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert {t["name"] for t in replies[1]["result"]["tools"]} >= {"get_snapshot", "cash_forecast", "tax_status", "propose_transaction"}
    fc_ = json.loads(replies[2]["result"]["content"][0]["text"])
    assert fc_["plan"] and "month_end" in fc_
    assert "waiting" in replies[3]["result"]["content"][0]["text"]
    assert replies[4]["result"]["isError"]
    assert replies[5]["error"]["code"] == -32601 and replies[6]["error"]["code"] == -32700
    props = client.get("/routines").json()["proposals"]
    p = next(x for x in props if x["key"].startswith("mcp:transaction"))
    assert p["source"] == "MCP · Claude Desktop" and p["status"] == "pending"
    tx_before = len(client.get("/api/transactions").json())
    client.post(f"/proposals/{p['id']}", json={"decision": "approve"})
    assert len(client.get("/api/transactions").json()) == tx_before + 1
    assert any(a["actor"] == "MCP · Claude Desktop" for a in client.get("/routines").json()["audit"])


# ---------------------------------------------------------------- automatic MCP setup
def _mcp_env(tmp_path, monkeypatch):
    from aaryaai_finance import mcp_setup as ms
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("AARYAAI_FAKE_HOME", str(tmp_path / "home"))
    return ms


def test_mcp_setup_merges_backs_up_and_detects(tmp_path, monkeypatch):
    ms = _mcp_env(tmp_path, monkeypatch)
    data = tmp_path / "data"
    with pytest.raises(ValueError, match="installed"):
        ms.install("claude", data, platform="linux")
    cfg = tmp_path / "cfg" / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    assert next(s for s in ms.status(data, platform="linux") if s["id"] == "claude")["state"] == "not_connected"
    r = ms.install("claude", data, python="/py", platform="linux")
    d = json.loads(cfg.read_text())
    assert d["theme"] == "dark" and d["mcpServers"]["other"] == {"command": "x"}
    assert d["mcpServers"]["aaryaai-finance"] == {"command": "/py", "args": ["-m", "aaryaai_finance", "mcp", "--data-dir", str(data.resolve())]}
    assert r["written"][0]["backup"] and json.loads(Path(r["written"][0]["backup"]).read_text())["mcpServers"] == {"other": {"command": "x"}}
    assert next(s for s in ms.status(data, python="/py", platform="linux") if s["id"] == "claude")["state"] == "connected"
    assert next(s for s in ms.status(tmp_path / "other", python="/py", platform="linux") if s["id"] == "claude")["state"] == "outdated"
    ms.uninstall("claude", platform="linux")
    assert "aaryaai-finance" not in json.loads(cfg.read_text())["mcpServers"]
    backups = sorted(cfg.parent.glob("claude_desktop_config.json.bak-*"))
    assert len(backups) == 2 and json.loads(backups[0].read_text())["mcpServers"] == {"other": {"command": "x"}}   # same second: both kept
    assert next(s for s in ms.status(data, platform="linux") if s["id"] == "vscode")["state"] == "not_found"


def test_mcp_setup_vscode_with_comments_and_broken_files(tmp_path, monkeypatch):
    ms = _mcp_env(tmp_path, monkeypatch)
    p = tmp_path / "cfg" / "Code" / "User" / "mcp.json"
    p.parent.mkdir(parents=True)
    original = '{\n  // my servers\n  "servers": {"gh": {"type": "http", "url": "https://x/y//z"},},\n  /* inputs */ "inputs": []\n}\n'
    p.write_text(original)
    r = ms.install("vscode", tmp_path / "data", python="/py", platform="linux")
    d = json.loads(p.read_text())
    assert d["servers"]["gh"]["url"] == "https://x/y//z" and d["servers"]["aaryaai-finance"]["type"] == "stdio"
    assert r["written"][0]["comments_removed"] and Path(r["written"][0]["backup"]).read_text() == original
    p.write_text("{ not json")
    with pytest.raises(ValueError, match="not changed"):
        ms.install("vscode", tmp_path / "data", platform="linux")
    assert p.read_text() == "{ not json"
    assert next(s for s in ms.status(tmp_path / "data", platform="linux") if s["id"] == "vscode")["state"] == "unreadable"


def test_mcp_setup_windows_store_claude(tmp_path, monkeypatch):
    ms = _mcp_env(tmp_path, monkeypatch)
    (tmp_path / "roaming" / "Claude").mkdir(parents=True)
    store = tmp_path / "local" / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    r = ms.install("claude", tmp_path / "data", python="C:\\py.exe", platform="win32")
    assert len(r["written"]) == 2 and (store / "claude_desktop_config.json").exists()


def test_mcp_connect_api_and_cli(client, tmp_path, capsys):
    from aaryaai_finance.cli import main
    (tmp_path / "appdata" / "Claude").mkdir(parents=True, exist_ok=True)
    clients = {c["id"]: c for c in client.get("/mcp/clients").json()["clients"]}
    assert clients["claude"]["installed"] and clients["claude"]["state"] == "not_connected"
    r = client.post("/mcp/connect", json={"client": "claude"}).json()
    assert r["written"] and next(c for c in r["clients"] if c["id"] == "claude")["state"] == "connected"
    assert client.post("/mcp/connect", json={"client": "nope"}).status_code == 400
    assert client.post("/mcp/connect", json={"client": "vscode"}).status_code == 400          # not installed: clear message
    assert any(a["action"].startswith("Connected Claude Desktop") for a in client.get("/routines").json()["audit"])
    assert client.post("/mcp/connect", json={"client": "claude", "remove": True}).json()["removed"]
    with pytest.raises(SystemExit) as ex:
        main(["mcp", "--setup", "all", "--status", "--data-dir", str(tmp_path / "data")])
    assert ex.value.code == 0
    out = capsys.readouterr().out
    assert "Claude Desktop: connected in" in out and "connected" in out


def test_wizard_can_connect_mcp_apps(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "appdata"))
    (tmp_path / "appdata" / "Claude").mkdir(parents=True)
    c = local_client(create_app(tmp_path / "boot"))
    assert [x["id"] for x in c.get("/setup/options").json()["mcp_clients"]] == ["claude"]
    r = c.post("/setup/apply", json={"data_dir": str(tmp_path / "data"), "countries": ["DE"], "mcp_clients": ["claude", "vscode"]}).json()
    assert [m["ok"] for m in r["mcp"]] == [True, False]
    cfg = json.loads((tmp_path / "appdata" / "Claude" / "claude_desktop_config.json").read_text())
    assert cfg["mcpServers"]["aaryaai-finance"]["args"][-1] == str((tmp_path / "data").resolve())


def test_web_scripts_parse():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    web = Path(__file__).resolve().parents[1] / "aaryaai_finance" / "web"
    for f in ("app.js", "planning.js"):
        r = subprocess.run([node, "--check", str(web / f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_settings_are_isolated():
    from aaryaai_finance import mcp_setup as ms
    import os
    for client in ms.CLIENTS:
        for plat in ("win32", "darwin", "linux"):
            for p in ms.config_paths(client, plat):
                assert "isolated-home" in str(p), p
    assert "isolated-home" in os.environ["LOCALAPPDATA"]


def test_mcp_server_output_survives_a_non_utf8_console(client, tmp_path):
    """Windows pipes default to cp1252; tool results contain €, ₹ and →. Output must still be written and parse."""
    from aaryaai_finance.mcp_server import Server
    raw = io.BytesIO()
    out = io.TextIOWrapper(raw, encoding="cp1252", newline="\n")
    inp = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
                      + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "cash_forecast", "arguments": {}}}) + "\n")
    Server(tmp_path / "data").serve(inp, out)
    out.flush()
    lines = raw.getvalue().decode("ascii").splitlines()
    assert len(lines) == 2 and "→" in json.dumps(json.loads(lines[0]), ensure_ascii=False) + "→"
    assert json.loads(json.loads(lines[1])["result"]["content"][0]["text"])["base"] == "EUR"
