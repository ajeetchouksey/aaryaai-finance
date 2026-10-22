"""Bank-statement import: CSV exports from your bank, read by profiles written in YAML.

A profile says which columns hold the date, the amount (or debit and credit) and the description, and how dates are
written. Profiles come from your rules files (`import_profiles:` in <data folder>/rules/*.yaml) and from country packs;
the first one whose header names all appear in the file is used. Nothing is saved here: `parse` and `mark_duplicates`
build a preview, and the server writes the rows you tick.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import date, datetime

from ..rules.engine import _to_float

MAX_ROWS = 5000
# Used when no pack or rules file has a profile that fits: a plain "Date, Description, Amount" export.
GENERIC = [{"id": "generic_date_description_amount", "label": "Generic CSV (Date · Description · Amount)", "_source": "built in",
            "match": {"headers_all": ["Date", "Amount"]},
            "columns": {"date": "Date", "amount": "Amount", "description": ["Payee", "Description"]},
            "date_format": ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"]}]
COLUMN_KEYS = ("date", "amount", "debit", "credit", "description")


def check_profile(p) -> list[str]:
    """Problems with one profile (empty list = fine). A broken profile is skipped and reported, never half-used."""
    if not isinstance(p, dict) or not p.get("id"):
        return ["import profile needs an id"]
    errs, pid = [], p["id"]
    cols = p.get("columns")
    if not isinstance(cols, dict) or not cols.get("date"):
        errs.append(f"{pid}: columns.date is required")
    elif not (cols.get("amount") or (cols.get("debit") and cols.get("credit"))):
        errs.append(f"{pid}: columns needs amount, or debit and credit")
    elif any(k not in COLUMN_KEYS for k in cols):
        errs.append(f"{pid}: unknown column key (use {', '.join(COLUMN_KEYS)})")
    heads = (p.get("match") or {}).get("headers_all")
    if not isinstance(heads, list) or not heads or not all(isinstance(h, str) for h in heads):
        errs.append(f"{pid}: match.headers_all must list the header names that identify the file")
    fmts = p.get("date_format", "%Y-%m-%d")
    for f in fmts if isinstance(fmts, list) else [fmts]:
        try:
            datetime(2026, 1, 31).strftime(str(f))
        except ValueError:
            errs.append(f"{pid}: bad date_format {f!r}")
    if p.get("delimiter") is not None and (not isinstance(p["delimiter"], str) or len(p["delimiter"]) != 1):
        errs.append(f"{pid}: delimiter must be one character")
    return errs


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):          # many German banks still export Windows-1252
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _rows(text: str, delimiter: str | None) -> list[list[str]]:
    if not delimiter:
        try:
            delimiter = csv.Sniffer().sniff(text[:4000], delimiters=";,\t|").delimiter
        except csv.Error:
            delimiter = ";" if text[:4000].count(";") > text[:4000].count(",") else ","
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _norm(s: str) -> str:
    return " ".join(str(s).lower().replace("﻿", "").split())


def _find_header(rows: list[list[str]], profile: dict) -> int | None:
    want = [_norm(h) for h in profile["match"]["headers_all"]]
    for i, r in enumerate(rows[:40]):                # banks put a few lines of account details above the table
        have = {_norm(c) for c in r}
        if all(w in have for w in want):
            return i
    return None


def _date(s: str, fmts) -> date | None:
    for f in fmts if isinstance(fmts, list) else [fmts]:
        try:
            return datetime.strptime(s.strip(), str(f)).date()
        except ValueError:
            continue
    return None


def _amount(s: str) -> float | None:
    s = (s or "").replace("−", "-").replace(" ", "").replace(" ", "")
    for cur in ("EUR", "INR", "USD", "GBP", "CHF"):
        s = s.replace(cur, "")
    neg = s.endswith("-") or (s.startswith("(") and s.endswith(")"))     # "12,50-" and "(12.50)" are negative too
    s = s.strip("()-+") if neg else s.lstrip("+")
    v = _to_float(s) if s else None
    return -v if (v is not None and neg) else v


def parse(data: bytes, profiles: list[dict], profile_id: str | None = None) -> dict:
    """Rows of a statement as {date, kind, amount, description}, the profile used, and the lines that couldn't be read."""
    rows = _rows(_decode(data), None)
    chosen = [p for p in profiles if not profile_id or p["id"] == profile_id]
    for p in chosen:
        if p.get("delimiter"):
            rows_p = _rows(_decode(data), p["delimiter"])
        else:
            rows_p = rows
        h = _find_header(rows_p, p)
        if h is not None:
            return _read(rows_p, h, p)
    return {"profile": None, "rows": [], "skipped": [],
            "error": "None of the import profiles fits this file. Check it is your bank's CSV export, or add a profile "
                     "(Rules → import_profiles)."}


def _read(rows: list[list[str]], h: int, p: dict) -> dict:
    head = [_norm(c) for c in rows[h]]
    col = lambda name: head.index(_norm(name)) if name and _norm(name) in head else None   # noqa: E731
    cols = p["columns"]
    i_date, i_amt, i_deb, i_cred = col(cols.get("date")), col(cols.get("amount")), col(cols.get("debit")), col(cols.get("credit"))
    desc = cols.get("description") or []
    i_desc = [i for i in (col(d) for d in (desc if isinstance(desc, list) else [desc])) if i is not None]
    fmts, invert = p.get("date_format", "%Y-%m-%d"), bool(p.get("invert"))
    out, skipped = [], []
    for n, r in enumerate(rows[h + 1:], start=h + 2):
        if not any(r):
            continue
        get = lambda i: r[i] if i is not None and i < len(r) else ""   # noqa: E731
        d = _date(get(i_date), fmts)
        if i_amt is not None:
            v = _amount(get(i_amt))
        else:
            deb, cred = _amount(get(i_deb)) or 0, _amount(get(i_cred)) or 0
            v = (cred - abs(deb)) if (deb or cred) else None
        if d is None or v is None or v == 0:
            if len(skipped) < 50:
                skipped.append({"line": n, "reason": "no date" if d is None else "no amount", "text": " | ".join(r)[:120]})
            continue
        v = -v if invert else v
        text = " · ".join(x for x in (get(i).strip() for i in i_desc) if x)
        out.append({"date": d.isoformat(), "kind": "income" if v > 0 else "expense", "amount": round(abs(v), 2), "description": text[:200]})
        if len(out) >= MAX_ROWS:
            break
    return {"profile": {"id": p["id"], "label": p.get("label", p["id"]), "source": p.get("_source", "")}, "rows": out, "skipped": skipped}


def mark_duplicates(rows: list[dict], existing: list[dict]) -> list[dict]:
    """Flag rows already in the account (same date, kind and amount). Two equal coffees on one day count twice."""
    have = Counter((t["date"], t["kind"], round(float(t["amount"]), 2)) for t in existing)
    for i, r in enumerate(rows):
        k = (r["date"], r["kind"], r["amount"])
        r["i"] = i
        r["duplicate"] = have[k] > 0
        if have[k] > 0:
            have[k] -= 1
    return rows
