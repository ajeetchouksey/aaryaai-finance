"""SQLite storage, generated from the JSON model (aaryaai_finance/model). One file in your data folder."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from .. import model as M

DEFAULT_SETTINGS = {"paper_starting_cash": "10000"}


class IntegrityProblem(ValueError):
    """A save/delete that would break a relation (e.g. deleting an account that still has transactions)."""


class DB:
    def __init__(self, path: Path, model: dict | None = None, backup_dir: Path | None = None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.model = model or M.build()[0]
        self.sync_report = M.sync(path, self.model, backup_dir)
        with self.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            for k, v in DEFAULT_SETTINGS.items():
                c.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))

    def conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @property
    def tables(self) -> dict:
        """Editable entities -> spec (system tables like chats/snapshots are excluded)."""
        return {k: v for k, v in self.model["entities"].items() if not v.get("system")}

    # settings
    def settings(self) -> dict:
        with self.conn() as c:
            return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}

    def set_setting(self, key: str, value) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))

    # generic CRUD — every row is checked against the model
    def _spec(self, table: str) -> dict:
        if table not in self.model["entities"]:
            raise KeyError(table)
        return self.model["entities"][table]

    @staticmethod
    def _flatten(r: sqlite3.Row) -> dict:
        d = dict(r)
        ex = d.pop("extra", None)
        if ex:
            try:
                for k, v in json.loads(ex).items():
                    if not k.startswith("_"):
                        d.setdefault(k, v)
            except ValueError:
                pass
        return d

    def list(self, table: str, order: str | None = None) -> list[dict]:
        spec = self._spec(table)
        order = order or spec.get("primary_key") or "id"
        with self.conn() as c:
            return [self._flatten(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def get(self, table: str, row_id) -> dict | None:
        spec = self._spec(table)
        with self.conn() as c:
            r = c.execute(f"SELECT * FROM {table} WHERE {spec.get('primary_key') or 'id'}=?", (row_id,)).fetchone()
            return self._flatten(r) if r else None

    def upsert(self, table: str, row: dict) -> int:
        spec = self._spec(table)
        rid = row.get("id")
        cols, extra, errs = M.coerce(spec, row, partial=bool(rid))
        if errs:
            raise IntegrityProblem("; ".join(errs))
        try:
            with self.conn() as c:
                if rid:
                    cur = c.execute(f"SELECT extra FROM {table} WHERE id=?", (rid,)).fetchone()
                    if cur is None:
                        raise IntegrityProblem(f"No {spec.get('label', table).lower()} #{rid}")
                    if extra:
                        ex = json.loads(cur["extra"]) if cur["extra"] else {}
                        ex.update(extra)
                        cols["extra"] = json.dumps(ex, ensure_ascii=False)
                    if cols:
                        c.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?", (*cols.values(), rid))
                    return int(rid)
                if extra:
                    cols["extra"] = json.dumps(extra, ensure_ascii=False)
                cur = c.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))
                return int(cur.lastrowid)
        except sqlite3.IntegrityError as e:
            raise IntegrityProblem(_explain(str(e), spec)) from None

    def delete(self, table: str, row_id: int) -> None:
        spec = self._spec(table)
        try:
            with self.conn() as c:
                c.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
        except sqlite3.IntegrityError:
            users = [M.plural(s.get('label', t)) for t, s in self.model["entities"].items()
                     for f in M.stored_fields(s).values() if f["type"] == "ref" and f["to"] == table and f.get("on_delete", "restrict") == "restrict"]
            raise IntegrityProblem(f"This {spec.get('label', table).lower()} is still used by {' or '.join(sorted(set(users))) or 'other records'}. "
                                   + ("Archive it instead, or move those first." if "archived" in spec["fields"] else "Remove those first.")) from None

    # whole-database export/import (JSON)
    def export(self) -> dict:
        out = {"format": "aaryaai-finance", "model_version": self.model.get("version"), "exported": datetime.now().isoformat(timespec="seconds"),
               "settings": self.settings(), "tables": {}}
        with self.conn() as c:
            for t in self.model["entities"]:
                out["tables"][t] = [dict(r) for r in c.execute(f"SELECT * FROM {t}")]
            # tables the current model doesn't describe (e.g. your own record types while model.json is being
            # ignored) are still exported as they are, so a backup is never silently incomplete
            other = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
                     if r[0] not in self.model["entities"] and r[0] != "settings" and not r[0].startswith(("sqlite_", "_new_"))]
            for t in other:
                out["tables"][t] = [dict(r) for r in c.execute(f'SELECT * FROM "{t}"')]
            if other:
                out["unmanaged_tables"] = other
        return out

    def import_all(self, data: dict) -> dict:
        """Replace everything with an export. All-or-nothing; relations are checked before committing."""
        if data.get("format") != "aaryaai-finance" or not isinstance(data.get("tables"), dict):
            raise IntegrityProblem("That file isn't an aaryaai-finance export")
        counts = {}
        con = sqlite3.connect(self.path)
        try:
            con.execute("PRAGMA foreign_keys=OFF")
            con.execute("BEGIN")
            problems = []
            # only record types present in the file are replaced; others (e.g. your own types missing from an
            # older export) are left as they are
            for t, rows in data["tables"].items():
                if t not in self.model["entities"] or not isinstance(rows, list):
                    continue
                spec = self.model["entities"][t]
                con.execute(f"DELETE FROM {t}")
                for i, r in enumerate(rows):
                    if not isinstance(r, dict):
                        problems.append(f"{t} #{i + 1}: not a record"); continue
                    cols, extra, errs = M.coerce(spec, r)              # same checks as when you save in the app
                    if errs:
                        problems.append(f"{t} #{r.get('id', i + 1)}: {'; '.join(errs)}"); continue
                    ex = r.get("extra")
                    if isinstance(ex, str):
                        try:
                            ex = json.loads(ex)
                        except ValueError:
                            ex = None
                    ex = {**(ex if isinstance(ex, dict) else {}), **extra}
                    if not spec.get("primary_key") and r.get("id") is not None:
                        cols["id"] = int(r["id"])
                    if ex:
                        cols["extra"] = json.dumps(ex, ensure_ascii=False)
                    con.execute(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))
                counts[t] = len(rows)
            if problems:
                raise IntegrityProblem(f"{len(problems)} record(s) in the file aren't valid, nothing was changed: " + "; ".join(problems[:4]))
            for k, v in (data.get("settings") or {}).items():
                con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, str(v)))
            bad = con.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise IntegrityProblem(f"The file has {len(bad)} broken links (e.g. a transaction for a missing account) — nothing was changed")
            con.execute("COMMIT")
        except sqlite3.Error as e:
            con.execute("ROLLBACK")
            raise IntegrityProblem(f"Import failed, nothing was changed: {e}") from None
        except IntegrityProblem:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
        return counts

    def snapshot(self, nw: dict, currency: str) -> None:
        """One row per day, in your base currency. If you change base currency, older days are converted when read."""
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO snapshots (day, net_worth, assets, liabilities, currency) VALUES (?,?,?,?,?)",
                      (date.today().isoformat(), nw["net_worth"], nw["assets"], nw["liabilities"], currency))

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


def _explain(msg: str, spec: dict) -> str:
    m = msg.lower()
    if "foreign key" in m:
        return "That refers to something that doesn't exist (e.g. an account that was removed)."
    if "unique" in m:
        return "An identical record already exists."
    if "check constraint" in m:
        return "A value isn't one of the allowed options."
    if "not null" in m:
        col = msg.rsplit(".", 1)[-1]
        return f"{spec['fields'].get(col, {}).get('label', col)} is required."
    return msg
