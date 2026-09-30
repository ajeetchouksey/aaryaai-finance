"""The JSON data model: generation, extensions, migration, relations, export/import."""
import json
import sqlite3
from pathlib import Path

import pytest

from aaryaai_finance import model as M
from aaryaai_finance.core.db import DB, IntegrityProblem

V1_SCHEMA = """
CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, institution TEXT, country TEXT NOT NULL DEFAULT 'DE',
  currency TEXT NOT NULL DEFAULT 'EUR', type TEXT DEFAULT 'Current account', opening_balance REAL DEFAULT 0,
  opening_date TEXT, liquid INTEGER DEFAULT 1, in_networth INTEGER DEFAULT 1, archived INTEGER DEFAULT 0, note TEXT, legacy_col TEXT);
CREATE TABLE transactions (id INTEGER PRIMARY KEY, date TEXT NOT NULL, account_id INTEGER NOT NULL, kind TEXT NOT NULL,
  amount REAL NOT NULL, category TEXT, note TEXT, to_account_id INTEGER, to_amount REAL, recurring_id INTEGER, doc_id INTEGER, created TEXT);
CREATE TABLE snapshots (day TEXT PRIMARY KEY, net_worth_eur REAL, assets_eur REAL, liabilities_eur REAL);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
"""


def test_core_model_is_valid_and_generates_sql():
    model, errs = M.build()
    assert errs == []
    sql = M.table_sql("transactions", model["entities"]["transactions"])
    assert "REFERENCES accounts(id) ON DELETE RESTRICT" in sql
    assert "REFERENCES recurring(id) ON DELETE SET NULL" in sql
    assert "CHECK(kind IN ('income','expense','transfer'))" in sql


def test_bad_extensions_are_reported_not_fatal():
    model, errs = M.build([("Test pack", {"extends": {"accounts": {"fields": {
        "ok_field": {"type": "text"}, "Bad Name": {"type": "text"}, "odd": {"type": "blob"}, "name": {"type": "text"}}},
        "nope": {"fields": {"x": {"type": "text"}}}},
        "entities": {"accounts": {"fields": {"a": {"type": "text"}}}, "policies": {"fields": {"acct": {"type": "ref", "to": "ghost"}}}}})])
    assert "ok_field" in model["entities"]["accounts"]["fields"]
    joined = " | ".join(errs)
    for bit in ("invalid field name", "unknown type 'blob'", "accounts.name already exists", "unknown entity 'nope'",
                "'accounts' is taken", "unknown entity 'ghost'"):
        assert bit in joined, bit
    assert "policies" not in model["entities"]


def test_migrates_v1_database_without_losing_data(tmp_path):
    p = tmp_path / "finance.db"
    c = sqlite3.connect(p)
    c.executescript(V1_SCHEMA)
    c.execute("INSERT INTO accounts (id,name,legacy_col) VALUES (1,'Giro','keep me')")
    c.execute("INSERT INTO transactions (date,account_id,kind,amount) VALUES ('2026-01-01',1,'income',10)")
    c.execute("INSERT INTO transactions (date,account_id,kind,amount) VALUES ('2026-01-02',42,'expense',5)")   # orphan
    c.execute("INSERT INTO transactions (date,account_id,kind,amount,recurring_id) VALUES ('2026-01-03',1,'expense',1,9)")
    c.execute("INSERT INTO snapshots VALUES ('2026-01-01', 100, 120, 20)")
    c.commit(); c.close()

    db = DB(p, backup_dir=tmp_path / "backups")
    r = db.sync_report
    assert "accounts" in r["rebuilt"] and "transactions" in r["rebuilt"] and "recurring" in r["created"]
    assert r["backup"] and Path(r["backup"]).exists()
    assert len(r["repaired"]) == 2
    assert db.list("snapshots")[0]["net_worth"] == 100
    txs = db.list("transactions")
    assert len(txs) == 3 and txs[2]["recurring_id"] is None
    recovered = [a for a in db.list("accounts") if a["id"] == txs[1]["account_id"]][0]
    assert recovered["archived"] == 1 and "Recovered" in recovered["name"]
    extra = json.loads(sqlite3.connect(p).execute("SELECT extra FROM accounts WHERE id=1").fetchone()[0])
    assert extra["_legacy"]["legacy_col"] == "keep me"          # dropped columns are kept, not lost
    assert DB(p, backup_dir=tmp_path / "backups").sync_report == {"created": [], "rebuilt": [], "backup": None, "repaired": [], "changed": []}
    assert sqlite3.connect(p).execute("PRAGMA user_version").fetchone()[0] == M.CORE["version"]


def test_relations_are_enforced(tmp_path):
    db = DB(tmp_path / "f.db")
    a = db.upsert("accounts", {"name": "Giro", "currency": "EUR"})
    db.upsert("transactions", {"date": "2026-01-01", "account_id": a, "kind": "income", "amount": 5})
    with pytest.raises(IntegrityProblem, match="still used by"):
        db.delete("accounts", a)
    with pytest.raises(IntegrityProblem, match="doesn't exist"):
        db.upsert("transactions", {"date": "2026-01-01", "account_id": 999, "kind": "income", "amount": 5})
    with pytest.raises(IntegrityProblem, match="Kind must be one of"):
        db.upsert("transactions", {"date": "2026-01-01", "account_id": a, "kind": "gift", "amount": 5})
    with pytest.raises(IntegrityProblem, match="YYYY-MM-DD"):
        db.upsert("transactions", {"date": "1st Jan", "account_id": a, "kind": "income", "amount": 5})
    with pytest.raises(IntegrityProblem, match="3-letter"):
        db.upsert("accounts", {"name": "x", "currency": "euro"})
    c = db.conn().execute("PRAGMA foreign_keys").fetchone()[0]
    assert c == 1


def test_custom_fields_and_user_entities(tmp_path):
    model, errs = M.build(user_model={
        "extends": {"accounts": {"fields": {"iban_last4": {"type": "text", "label": "IBAN (last 4)"}}}},
        "entities": {"policies": {"label": "Insurance policy", "fields": {
            "name": {"type": "text", "required": True}, "premium": {"type": "money"},
            "account_id": {"type": "ref", "to": "accounts", "on_delete": "set_null"}}}}})
    assert errs == []
    db = DB(tmp_path / "f.db", model)
    a = db.upsert("accounts", {"name": "Giro", "iban_last4": "1234"})
    assert db.get("accounts", a)["iban_last4"] == "1234"
    db.upsert("accounts", {"id": a, "note": "main"})                      # partial update keeps custom field
    assert db.get("accounts", a)["iban_last4"] == "1234"
    pid = db.upsert("policies", {"name": "Haftpflicht", "premium": 60, "account_id": a})
    assert db.get("policies", pid)["premium"] == 60
    assert "policies" in db.tables


def test_export_import_roundtrip_and_rejects_broken_links(tmp_path):
    db = DB(tmp_path / "a.db")
    a = db.upsert("accounts", {"name": "Giro"})
    db.upsert("transactions", {"date": "2026-02-01", "account_id": a, "kind": "expense", "amount": 3})
    dump = json.loads(json.dumps(db.export()))
    db2 = DB(tmp_path / "b.db")
    db2.upsert("accounts", {"name": "will be replaced"})
    counts = db2.import_all(dump)
    assert counts["transactions"] == 1 and [x["name"] for x in db2.list("accounts")] == ["Giro"]
    dump["tables"]["transactions"][0]["account_id"] = 77
    with pytest.raises(IntegrityProblem, match="broken links"):
        db2.import_all(dump)
    assert [x["name"] for x in db2.list("accounts")] == ["Giro"]        # unchanged after a failed import
    with pytest.raises(IntegrityProblem):
        db2.import_all({"hello": 1})


def test_model_api(tmp_path):
    from aaryaai_finance.server import create_app
    from conftest import local_client
    cl = local_client(create_app(tmp_path / "data"))
    cl.post("/setup/apply", json={"data_dir": str(tmp_path / "data"), "countries": ["IN"], "base_currency": "EUR"})
    m = cl.get("/model").json()
    assert m["entities"]["accounts"]["fields"]["in_account_kind"]["custom"] is True
    r = cl.post("/model/user", json={"text": '{"extends": {"goals": {"fields": {"owner": {"type": "text"}}}}}'})
    assert r.status_code == 200, r.text
    assert "owner" in cl.get("/model").json()["entities"]["goals"]["fields"]
    assert cl.post("/model/user", json={"text": '{"extends": {"goals": {"fields": {"x": {"type": "nope"}}}}}'}).status_code == 400
    a = cl.post("/api/accounts", json={"name": "Giro", "currency": "EUR"}).json()["id"]
    cl.post("/api/transactions", json={"date": "2026-01-01", "account_id": a, "kind": "income", "amount": 1})
    r = cl.delete(f"/api/accounts/{a}")
    assert r.status_code == 400 and "Archive it instead" in r.json()["detail"]
    exp = cl.get("/data/export")
    assert exp.status_code == 200 and exp.json()["format"] == "aaryaai-finance"
    assert cl.post("/data/import", json={"data": exp.json()}).status_code == 400          # needs confirm
    assert cl.post("/data/import", json={"data": exp.json(), "confirm": "REPLACE"}).json()["ok"]


def test_migration_never_silently_changes_values(tmp_path):
    """Review finding: an unexpected enum value used to become values[0] (an expense turning into income)."""
    p = tmp_path / "finance.db"
    c = sqlite3.connect(p)
    c.executescript(V1_SCHEMA)
    c.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, category TEXT, amount REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'EUR', liquid INTEGER DEFAULT 0, country TEXT, note TEXT, updated TEXT)")
    c.execute("INSERT INTO accounts (id,name) VALUES (1,'Giro')")
    c.execute("INSERT INTO transactions (date,account_id,kind,amount) VALUES ('2026-01-01',1,'Expense',900)")   # wrong case
    c.execute("INSERT INTO transactions (date,account_id,kind,amount) VALUES ('2026-01-02',1,'refund',50)")     # unknown
    c.execute("INSERT INTO items (name,kind,category,amount) VALUES ('Car','asset',NULL,1000)")                 # NULL in a now-required column
    c.commit(); c.close()
    db = DB(p, backup_dir=tmp_path / "b")
    kinds = [t["kind"] for t in db.list("transactions")]
    assert kinds[0] == "expense"                                                   # case fixed, meaning kept
    raw = sqlite3.connect(p).execute("SELECT extra FROM transactions WHERE amount=50").fetchone()[0]
    assert json.loads(raw)["_legacy"]["kind"] == "refund"                          # original kept, not lost
    assert any("not in" in n for n in db.sync_report["changed"]) and any("empty value" in n for n in db.sync_report["changed"])
    assert db.list("items")[0]["category"] == "(missing)"


def test_bad_user_model_is_refused_before_saving_and_never_bricks_start(tmp_path, monkeypatch):
    """Review finding: making a field required over existing empty values broke every start."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "ad"))
    from aaryaai_finance.server import create_app
    from conftest import local_client
    data = tmp_path / "data"
    cl = local_client(create_app(data))
    cl.post("/setup/apply", json={"data_dir": str(data), "countries": ["DE"], "base_currency": "EUR"})
    m1 = '{"entities": {"pol": {"label": "Policy", "fields": {"name": {"type": "text"}, "premium": {"type": "money"}}}}}'
    assert cl.post("/model/user", json={"text": m1}).status_code == 200
    cl.post("/api/pol", json={"name": "A"})                                        # premium empty
    m2 = m1.replace('"premium": {"type": "money"}', '"premium": {"type": "money", "required": true}')
    r = cl.post("/model/user", json={"text": m2})
    assert r.status_code == 200, r.text                                            # empty values get a placeholder, reported
    assert any("empty value" in n for n in r.json()["sync"]["changed"])
    m3 = m1.replace('"name": {"type": "text"}', '"name": {"type": "text", "unique": true}')
    assert cl.post("/api/pol", json={"name": "A", "premium": 5}).status_code == 200
    r = cl.post("/model/user", json={"text": m3})                                  # duplicates can't become unique
    assert r.status_code == 400 and "nothing was changed" in r.json()["detail"]
    assert "unique" not in (data / "model.json").read_text()                        # file untouched
    (data / "model.json").write_text(m3)                                           # even if written by hand…
    c2 = local_client(create_app(data))                                            # …the app still starts
    info = c2.get("/model").json()
    assert any("model.json" in e for e in info["errors"])


def test_outside_models_cannot_inject_sql_or_keys(tmp_path):
    model, errs = M.build(user_model={"entities": {"x": {"label": "X", "primary_key": "name", "system": True,
        "indexes": [{"name": "i", "columns": ["name"], "where": "1) ; DROP TABLE accounts; --"}],
        "fields": {"name": {"type": "text"}, "k": {"type": "enum", "values": ["O'Neil", "b"], "required": True}}}}})
    assert errs == []
    e = model["entities"]["x"]
    assert "indexes" not in e and "primary_key" not in e and not e.get("system")
    db = DB(tmp_path / "f.db", model)
    db.upsert("x", {"name": "a", "k": "O'Neil"})
    assert db.list("x")[0]["k"] == "O'Neil" and db.list("accounts") == []


def test_import_validates_rows_and_keeps_tables_not_in_the_file(tmp_path):
    model, _ = M.build(user_model={"entities": {"pol": {"label": "Policy", "fields": {"name": {"type": "text"}}}}})
    db = DB(tmp_path / "a.db", model)
    db.upsert("pol", {"name": "keep me"})
    a = db.upsert("accounts", {"name": "Giro"})
    dump = db.export()
    del dump["tables"]["pol"]                                   # an older export without this record type
    db.import_all(dump)
    assert [p["name"] for p in db.list("pol")] == ["keep me"]
    dump["tables"]["transactions"] = [{"id": 1, "date": "not-a-date", "account_id": a, "kind": "income", "amount": "lots"}]
    with pytest.raises(IntegrityProblem, match="aren't valid"):
        db.import_all(dump)


def test_export_includes_tables_the_current_model_does_not_know(tmp_path):
    model, _ = M.build(user_model={"entities": {"pol": {"label": "Policy", "fields": {"name": {"type": "text"}}}}})
    DB(tmp_path / "a.db", model).upsert("pol", {"name": "Haftpflicht"})
    dump = DB(tmp_path / "a.db").export()                 # core model only, as when model.json is being ignored
    assert dump["tables"]["pol"][0]["name"] == "Haftpflicht" and dump["unmanaged_tables"] == ["pol"]
