"""The data model: JSON in, SQLite out.

core.json (shipped) defines every table, field, type and relation. Country packs (a `model:` section in
pack.yaml) and the user (<data>/model.json) can extend it:

    {"extends":  {"accounts": {"fields": {"nri_type": {"type": "enum", "values": ["NRE", "NRO"]}}}},
     "entities": {"policies": {"label": "Insurance policy", "fields": {...}}}}

Extra fields on built-in entities are stored in each row's `extra` JSON column, so they never need a
schema change. New entities get real tables. At start-up `sync()` compares the SQL generated from the
model with what is in the database and rebuilds only the tables that differ — after backing the file up.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

CORE = json.loads((Path(__file__).parent / "core.json").read_text(encoding="utf-8"))

TYPES = {"text": "TEXT", "int": "INTEGER", "number": "REAL", "money": "REAL", "bool": "INTEGER", "date": "TEXT",
         "datetime": "TEXT", "enum": "TEXT", "ref": "INTEGER", "json": "TEXT", "currency": "TEXT", "country": "TEXT"}
ON_DELETE = {"restrict": "RESTRICT", "cascade": "CASCADE", "set_null": "SET NULL"}
IDENT = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
RESERVED = {"id", "extra", "settings", "sqlite_sequence"}


class ModelError(ValueError):
    pass


# ------------------------------------------------------------------ building the model
def build(pack_models: list[tuple[str, dict]] | None = None, user_model: dict | None = None) -> tuple[dict, list[str]]:
    """Merge core + pack extensions + user extensions. Returns (model, errors). Bad extensions are skipped, never fatal."""
    model = copy.deepcopy(CORE)
    errors: list[str] = []
    for source, ext in (pack_models or []) + ([("your model.json", user_model)] if user_model else []):
        if not ext:
            continue
        errs = _apply(model, ext, source)
        errors += errs
    errors += [e for e in validate(model) if e not in errors]
    return model, errors


def _apply(model: dict, ext: dict, source: str) -> list[str]:
    errs = []
    if not isinstance(ext, dict):
        return [f"{source}: model must be an object"]
    for ent, spec in (ext.get("extends") or {}).items():
        if ent not in model["entities"]:
            errs.append(f"{source}: can't extend unknown entity '{ent}'")
            continue
        for fname, f in ((spec or {}).get("fields") or {}).items():
            if fname in model["entities"][ent]["fields"]:
                errs.append(f"{source}: {ent}.{fname} already exists")
                continue
            e = _field_errors(f"{source}: {ent}.{fname}", fname, f, model, custom=True)
            if e:
                errs += e
                continue
            model["entities"][ent]["fields"][fname] = {**f, "custom": True, "source": source}
    for ent, spec in (ext.get("entities") or {}).items():
        if ent in model["entities"] or not IDENT.match(ent) or ent in RESERVED:
            errs.append(f"{source}: entity name '{ent}' is taken or invalid (lowercase letters, digits, _)")
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("fields"), dict) or not spec["fields"]:
            errs.append(f"{source}: entity '{ent}' needs fields")
            continue
        trial = {"label": str(spec.get("label") or ent), "description": str(spec.get("description", "")),
                 "fields": spec["fields"], "source": source, "user_defined": True}   # no indexes/primary_key/system from outside
        model["entities"][ent] = trial
        fe = [x for fname, f in spec["fields"].items() for x in _field_errors(f"{source}: {ent}.{fname}", fname, f, model)]
        if fe:
            del model["entities"][ent]
            errs += fe
    return errs


def _field_errors(where: str, name: str, f: dict, model: dict, custom: bool = False) -> list[str]:
    if not isinstance(f, dict):
        return [f"{where}: must be an object"]
    e = []
    if not IDENT.match(name) or name in RESERVED:
        e.append(f"{where}: invalid field name")
    t = f.get("type")
    if t not in TYPES:
        e.append(f"{where}: unknown type '{t}' (use one of {', '.join(TYPES)})")
    if t == "enum" and not (isinstance(f.get("values"), list) and f["values"]):
        e.append(f"{where}: enum needs 'values'")
    if t == "ref":
        if f.get("to") not in model["entities"]:
            e.append(f"{where}: ref points to unknown entity '{f.get('to')}'")
        if f.get("on_delete", "restrict") not in ON_DELETE:
            e.append(f"{where}: on_delete must be restrict, cascade or set_null")
        if custom:
            e.append(f"{where}: extra fields on built-in entities can't be refs (add a new entity instead)")
    return e


def validate(model: dict) -> list[str]:
    errs = []
    for ent, spec in model["entities"].items():
        for fname, f in spec["fields"].items():
            errs += _field_errors(f"{ent}.{fname}", fname, f, model)
        pk = spec.get("primary_key")
        if pk and pk not in spec["fields"]:
            errs.append(f"{ent}: primary_key '{pk}' is not a field")
    return errs


# ------------------------------------------------------------------ SQL generation
def stored_fields(spec: dict) -> dict:
    """Fields that are real columns (custom extensions live in `extra`)."""
    return {k: f for k, f in spec["fields"].items() if not f.get("custom")}


def _sql_default(f: dict) -> str:
    d = f["default"]
    if isinstance(d, bool):
        return str(int(d))
    if isinstance(d, (int, float)):
        return repr(d)
    return "'" + str(d).replace("'", "''") + "'"


def table_sql(name: str, spec: dict, table_name: str | None = None) -> str:
    cols, pk = [], spec.get("primary_key")
    if not pk:
        cols.append("id INTEGER PRIMARY KEY")
    for fname, f in stored_fields(spec).items():
        c = f"{fname} {TYPES[f['type']]}"
        if fname == pk:
            c += " PRIMARY KEY"
        if f.get("required") and fname != pk:
            c += " NOT NULL"
        if f.get("unique"):
            c += " UNIQUE"
        if "default" in f and f["default"] is not None:
            c += f" DEFAULT {_sql_default(f)}"
        if f["type"] == "enum" and f.get("strict", True):
            vals = ",".join("'" + str(v).replace("'", "''") + "'" for v in f["values"])
            c += f" CHECK({fname} IN ({vals}))" if f.get("required") else f" CHECK({fname} IS NULL OR {fname} IN ({vals}))"
        if f["type"] == "ref":
            c += f" REFERENCES {f['to']}(id) ON DELETE {ON_DELETE[f.get('on_delete', 'restrict')]}"
        cols.append(c)
    cols.append("extra TEXT")
    return f"CREATE TABLE {table_name or name} ({', '.join(cols)})"


def index_sql(name: str, spec: dict) -> list[str]:
    out = []
    for ix in spec.get("indexes", []) or []:
        u = "UNIQUE " if ix.get("unique") else ""
        w = f" WHERE {ix['where']}" if ix.get("where") else ""
        out.append(f"CREATE {u}INDEX IF NOT EXISTS {ix['name']} ON {name}({', '.join(ix['columns'])}){w}")
    for fname, f in stored_fields(spec).items():
        if f["type"] == "ref":
            out.append(f"CREATE INDEX IF NOT EXISTS ix_{name}_{fname} ON {name}({fname})")
    return out


def _canon(sql: str | None) -> str:
    s = re.sub(r'["`\[\]]', "", sql or "")
    return re.sub(r"\s+", " ", s).strip().lower()


# ------------------------------------------------------------------ syncing the database
def sync(db_path: Path, model: dict, backup_dir: Path | None = None) -> dict:
    """Bring the database in line with the model. Returns a report {created, rebuilt, backup, repaired}."""
    report = {"created": [], "rebuilt": [], "backup": None, "repaired": [], "changed": []}
    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        existing = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
        todo = []
        for name, spec in model["entities"].items():
            want = table_sql(name, spec)
            if name not in existing:
                todo.append(("create", name, spec))
            elif _canon(existing[name]) != _canon(want):
                todo.append(("rebuild", name, spec))
        if any(a == "rebuild" for a, _, _ in todo) and backup_dir is not None and db_path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            b = backup_dir / f"finance-before-schema-{datetime.now():%Y%m%d-%H%M%S}.db"
            con.commit()
            shutil.copy2(db_path, b)
            report["backup"] = str(b)
        con.execute("BEGIN")
        for action, name, spec in todo:
            if action == "create":
                con.execute(table_sql(name, spec))
                report["created"].append(name)
            else:
                report["changed"] += _rebuild(con, name, spec)
                report["rebuilt"].append(name)
        for name, spec in model["entities"].items():
            for s in index_sql(name, spec):
                con.execute(s)
        report["repaired"] = _repair_orphans(con, model)
        con.execute(f"PRAGMA user_version={int(model.get('version', 1))}")
        con.execute("COMMIT")
        bad = con.execute("PRAGMA foreign_key_check").fetchall()
        if bad:
            raise ModelError(f"Database still has {len(bad)} broken links after repair")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return report


def _q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _typed_placeholder(f: dict) -> str:
    t = f["type"]
    if t == "enum":
        return _q(f["values"][0])
    if t in ("int", "number", "money", "bool", "ref"):
        return "0"
    if t in ("date", "datetime"):
        return _q("1970-01-01")
    if t == "currency":
        return _q("EUR")
    return _q("(missing)")


def _rebuild(con: sqlite3.Connection, name: str, spec: dict) -> list[str]:
    """Copy a table into its new shape. Nothing is thrown away: values that don't fit the new shape are kept in
    the row's extra._legacy, and every change is reported."""
    notes: list[str] = []
    old_cols = [r[1] for r in con.execute(f"PRAGMA table_info({name})")]
    tmp = f"_new_{name}"
    key = spec.get("primary_key") or "id"
    con.execute(f"DROP TABLE IF EXISTS {tmp}")
    con.execute(table_sql(name, spec, tmp))
    new_cols, exprs = [], []
    if not spec.get("primary_key") and "id" in old_cols:
        new_cols.append("id"); exprs.append("id")
    legacy: dict = {}                       # row key -> {field: original value}
    renamed = {o for f in stored_fields(spec).values() for o in f.get("renamed_from", [])}
    for fname, f in stored_fields(spec).items():
        src = fname if fname in old_cols else next((o for o in f.get("renamed_from", []) if o in old_cols), None)
        if src is None:
            continue
        e = src
        if f["type"] == "enum" and f.get("strict", True):
            vals = ",".join(_q(v) for v in f["values"])
            fix = " ".join(f"WHEN lower({src}) = lower({_q(v)}) THEN {_q(v)}" for v in f["values"])
            fallback = _sql_default(f) if "default" in f else (_q(f["values"][0]) if f.get("required") else "NULL")
            e = f"CASE WHEN {src} IS NULL THEN NULL WHEN {src} IN ({vals}) THEN {src} {fix} ELSE {fallback} END"
            bad = con.execute(f"SELECT {key}, {src} FROM {name} WHERE {src} IS NOT NULL AND lower({src}) NOT IN ({','.join('lower(' + _q(v) + ')' for v in f['values'])})").fetchall()
            for k, v in bad:
                legacy.setdefault(k, {})[fname] = v
            if bad:
                notes.append(f"{name}.{fname}: {len(bad)} value(s) not in {f['values']} set to {fallback.strip(chr(39))} — originals kept in the record")
        if f.get("required") and fname != spec.get("primary_key"):
            n = con.execute(f"SELECT COUNT(*) FROM {name} WHERE {src} IS NULL").fetchone()[0]
            if n:
                ph = _sql_default(f) if "default" in f else _typed_placeholder(f)
                notes.append(f"{name}.{fname}: {n} empty value(s) filled with {ph.strip(chr(39))}")
                e = f"COALESCE({e}, {ph})"
        new_cols.append(fname); exprs.append(e)
    if "extra" in old_cols:
        new_cols.append("extra"); exprs.append("extra")
    # columns the model no longer has are kept, inside `extra`, rather than dropped
    dropped = [c for c in old_cols if c not in new_cols and c != "id" and c not in renamed]
    if dropped:
        for r in con.execute(f"SELECT {key}, {', '.join(dropped)} FROM {name}").fetchall():
            kept = {c: v for c, v in zip(dropped, r[1:]) if v is not None}
            if kept:
                legacy.setdefault(r[0], {}).update(kept)
    con.execute(f"INSERT INTO {tmp} ({', '.join(new_cols)}) SELECT {', '.join(exprs)} FROM {name}")
    for k, kept in legacy.items():
        cur = con.execute(f"SELECT extra FROM {tmp} WHERE {key}=?", (k,)).fetchone()
        try:
            ex = json.loads(cur[0]) if cur and cur[0] else {}
        except ValueError:
            ex = {"_unreadable": cur[0]}
        ex.setdefault("_legacy", {}).update(kept)
        con.execute(f"UPDATE {tmp} SET extra=? WHERE {key}=?", (json.dumps(ex, ensure_ascii=False, default=str), k))
    con.execute(f"DROP TABLE {name}")
    con.execute(f"ALTER TABLE {tmp} RENAME TO {name}")
    return notes


def _placeholder(con, model, target: str, depth: int = 0) -> int:
    spec = model["entities"][target]
    vals = {}
    for fname, f in stored_fields(spec).items():
        if not f.get("required") or "default" in f:
            continue
        t = f["type"]
        if t == "ref":
            row = con.execute(f"SELECT MIN(id) FROM {f['to']}").fetchone()
            vals[fname] = row[0] if row and row[0] is not None else (_placeholder(con, model, f["to"], depth + 1) if depth < 3 else None)
            continue
        vals[fname] = ("Recovered (was missing)" if t == "text" else date.today().isoformat() if t in ("date", "datetime")
                       else f["values"][0] if t == "enum" else "EUR" if t == "currency" else "" if t == "country" else 0)
    if "archived" in spec["fields"]:
        vals["archived"] = 1
    if "note" in spec["fields"]:
        vals["note"] = "Created automatically: other records pointed to a record that no longer existed."
    cols = list(vals)
    cur = con.execute(f"INSERT INTO {target} ({', '.join(cols) or 'id'}) VALUES ({', '.join('?' * len(cols)) or 'NULL'})", list(vals.values()))
    return int(cur.lastrowid)


def _repair_orphans(con, model) -> list[str]:
    """Fix links to records that no longer exist — never by deleting data."""
    out = []
    for name, spec in model["entities"].items():
        for fname, f in stored_fields(spec).items():
            if f["type"] != "ref":
                continue
            q = f"SELECT COUNT(*) FROM {name} WHERE {fname} IS NOT NULL AND {fname} NOT IN (SELECT id FROM {f['to']})"
            n = con.execute(q).fetchone()[0]
            if not n:
                continue
            if not f.get("required"):
                con.execute(f"UPDATE {name} SET {fname}=NULL WHERE {fname} IS NOT NULL AND {fname} NOT IN (SELECT id FROM {f['to']})")
                out.append(f"{n} {name}.{fname} link(s) to missing {f['to']} cleared")
            else:
                pid = _placeholder(con, model, f["to"])
                con.execute(f"UPDATE {name} SET {fname}=? WHERE {fname} NOT IN (SELECT id FROM {f['to']})", (pid,))
                out.append(f"{n} {name} row(s) re-linked to a new '{f['to']}' record #{pid} (was missing)")
    return out


# ------------------------------------------------------------------ rows
def coerce(spec: dict, row: dict, partial: bool = False) -> tuple[dict, dict, list[str]]:
    """Validate a row against an entity. Returns (columns, extra_fields, errors)."""
    cols, extra, errs = {}, {}, []
    for fname, f in spec["fields"].items():
        if fname not in row:
            if f.get("required") and "default" not in f and not partial:
                errs.append(f"{f.get('label', fname)} is required")
            continue
        v = row[fname]
        try:
            v = _coerce_value(f, v)
        except (TypeError, ValueError) as e:
            msg = str(e) if str(e).startswith("must") else {
                "date": "must be a date (YYYY-MM-DD)", "datetime": "must be a date and time",
                "int": "must be a whole number", "ref": "must be a record id"}.get(f["type"], "must be a number")
            errs.append(f"{f.get('label', fname)} {msg}")
            continue
        if v is None and f.get("required"):
            errs.append(f"{f.get('label', fname)} is required")
            continue
        (extra if f.get("custom") else cols)[fname] = v
    return cols, extra, errs


def _coerce_value(f: dict, v):
    if v is None or v == "":
        return None
    t = f["type"]
    if t in ("int", "ref"):
        return int(v)
    if t in ("number", "money"):
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):
            raise ValueError("must be a number")
        return x
    if t == "bool":
        return 1 if v in (True, 1, "1", "true", "on", "yes") else 0
    if t == "date":
        return date.fromisoformat(str(v)[:10]).isoformat()
    if t == "datetime":
        return datetime.fromisoformat(str(v)).isoformat(timespec="seconds")
    if t == "enum":
        if str(v) not in [str(x) for x in f["values"]] and f.get("strict", True):
            raise ValueError(f"must be one of {', '.join(map(str, f['values']))}")
        return str(v)
    if t == "currency":
        s = str(v).strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", s):
            raise ValueError("must be a 3-letter currency code")
        return s
    if t == "country":
        s = str(v).strip().upper()
        if s and not re.fullmatch(r"[A-Z]{2}", s):
            raise ValueError("must be a 2-letter country code")
        return s
    if t == "json":
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return str(v)


def public(model: dict) -> dict:
    """What the browser needs to draw forms."""
    return {"version": model.get("version"), "entities": {
        k: {"label": v.get("label", k), "primary_key": v.get("primary_key"), "system": bool(v.get("system")),
            "user_defined": bool(v.get("user_defined")), "source": v.get("source", "built-in"),
            "fields": {fn: {kk: vv for kk, vv in f.items() if kk not in ("renamed_from",)} for fn, f in v["fields"].items()}}
        for k, v in model["entities"].items()}}


def plural(label: str) -> str:
    w = label.lower()
    return w[:-1] + "ies" if w.endswith("y") and w[-2:-1] not in "aeiou" else w + ("es" if w.endswith(("s", "x")) else "s")



def friendly_error(e: Exception) -> str:
    m = str(e)
    if "UNIQUE constraint failed" in m:
        return f"existing records have duplicate values, so '{m.rsplit('.', 1)[-1]}' can't be made unique"
    if "FOREIGN KEY" in m.upper():
        return "some records would link to records that don't exist"
    return m


def dry_run(db_path: Path, model: dict) -> dict:
    """Apply a model to a throw-away copy of the database first. Raises if it wouldn't work."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "check.db"
        if db_path.exists():
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(tmp)
            src.backup(dst)
            src.close(); dst.close()
        return sync(tmp, model, None)
