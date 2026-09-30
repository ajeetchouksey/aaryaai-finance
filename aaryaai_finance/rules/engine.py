"""Deterministic rules engine: documents and deadlines.

Same input, same output, every time — no AI involved. Rules come from:
  1. your rules:      <data>/rules/*.yaml        (checked first; same id overrides a pack rule)
  2. country packs:   packs/<CODE>/pack.yaml     (only the countries you switched on)
  3. trackers:        <data>/trackers/*.yaml     (e.g. a property purchase can add its own rules)

Document rule syntax (YAML):
  - id: my_rule
    label: What this document is
    category: Receipts & bills
    confidence: 0.9                      # 0..1 — how sure a text match makes us
    match:
      text_all: [word, word]             # every one must appear in the text
      text_any: [word, word]             # at least one must appear
      filename_any: [part, part]         # hints in the file name
    extract:                             # optional named fields (regex, first group)
      - {name: invoice_no, pattern: "Invoice No\\.?\\s*(\\d+)"}   # add source: squashed to match with spaces removed
    route:
      folder: "{folder:DE}/Receipts/{first_year}"
      filename: "{first_date}_{stem}{ext}"
Words are matched case-insensitively with spaces and punctuation removed, so
"A br e c h n u ng" still matches "abrechnung".
"""
from __future__ import annotations

import hashlib
import io
import re
import string
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

DE_MONTHS = {"januar": 1, "februar": 2, "märz": 3, "marz": 3, "maerz": 3, "mrz": 3, "april": 4, "mai": 5, "juni": 6,
             "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
DE_MONTH_NAMES = ["Januar", "Februar", "Maerz", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
EN_MONTHS = {m.lower(): i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
DOC_EXT = {".pdf", ".xls", ".xlsx", ".csv", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".txt"}
SKIP_PARTS = {".inbox", "_DUPLICATES_TO_DELETE", ".git", "__pycache__", "node_modules"}

DEFAULT_CATEGORIES = ["Salary & payslips", "Tax", "Property", "Bank statements", "Investments", "Insurance",
                      "Receipts & bills", "Social security & pension", "Employment", "Career", "Other"]


# ------------------------------------------------------------------ text
def extract_text(data: bytes, filename: str, max_pages: int = 6) -> tuple[str, str]:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                txt = "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
            return txt, "pdf-text" if txt.strip() else "pdf-scan (no text layer)"
        if ext in (".xls", ".xlsx", ".csv"):
            import pandas as pd
            if ext == ".csv":
                frames = [pd.read_csv(io.BytesIO(data), header=None, dtype=str, on_bad_lines="skip", encoding_errors="ignore")]
            else:
                frames = list(pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=str).values())
            rows = [" | ".join(str(x) for x in r if str(x).strip()) for df in frames for r in df.head(80).fillna("").values.tolist()]
            return "\n".join(rows), "spreadsheet"
        if ext == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return re.sub(r"<[^>]+>", " ", z.read("word/document.xml").decode("utf8", "ignore")), "docx"
        if ext in (".txt", ".md", ".json", ".xml", ".html"):
            return data.decode("utf8", "ignore"), "text"
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".heic"):
            return "", "image (no text layer)"
    except Exception as e:  # noqa: BLE001
        return "", f"unreadable ({type(e).__name__})"
    return "", "unsupported type"


def squash(s: str) -> str:
    return re.sub(r"[\s\-_.,:/()|]+", "", (s or "").lower())


def _to_float(s: str) -> float | None:
    s = s.strip().replace("₹", "").replace("€", "").replace("Rs.", "").replace("Rs", "").strip()
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{2,3})+(\.\d{1,2})?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def find_dates(text: str) -> list[str]:
    out = []
    for d, m, y in re.findall(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text):
        try:
            out.append(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    for y, m, d in re.findall(r"\b(20\d{2})-(\d{2})-(\d{2})", text):
        try:
            out.append(date(int(y), int(m), int(d)).isoformat())
        except ValueError:
            pass
    for d, mon, y in re.findall(r"\b(\d{1,2})[ -]([A-Za-z]{3})[a-z]*[ -,]*(20\d{2})\b", text):
        if mon.lower() in EN_MONTHS:
            try:
                out.append(date(int(y), EN_MONTHS[mon.lower()], int(d)).isoformat())
            except ValueError:
                pass
    return list(dict.fromkeys(out))


COMMON_EXTRACTORS = [
    {"name": "cin", "pattern": r"\b(\d{14}[A-Z]{4})\b"},
    {"name": "invoice_no", "pattern": r"Invoice No\.?\s*:?\s*(\d{6,})"},
    {"name": "certificate_no", "pattern": r"Certificate No\.?\s*:?\s*([\w/]+)"},
    {"name": "as_on", "pattern": r"as on date\s*(\d{2}\.\d{2}\.20\d{2})", "parse": "date"},
]


def common_fields(text: str) -> dict:
    f: dict = {}
    if m := re.search(r"(?:Transaction Amount\(Rs\.\)|Total Amount \(in Rs\.\)|Amount \(in Rs\.\)|Total Amount)\s*:?\s*₹?\s*([\d,]+(?:\.\d+)?)", text):
        f["amount"], f["currency"] = _to_float(m.group(1)), "INR"
    elif m := re.search(r"(?:Auszahlungsbetrag|Netto-?Bezüge|Überweisung|Gesamtbetrag|Summe)\D{0,30}([\d.]+,\d{2})", text):
        f["amount"], f["currency"] = _to_float(m.group(1)), "EUR"
    elif m := re.search(r"(?:Total|Amount due|Grand total)\s*:?\s*([€$£])\s*([\d,]+\.\d{2})", text, re.I):
        f["amount"], f["currency"] = _to_float(m.group(2)), {"€": "EUR", "$": "USD", "£": "GBP"}[m.group(1)]
    for ex in COMMON_EXTRACTORS:
        _apply_extractor(ex, text, f)
    ds = find_dates(text)
    if ds:
        f["dates"] = ds[:8]
    return f


def _apply_extractor(ex: dict, text: str, f: dict) -> None:
    mode = ex.get("source") or ex.get("on") or ex.get(True)   # YAML reads a bare `on:` key as True
    src = squash(text) if mode == "squashed" else text
    try:
        m = re.search(ex["pattern"], src, re.I if ex.get("ignore_case", True) else 0)
    except re.error:
        return
    if not m:
        return
    parse = ex.get("parse")
    if parse == "de_month_year" and m.lastindex and m.lastindex >= 2:
        mon = DE_MONTHS.get(m.group(1))
        if mon:
            f[ex["name"]] = f"{m.group(2)}-{mon:02d}"
            f[ex["name"] + "_year"], f[ex["name"] + "_month"] = m.group(2), f"{mon:02d}"
            f[ex["name"] + "_month_name_de"] = DE_MONTH_NAMES[mon - 1]
        return
    val = m.group(1) if m.lastindex else m.group(0)
    if parse == "date":
        ds = find_dates(val)
        val = ds[0] if ds else val
    elif parse == "amount":
        val = _to_float(val)
    f.setdefault(ex["name"], val)


# ------------------------------------------------------------------ rule sets
def load_yaml_rules(folder: Path) -> tuple[list, list, list]:
    """(document_rules, deadlines, errors) from every *.yaml in a folder."""
    docs, dls, errs = [], [], []
    if not folder or not folder.exists():
        return docs, dls, errs
    for p in sorted(folder.glob("*.y*ml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for r in d.get("document_rules", []) or []:
                r["_source"] = f"yours · {p.name}"
                docs.append(r)
            for r in d.get("deadlines", []) or []:
                r["_source"] = f"yours · {p.name}"
                dls.append(r)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{p.name}: {e}")
    return docs, dls, errs


def validate_rules_yaml(text: str) -> list[str]:
    errs = []
    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        return [f"YAML syntax: {e}"]
    if not isinstance(d, dict):
        return ["The file must be a mapping with 'document_rules:' and/or 'deadlines:'"]
    for i, r in enumerate(d.get("document_rules", []) or []):
        if not isinstance(r, dict) or not r.get("id"):
            errs.append(f"document_rules[{i}] needs an 'id'"); continue
        m = r.get("match") or {}
        if not any(m.get(k) for k in ("text_all", "text_any", "filename_any")):
            errs.append(f"{r['id']}: 'match' needs text_all, text_any or filename_any")
        for ex in r.get("extract", []) or []:
            try:
                re.compile(ex.get("pattern", ""))
            except re.error as e:
                errs.append(f"{r['id']}: bad regex in extract '{ex.get('name')}': {e}")
    for i, r in enumerate(d.get("deadlines", []) or []):
        if not isinstance(r, dict) or not r.get("id") or not r.get("title") or not r.get("due"):
            errs.append(f"deadlines[{i}] needs id, title and due")
    return errs


class RuleSet:
    def __init__(self, settings, packs: dict, trackers: list[dict]):
        self.settings, self.packs, self.trackers = settings, packs, trackers
        user_docs, user_dls, self.errors = load_yaml_rules(settings.rules_dir)
        tracker_docs = []
        for t in trackers:
            for r in t.get("document_rules", []) or []:
                tracker_docs.append({**r, "tracker": t["id"], "_source": f"tracker · {t.get('name', t['id'])}"})
        pack_docs = []
        for code, p in packs.items():
            for r in p.get("document_rules", []) or []:
                pack_docs.append({**r, "country": r.get("country", code), "_source": f"{p.get('flag', '')} {p.get('name', code)} pack"})
        seen, self.document_rules = set(), []
        for r in user_docs + tracker_docs + pack_docs:          # first one with an id wins
            if r.get("id") in seen:
                continue
            seen.add(r.get("id"))
            self.document_rules.append(r)
        pack_dls = [{**r, "country": code, "_source": f"{p.get('name', code)} pack"} for code, p in packs.items() for r in p.get("deadlines", []) or []]
        seen, self.deadline_rules = set(), []
        for r in user_dls + pack_dls:
            if r.get("id") in seen:
                continue
            seen.add(r.get("id"))
            self.deadline_rules.append(r)

    @property
    def categories(self) -> list[str]:
        cats = list(DEFAULT_CATEGORIES)
        for r in self.document_rules:
            if r.get("category") and r["category"] not in cats:
                cats.insert(-1, r["category"])
        return cats

    # ---------------- documents
    def score(self, rule: dict, sq: str, fn: str) -> tuple[float, str] | None:
        m = rule.get("match") or {}
        all_of, any_of, fhints = m.get("text_all") or [], m.get("text_any") or [], m.get("filename_any") or []
        conf = float(rule.get("confidence", 0.8))
        ok_all = all(squash(w) in sq for w in all_of) if all_of else True
        hit_any = any(squash(w) in sq for w in any_of) if any_of else bool(all_of)
        by_text = bool(sq) and ok_all and hit_any
        by_name = any(str(h).lower() in fn for h in fhints)
        if by_text:
            return min(conf + (0.03 if by_name else 0), 0.99), "text + file name" if by_name else "text"
        if by_name:
            return conf * (0.7 if sq else 0.75), "file name only"
        return None

    def classify(self, text: str, filename: str) -> tuple[dict | None, dict, list]:
        sq, fn = squash(text), filename.lower()
        scored = []
        for r in self.document_rules:
            s = self.score(r, sq, fn)
            if s:
                scored.append((s[0], s[1], r))
        scored.sort(key=lambda x: -x[0])       # stable: earlier (user) rules win ties
        if not scored:
            return None, {"confidence": 0.0, "matched_on": "nothing"}, []
        best = scored[0]
        return best[2], {"confidence": round(best[0], 2), "matched_on": best[1]}, [
            {"id": r["id"], "label": r.get("label"), "score": round(s, 2), "on": on, "source": r.get("_source")} for s, on, r in scored[:6]]

    def fields(self, text: str, rule: dict | None) -> dict:
        f = common_fields(text) if text else {}
        for ex in (rule or {}).get("extract", []) or []:
            _apply_extractor(ex, text, f)
        return f

    def folder(self, key: str) -> str:
        from ..packs import folder_for
        return folder_for(self.settings, self.packs, key)

    def _tracker_stage_folder(self, tracker: dict, sq: str, when: str | None) -> str:
        base_rel = tracker.get("stages_folder", "")
        base = self.settings.documents_root / base_rel
        existing = sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []
        for st in tracker.get("stages", []):
            for kw in st.get("keywords", []) or []:
                if squash(kw) in sq:
                    pre = f"{st['no']}_"
                    hit = next((n for n in existing if n.startswith(pre)), None)
                    return f"{base_rel}/{hit or pre + re.sub(r'[^A-Za-z0-9]', '', st.get('name', 'Stage')) + '_' + (when or date.today().isoformat())[:7]}"
        if when:
            ym = when[:7]
            c = [n for n in existing if re.search(r"_(\d{4}-\d{2})$", n) and n[-7:] <= ym]
            if c:
                return f"{base_rel}/{max(c, key=lambda n: n[-7:])}"
        return f"{base_rel}/_Unsorted"

    def route(self, rule: dict | None, text: str, filename: str, f: dict) -> dict:
        p = Path(filename)
        dates = f.get("dates") or []
        first = dates[0] if dates else date.today().isoformat()
        ctx = {**{k: v for k, v in f.items() if not isinstance(v, (list, dict))},
               "ext": p.suffix.lower() or ".pdf", "stem": re.sub(r"[^\w\-. ]+", "", p.stem).strip().replace(" ", "_")[:80] or "document",
               "original": p.name, "first_date": first, "first_month": first[:7], "first_year": first[:4],
               "today": date.today().isoformat(), "year": str(date.today().year)}
        if f.get("amount") is not None:
            amt = f["amount"]
            ctx["amount_int"] = str(int(amt))
            ctx["unit_or_gst"] = "GST" if amt < 100000 else "Unit"
        if rule and rule.get("tracker"):
            t = next((t for t in self.trackers if t["id"] == rule["tracker"]), None)
            if t:
                ctx["stage_folder"] = self._tracker_stage_folder(t, squash(text), first)
                ctx["tracker_folder"] = t.get("documents_folder", "")
        r = (rule or {}).get("route") or {}
        folder_t = r.get("folder") or "{folder:inbox}"
        name_t = r.get("filename") or "{original}"

        def fill(tmpl: str) -> str | None:
            def repl_folder(m):
                return self.folder(m.group(1))
            tmpl = re.sub(r"\{folder:([A-Za-z_]+)\}", repl_folder, tmpl)
            try:
                names = [fn for _, fn, _, _ in string.Formatter().parse(tmpl) if fn]
            except ValueError:
                return None
            if any(n not in ctx or ctx[n] in (None, "") for n in names):
                return None
            return tmpl.format(**ctx)

        folder = fill(folder_t) or self.folder("inbox")
        name = fill(name_t) or p.name
        return {"folder": folder.strip("/").replace("\\", "/"), "filename": Path(name).name}

    def analyze(self, data: bytes, filename: str) -> dict:
        text, method = extract_text(data, filename)
        rule, conf, candidates = self.classify(text, filename)
        f = self.fields(text, rule)
        tgt = self.route(rule, text, filename, f)
        return {"filename": filename, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "method": method,
                "has_text": bool(text.strip()), "doc_type": rule["id"] if rule else "unknown",
                "label": rule.get("label", rule["id"]) if rule else "Not recognised",
                "category": rule.get("category", "Other") if rule else "Other",
                "country": rule.get("country", "") if rule else "", "rule_source": rule.get("_source") if rule else None,
                **conf, "candidates": candidates, "fields": f, **tgt, "excerpt": re.sub(r"\s+", " ", text)[:600]}

    # ---------------- deadlines
    def deadlines(self, answers: dict, today: date | None = None, horizon_days: int = 460) -> list[dict]:
        today = today or date.today()
        out = []
        for r in self.deadline_rules:
            cond = str(r.get("if") or "")
            if cond:
                neg = cond.startswith("!")
                val = bool(answers.get(cond.lstrip("!")))
                if val == neg:
                    continue
            due_t = str(r.get("due"))
            if due_t == "ongoing":
                out.append(self._dl(r, None, None))
                continue
            seen = set()
            for ty in range(today.year - 5, today.year + 2):
                d = _render_due(due_t, ty, ty)
                if not d or d in seen:
                    continue
                seen.add(d)
                dd = date.fromisoformat(d)
                if today - timedelta(days=0) <= dd <= today + timedelta(days=horizon_days):
                    out.append(self._dl(r, d, ty))
        return sorted(out, key=lambda x: (x["due"] is None, x["due"] or ""))

    def _dl(self, r: dict, due: str | None, ty: int | None) -> dict:
        ty = ty or date.today().year
        return {"key": f"{r['id']}:{due or 'ongoing'}", "rule_id": r["id"], "due": due, "country": r.get("country", ""),
                "title": _render_text(r.get("title", r["id"]), ty), "detail": _render_text(r.get("detail", ""), ty),
                "severity": r.get("severity", "normal"), "source": r.get("source", r.get("_source", ""))}


def _render_due(t: str, tax_year: int, year: int) -> str | None:
    s = _render_text(t, tax_year, year)
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _render_text(t: str, tax_year: int, year: int | None = None) -> str:
    year = year or tax_year

    def rep(m):
        base = tax_year if m.group(1) == "tax_year" else year
        off = int(m.group(2).replace(" ", "")) if m.group(2) else 0
        return str(base + off)
    s = re.sub(r"\{(tax_year|year)\s*([+-]\s*\d+)?\}", rep, t)
    return s.replace("{tax_year_next2}", str(tax_year + 1)[-2:])


# ------------------------------------------------------------------ filing helpers
def safe_target(root: Path, folder: str, filename: str) -> Path:
    base = root.resolve()
    tgt = (base / folder / Path(filename).name).resolve()
    if base not in tgt.parents:
        raise ValueError("Target must be inside your documents folder")
    return tgt


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    for i in range(2, 500):
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not q.exists():
            return q
    raise ValueError("Too many files with this name")


def library(root: Path) -> list[dict]:
    out = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        try:
            rel_parts = set(p.relative_to(root).parts)
        except ValueError:
            continue
        if not p.is_file() or p.suffix.lower() not in DOC_EXT or SKIP_PARTS & rel_parts or any(x.startswith(".") for x in rel_parts):
            continue
        rel = p.relative_to(root).as_posix()
        st = p.stat()
        parent = Path(rel).parent.as_posix()
        out.append({"path": rel, "folder": "" if parent == "." else parent,
                    "name": p.name, "size": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return sorted(out, key=lambda r: r["path"].lower())


def same_place(a: str, b: str) -> bool:
    return a.strip("/").lower() == b.strip("/").lower()
