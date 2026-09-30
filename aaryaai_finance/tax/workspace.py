"""Tax-year workspace: documents, the questions a good adviser would ask, the best way to file, and a filing sheet.

Everything country-specific lives in the pack's `tax_workspace:` section (documents to collect, questions,
derived numbers, which calculator to run, optimisation checks and the lines of the filing sheet).
Formulas are small arithmetic expressions over your answers, evaluated by a safe evaluator below
(numbers, + - * /, comparisons, and/or, min/max/round, `a if cond else b` — nothing else).

The app prepares; you file. Nothing is sent to a tax authority.
"""
from __future__ import annotations

import ast
import json
import operator
import re
from datetime import date

from ..core.planning import fmt

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FN = {"min": min, "max": max, "round": round, "abs": abs}


class FormulaError(ValueError):
    pass


def check_formula(expr: str) -> str | None:
    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError as e:
        return f"formula '{expr}': {e.msg}"
    for n in ast.walk(tree):
        if isinstance(n, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.USub, ast.UAdd, ast.Not, ast.Compare, ast.BoolOp, ast.And, ast.Or,
                          ast.IfExp, ast.Name, ast.Load, ast.Constant, ast.Call)) or type(n) in _BIN or type(n) in _CMP:
            if isinstance(n, ast.Call) and not (isinstance(n.func, ast.Name) and n.func.id in _FN and not n.keywords):
                return f"formula '{expr}': only min, max, round and abs can be called"
            if isinstance(n, ast.Constant) and not isinstance(n.value, (int, float, bool)):
                return f"formula '{expr}': only numbers are allowed"
            continue
        return f"formula '{expr}': '{type(n).__name__}' isn't allowed"
    return None


def evaluate(expr, env: dict):
    """Evaluate a pack formula. Unknown names count as 0 (an unanswered question)."""
    if isinstance(expr, (int, float, bool)) or expr is None:
        return expr
    err = check_formula(expr)
    if err:
        raise FormulaError(err)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            v = env.get(n.id, 0)
            return 0 if v in (None, "") else v
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and not b:
                return 0.0
            return _BIN[type(n.op)](float(a), float(b))
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return (not v) if isinstance(n.op, ast.Not) else (-float(v) if isinstance(n.op, ast.USub) else float(v))
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, c in zip(n.ops, n.comparators):
                right = ev(c)
                if not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.IfExp):
            return ev(n.body) if ev(n.test) else ev(n.orelse)
        if isinstance(n, ast.Call):
            return _FN[n.func.id](*[ev(a) for a in n.args])
        raise FormulaError(type(n).__name__)
    return ev(ast.parse(str(expr), mode="eval"))


def validate_workspace(ws) -> list[str]:
    if not isinstance(ws, dict):
        return ["tax_workspace must be a mapping"]
    errs = []
    qids = set()
    for q in ws.get("questions") or []:
        if not isinstance(q, dict) or not q.get("id") or not q.get("label"):
            errs.append("tax_workspace: each question needs id and label")
        else:
            qids.add(q["id"])
    for sec in ("derived", "checks", "sheet"):
        for x in ws.get(sec) or []:
            if not isinstance(x, dict):
                errs.append(f"tax_workspace.{sec}: each entry must be a mapping"); continue
            for k in ("value", "when", "effect"):
                if k in x and isinstance(x[k], str):
                    e = check_formula(x[k])
                    if e:
                        errs.append(f"tax_workspace.{sec}: {e}")
    for k, v in ((ws.get("estimate") or {}).get("inputs") or {}).items():
        if isinstance(v, str):
            e = check_formula(v)
            if e:
                errs.append(f"tax_workspace.estimate.{k}: {e}")
    return errs


def default_year(kind: str, today: date | None = None) -> int:
    today = today or date.today()
    if kind == "india_fy":        # the last financial year (April–March) that has ended
        return today.year - 1 if today.month >= 4 else today.year - 2
    return today.year - 1


def year_label(kind: str, year: int) -> str:
    return f"FY {year}-{str(year + 1)[-2:]}" if kind == "india_fy" else str(year)


def _doc_year(d: dict, kind: str = "calendar") -> int | None:
    y = _doc_year_raw(d)
    if y is None or kind != "india_fy":
        return y[0] if isinstance(y, tuple) else y
    year, month = y if isinstance(y, tuple) else (y, None)
    return year - 1 if (month and month < 4) else year


def _doc_year_raw(d: dict):
    try:
        f = json.loads(d.get("fields") or "{}") if isinstance(d.get("fields"), str) else (d.get("fields") or {})
    except ValueError:
        f = {}
    for k in ("tax_year", "period_year"):
        if str(f.get(k) or "").isdigit():
            return int(f[k])
    ay = str(f.get("assessment_year") or "")
    if re.fullmatch(r"20\d{2}-\d{2}", ay):
        return int(ay[:4]) - 1
    if d.get("doc_date"):
        try:
            return int(str(d["doc_date"])[:4]), int(str(d["doc_date"])[5:7])
        except ValueError:
            pass
    name = d.get("stored_path") or d.get("original_name") or ""
    m = re.search(r"(20\d{2})[-_ .](0[1-9]|1[0-2])(?!\d)", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(20\d{2})", name)
    return int(m.group(1)) if m else None


def _doc_fields(d: dict) -> dict:
    try:
        return json.loads(d.get("fields") or "{}") if isinstance(d.get("fields"), str) else (d.get("fields") or {})
    except ValueError:
        return {}


def _coerce(q: dict, v):
    t = q.get("type", "number")
    if v in (None, ""):
        return None
    if t == "number":
        sv = str(v).strip().replace("€", "").replace("₹", "").strip()
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})*(,\d+)?|-?\d+,\d+", sv):   # German style 68.400,00
            sv = sv.replace(".", "").replace(",", ".")
        try:
            return float(sv.replace(",", ""))
        except ValueError:
            return None
    if t == "bool":
        return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
    return str(v)


def _fmt(v, kind: str, ccy: str):
    if v is None:
        return "—"
    if kind == "money":
        return fmt(float(v), ccy)
    if kind == "bool":
        return "yes" if v else "no"
    if kind == "days":
        return f"{float(v):,.0f} days"
    if kind == "number":
        return f"{float(v):,.0f}"
    if kind == "percent":
        return f"{float(v):.1%}"
    return str(v)


def build(pack: dict, year: int, saved: dict, documents: list[dict], profile_answers: dict, run_calc) -> dict:
    ws = pack.get("tax_workspace") or {}
    kind = ws.get("year", "calendar")
    ccy = pack.get("currency", "EUR")
    env: dict = {"year": year}

    # 1) documents
    doc_rows, found_by_id = [], {}
    for dd in ws.get("documents") or []:
        want_year = year + int(dd.get("year_offset", 0))
        types = set(dd.get("doc_types") or [])
        hits = [d for d in documents if d.get("doc_type") in types]
        exact = [d for d in hits if _doc_year(d, kind) == want_year]
        unknown = [d for d in hits if _doc_year(d, kind) is None]
        use = exact or unknown
        found_by_id[dd["id"]] = use
        doc_rows.append({"id": dd["id"], "label": dd.get("label", dd["id"]), "required": bool(dd.get("required")), "why": dd.get("why", ""),
                         "found": [{"path": d["stored_path"], "year": _doc_year(d, kind)} for d in use], "status": "found" if exact else ("check" if unknown else "missing")})

    # 2) questions, prefilled from documents where a pack says so
    qrows = []
    for q in ws.get("questions") or []:
        v, src = None, None
        if q["id"] in saved and saved[q["id"]] not in (None, ""):
            v, src = _coerce(q, saved[q["id"]]), "you"
        elif q.get("prefill"):
            doc_id, _, field = str(q["prefill"]).partition(".")
            for d in found_by_id.get(doc_id, []):
                f = _doc_fields(d).get(field)
                if f not in (None, ""):
                    v, src = _coerce(q, f), f"from {d['stored_path'].rsplit('/', 1)[-1]}"
                    break
        elif q.get("from_answer"):
            fa = q["from_answer"]
            v, src = ((not profile_answers.get(fa[1:])) if fa.startswith("!") else bool(profile_answers.get(fa))), "your setup answers"
        if v is None and "default" in q:
            v, src = _coerce(q, q["default"]), "default"
        env[q["id"]] = v if v is not None else 0
        qrows.append({**{k: q[k] for k in q if k in ("id", "label", "type", "help", "section", "options", "unit")}, "value": v, "source": src,
                      "answered": src in ("you", "your setup answers") or (src or "").startswith("from ")})

    # 3) derived numbers
    derived = []
    for x in ws.get("derived") or []:
        try:
            env[x["id"]] = evaluate(x["value"], env)
        except (FormulaError, TypeError, ValueError) as e:
            env[x["id"]] = 0
            derived.append({"id": x["id"], "label": x.get("label", x["id"]), "value": None, "error": str(e)})
            continue
        derived.append({"id": x["id"], "label": x.get("label", x["id"]), "value": env[x["id"]], "shown": _fmt(env[x["id"]], x.get("format", "money"), ccy)})

    # 4) estimate with the pack's calculator
    est, est_error = None, None
    e = ws.get("estimate")
    if e:
        try:
            inputs = {k: evaluate(v, env) if isinstance(v, str) else v for k, v in (e.get("inputs") or {}).items()}
            est = run_calc(e["calculator"], inputs)
            for k, v in (est.get("data") or {}).items():
                env["est_" + k] = v
        except Exception as ex:  # noqa: BLE001
            est_error = str(ex)

    # 5) optimisation checks
    checks = []
    for c in ws.get("checks") or []:
        try:
            if not evaluate(c.get("when", "True"), env):
                continue
            eff = evaluate(c["effect"], env) if c.get("effect") else None
        except (FormulaError, TypeError, ValueError):
            continue
        checks.append({"id": c.get("id"), "title": c.get("title", ""), "detail": _fill(c.get("detail", ""), env, ccy),
                       "effect": eff, "effect_shown": _fmt(eff, c.get("format", "money"), ccy) if eff is not None else "", "tone": c.get("tone", "good")})

    # 6) filing sheet
    sheet = []
    for s in ws.get("sheet") or []:
        try:
            v = evaluate(s["value"], env)
        except (FormulaError, TypeError, ValueError):
            v = None
        if s.get("skip_zero") and not v:
            continue
        sheet.append({"form": s.get("form", ""), "field": s.get("field", ""), "value": v, "shown": _fmt(v, s.get("format", "money"), ccy)})

    req = [d for d in doc_rows if d["required"]]
    answered = sum(1 for q in qrows if q["answered"])
    prefilled = sum(1 for q in qrows if (q["source"] or "").startswith("from "))
    steps = [
        {"id": "collect", "label": "Collect", "done": all(d["status"] != "missing" for d in req),
         "detail": f"{sum(1 for d in doc_rows if d['status'] != 'missing')} of {len(doc_rows)} documents"},
        {"id": "numbers", "label": "Numbers", "done": prefilled > 0 or answered == len(qrows), "detail": f"{prefilled} read from documents"},
        {"id": "interview", "label": "Interview", "done": answered == len(qrows), "detail": f"{answered} of {len(qrows)} answered"},
        {"id": "optimise", "label": "Optimise", "done": est is not None and answered == len(qrows), "detail": f"{len(checks)} findings"},
        {"id": "sheet", "label": "Filing sheet", "done": False, "detail": f"{len(sheet)} lines"},
    ]
    return {"country": pack["code"], "flag": pack.get("flag", ""), "name": pack.get("name"), "currency": ccy, "year": year,
            "year_kind": kind, "year_label": year_label(kind, year), "title": ws.get("title", "Tax return").replace("{year}", year_label(kind, year)),
            "filing_hint": ws.get("filing_hint", ""), "documents": doc_rows, "questions": qrows, "derived": derived,
            "estimate": est, "estimate_error": est_error, "checks": checks, "sheet": sheet, "steps": steps,
            "complete": answered == len(qrows)}


def _fill(text: str, env: dict, ccy: str) -> str:
    def rep(m):
        expr, _, kind = m.group(1).partition("|")
        try:
            return _fmt(evaluate(expr, env), kind or "money", ccy)
        except (FormulaError, TypeError, ValueError):
            return "?"
    return re.sub(r"\{([^{}]+)\}", rep, text)


def sheet_csv(ws: dict) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Form", "Field", "Value"])
    for r in ws["sheet"]:
        w.writerow([r["form"], r["field"], r["shown"]])
    w.writerow([])
    w.writerow(["Question", "Answer", "Source"])
    for q in ws["questions"]:
        w.writerow([q["label"], "" if q["value"] is None else q["value"], q["source"] or ""])
    return buf.getvalue()


def followup_prompt(ws: dict) -> str:
    missing = [d["label"] for d in ws["documents"] if d["status"] == "missing"]
    qa = [f"- {q['label']}: {q['value'] if q['value'] is not None else '(not answered)'}" for q in ws["questions"]]
    return (f"You help someone prepare their {ws['name']} tax return for {ws['year_label']}. They answered:\n" + "\n".join(qa)
            + (f"\nDocuments still missing: {', '.join(missing)}." if missing else "")
            + "\n\nAsk exactly ONE short follow-up question a careful tax adviser would ask next, about something that could change "
              "the result and isn't already covered above. Plain language, no preamble, one sentence, then one short line on why it matters.")
