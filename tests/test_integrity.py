"""Data integrity: proposals apply once, backups are consistent and bounded, temporary uploads don't pile up."""
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aaryaai_finance import model as M  # noqa: E402
from aaryaai_finance.server import create_app  # noqa: E402
from conftest import local_client  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    c = local_client(create_app(tmp_path / "boot"))
    assert c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"}).status_code == 200
    c.ctx = c.app.state.get_ctx
    c.acc = c.post("/api/accounts", json={"name": "Giro", "country": "DE", "currency": "EUR", "opening_balance": 100, "liquid": 1}).json()["id"]
    return c


def test_a_proposal_is_applied_only_once(client):
    ctx = client.ctx()
    pid = ctx.propose("t:1", "test", "Expense", action={"type": "add_transaction", "row": {
        "date": "2026-01-02", "kind": "expense", "account_id": client.acc, "amount": 5}})
    assert ctx.decide(pid, "approve")["ok"]
    with pytest.raises(ValueError):
        ctx.decide(pid, "approve")
    assert len(client.get("/api/transactions").json()) == 1


def test_a_failed_approval_leaves_the_proposal_waiting(client):
    ctx = client.ctx()
    pid = ctx.propose("t:2", "test", "Save more", action={"type": "set_goal_monthly", "goal_id": 999, "monthly": 50})
    with pytest.raises(ValueError):
        ctx.decide(pid, "approve")
    p = ctx.db.get("proposals", pid)
    assert p["status"] == "pending" and not p["decided"]
    assert ctx.decide(pid, "skip")["ok"] and ctx.db.get("proposals", pid)["status"] == "skipped"


def test_connections_are_closed_after_use(client):
    with client.ctx().db.conn() as c:
        c.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        c.execute("SELECT 1")


def test_backup_copy_is_a_readable_database(tmp_path):
    src = tmp_path / "a.db"
    con = sqlite3.connect(src); con.execute("CREATE TABLE t (x)"); con.execute("INSERT INTO t VALUES (42)"); con.commit()
    out = M.backup_copy(src, tmp_path / "backups" / "finance-before-test.db")
    con.close()
    assert sqlite3.connect(out).execute("SELECT x FROM t").fetchone() == (42,)


def test_old_backups_are_pruned_but_recent_and_newest_kept(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    now = time.time()
    for i in range(25):                                      # 25 backups, a day apart, 40-64 days old
        f = d / f"finance-before-schema-{i:02d}.db"
        f.write_text("x")
        os.utime(f, (now - (40 + i) * 86400,) * 2)
    for i in range(3):                                       # 3 from this week
        f = d / f"finance-before-import-new{i}.db"
        f.write_text("x")
    (d / "my-own-copy.db").write_text("x")                   # not the app's: never touched
    gone = M.prune_backups(d)
    left = sorted(p.name for p in d.iterdir())
    assert len(gone) == 8 and "my-own-copy.db" in left
    assert all(f"finance-before-import-new{i}.db" in left for i in range(3))
    assert len([n for n in left if n.startswith("finance-before-")]) == 20


def test_unfiled_uploads_are_removed_after_a_week(tmp_path):
    from aaryaai_finance.config import Settings
    from aaryaai_finance.context import Ctx
    s = Settings(tmp_path / "d")
    s.inbox_dir.mkdir(parents=True)
    old, new = s.inbox_dir / ("a" * 64 + ".pdf"), s.inbox_dir / ("b" * 64 + ".pdf")
    old.write_bytes(b"%PDF"); new.write_bytes(b"%PDF")
    os.utime(old, (time.time() - 8 * 86400,) * 2)
    Ctx(s)
    assert not old.exists() and new.exists()


def test_mcp_repeats_a_decided_transaction_as_a_new_proposal(client, tmp_path):
    from aaryaai_finance.mcp_server import Server
    srv = Server(tmp_path / "d")
    args = {"account": "Giro", "kind": "expense", "amount": 9.5, "date": "2026-02-01", "note": "Lunch"}
    first = srv.call("propose_transaction", args)
    assert srv.call("propose_transaction", args)["proposal_id"] == first["proposal_id"]      # a retry: same proposal
    srv.ctx.decide(first["proposal_id"], "approve")
    second = srv.call("propose_transaction", args)                                          # the same lunch again: new
    assert second["proposal_id"] and second["proposal_id"] != first["proposal_id"]
