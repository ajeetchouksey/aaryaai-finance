"""SQLite storage. One file (data/finance.db) next to the app — never leaves your PC."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('asset','liability')),
  category TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT 'EUR',
  liquid INTEGER NOT NULL DEFAULT 0, country TEXT DEFAULT 'DE', note TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS holdings (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, ticker TEXT, asset_type TEXT DEFAULT 'ETF',
  country TEXT DEFAULT 'DE', account TEXT, qty REAL DEFAULT 0, avg_cost REAL DEFAULT 0,
  currency TEXT DEFAULT 'EUR', last_price REAL, price_date TEXT);
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, target_today REAL NOT NULL, currency TEXT DEFAULT 'EUR',
  target_date TEXT NOT NULL, saved REAL DEFAULT 0, monthly REAL DEFAULT 0,
  annual_return REAL DEFAULT 0.05, inflation REAL DEFAULT 0.02, priority INTEGER DEFAULT 2, note TEXT);
CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY, category TEXT NOT NULL, amount REAL NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, ticker TEXT NOT NULL, side TEXT NOT NULL CHECK(side IN ('buy','sell')),
  qty REAL NOT NULL, price REAL NOT NULL, fee REAL DEFAULT 1.0, note TEXT);
CREATE TABLE IF NOT EXISTS calendar (
  id INTEGER PRIMARY KEY, due TEXT, country TEXT, title TEXT NOT NULL, detail TEXT,
  severity TEXT DEFAULT 'normal', status TEXT DEFAULT 'open', source TEXT, key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS chat_messages (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, role TEXT, content TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, institution TEXT, country TEXT NOT NULL DEFAULT 'DE',
  currency TEXT NOT NULL DEFAULT 'EUR', type TEXT DEFAULT 'Current account', opening_balance REAL DEFAULT 0,
  opening_date TEXT, liquid INTEGER DEFAULT 1, in_networth INTEGER DEFAULT 1, archived INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, account_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('income','expense','transfer')),
  amount REAL NOT NULL, category TEXT, note TEXT, to_account_id INTEGER, to_amount REAL,
  recurring_id INTEGER, doc_id INTEGER, created TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS tx_recur_once ON transactions(recurring_id, date) WHERE recurring_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS recurring (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, account_id INTEGER NOT NULL, amount REAL NOT NULL, category TEXT, note TEXT,
  frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly','quarterly','yearly')),
  start_date TEXT NOT NULL, end_date TEXT, to_account_id INTEGER, to_amount REAL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE, original_name TEXT, stored_path TEXT, doc_type TEXT, category TEXT,
  country TEXT, doc_date TEXT, amount REAL, currency TEXT, fields TEXT, text_excerpt TEXT, confidence REAL,
  status TEXT DEFAULT 'filed', added TEXT);
CREATE TABLE IF NOT EXISTS snapshots (day TEXT PRIMARY KEY, net_worth_eur REAL, assets_eur REAL, liabilities_eur REAL);
"""

TABLES = {
    "items": ["name", "kind", "category", "amount", "currency", "liquid", "country", "note", "updated"],
    "holdings": ["name", "ticker", "asset_type", "country", "account", "qty", "avg_cost", "currency", "last_price", "price_date"],
    "goals": ["name", "target_today", "currency", "target_date", "saved", "monthly", "annual_return", "inflation", "priority", "note"],
    "expenses": ["category", "amount", "note"],
    "paper_trades": ["ts", "ticker", "side", "qty", "price", "fee", "note"],
    "calendar": ["due", "country", "title", "detail", "severity", "status", "source", "key"],
    "accounts": ["name", "institution", "country", "currency", "type", "opening_balance", "opening_date", "liquid", "in_networth", "archived", "note"],
    "transactions": ["date", "account_id", "kind", "amount", "category", "note", "to_account_id", "to_amount", "recurring_id", "doc_id", "created"],
    "recurring": ["kind", "account_id", "amount", "category", "note", "frequency", "start_date", "end_date", "to_account_id", "to_amount", "active"],
    "documents": ["sha256", "original_name", "stored_path", "doc_type", "category", "country", "doc_date", "amount", "currency", "fields", "text_excerpt", "confidence", "status", "added"],
}

DEFAULT_SETTINGS = {"paper_starting_cash": "10000"}


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.conn() as c:
            c.executescript(SCHEMA)
            for k, v in DEFAULT_SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    # settings
    def settings(self) -> dict:
        with self.conn() as c:
            return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}

    def set_setting(self, key: str, value) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))

    # generic CRUD
    def list(self, table: str, order: str = "id") -> list[dict]:
        assert table in TABLES
        with self.conn() as c:
            return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def upsert(self, table: str, row: dict) -> int:
        assert table in TABLES
        cols = [k for k in TABLES[table] if k in row]
        vals = [row[k] for k in cols]
        with self.conn() as c:
            if row.get("id"):
                c.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*vals, row["id"]))
                return int(row["id"])
            cur = c.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
            return int(cur.lastrowid)

    def delete(self, table: str, row_id: int) -> None:
        assert table in TABLES
        with self.conn() as c:
            c.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))

    def seed_calendar(self, entries: list[dict]) -> None:
        """Insert seed items once (by key); never overwrite a status you changed."""
        with self.conn() as c:
            for e in entries:
                c.execute("INSERT OR IGNORE INTO calendar (due,country,title,detail,severity,status,source,key) "
                          "VALUES (?,?,?,?,?,?,?,?)",
                          (e.get("due"), e["country"], e["title"], e.get("detail"), e.get("severity", "normal"),
                           "open", e.get("source"), e["key"]))

    def seed_once(self, flag: str, fn) -> None:
        s = self.settings()
        if s.get(flag) != "1":
            fn(self)
            self.set_setting(flag, "1")

    def snapshot(self, nw: dict) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                      (date.today().isoformat(), nw["net_worth_eur"], nw["assets_eur"], nw["liabilities_eur"]))

    # chats
    def chat_create(self, title: str) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as c:
            return int(c.execute("INSERT INTO chats (title, created, updated) VALUES (?,?,?)", (title, now, now)).lastrowid)

    def chat_list(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM chats ORDER BY updated DESC")]

    def chat_history(self, chat_id: int) -> list[dict]:
        with self.conn() as c:
            return [{"role": r["role"], "content": json.loads(r["content"])}
                    for r in c.execute("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id", (chat_id,))]

    def chat_append(self, chat_id: int, msg: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as c:
            c.execute("INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?,?,?,?)",
                      (chat_id, msg["role"], json.dumps(msg["content"], ensure_ascii=False), now))
            c.execute("UPDATE chats SET updated=? WHERE id=?", (now, chat_id))

    def chat_delete(self, chat_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM chat_messages WHERE chat_id=?", (chat_id,))
            c.execute("DELETE FROM chats WHERE id=?", (chat_id,))

    def chat_rename(self, chat_id: int, title: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE chats SET title=? WHERE id=?", (title, chat_id))

    def snapshots(self) -> list[dict]:
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM snapshots ORDER BY day")]
