"""HTTP API + web UI. Binds to 127.0.0.1 only — the app is for the person at this computer."""
from __future__ import annotations

import base64
import re
import secrets
import json
import os
import shutil
from datetime import date, datetime
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .ai import assistant
from .ai.providers import PROVIDERS, ProviderError, make_provider
from .config import Settings, default_data_dir, remember_data_dir, remembered_data_dir, SECRET_KEYS
from .context import Ctx
from .core import ledger, planning, trackers as trk, trading
from .core.db import IntegrityProblem
from . import model as M
from .packs import available_packs, pack_summary
from .rules.engine import library, safe_target, same_place, unique_path, validate_rules_yaml

WEB = Path(__file__).parent / "web"
COMMON_CURRENCIES = ["EUR", "INR", "USD", "GBP", "CHF", "SGD", "AED", "AUD", "CAD", "JPY", "SEK", "NOK", "DKK", "PLN", "CZK"]


LOOPBACK = {"127.0.0.1", "localhost", "::1"}
PUBLIC_PATHS = ("/static/",)
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-src 'self' blob:; object-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def create_app(data_dir: Path | None = None, extra_hosts: set[str] | None = None) -> FastAPI:
    app = FastAPI(title="aaryaai-finance", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    token = secrets.token_urlsafe(32)
    hosts = LOOPBACK | set(extra_hosts or ())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        """Only this computer's browser tab may use the API.
        Host check: blocks DNS-rebinding (a web page pointing its own domain at 127.0.0.1).
        Origin check: blocks other web pages from sending requests here.
        Session token: created at start-up, only handed to the app's own page."""
        host = request.url.hostname or ""
        if host not in hosts:
            return JSONResponse({"detail": "Blocked: this app only answers on 127.0.0.1 / localhost."}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != "null":
            from urllib.parse import urlsplit
            o = urlsplit(origin)
            if o.hostname not in hosts or (o.port or 80) != (request.url.port or 80):
                return JSONResponse({"detail": "Blocked: request from another website."}, status_code=403)
        elif origin == "null" and request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "Blocked: request from an unknown origin."}, status_code=403)
        path = request.url.path
        if path != "/" and not path.startswith(PUBLIC_PATHS):
            given = request.headers.get("x-session-token") or request.query_params.get("t")
            if not given or not secrets.compare_digest(given, token):
                return JSONResponse({"detail": "Session expired — reload the page."}, status_code=401)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = CSP
        if not path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp
    state = {"ctx": Ctx(Settings(data_dir or remembered_data_dir() or default_data_dir())), "review": {}, "explicit_dir": data_dir is not None}

    def ctx() -> Ctx:
        return state["ctx"]

    @app.exception_handler(IntegrityProblem)
    async def _integrity(_req, exc: IntegrityProblem):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def _history(c: Ctx) -> list[dict]:
        out = []
        for h in c.db.snapshots():
            v = h["net_worth"]
            cur = h.get("currency") or c.base
            if cur != c.base:
                try:
                    v = c.conv(v, cur)
                except ValueError:
                    continue
            out.append({"day": h["day"], "net_worth": v})
        return out

    # ======================= updates =======================
    @app.get("/update/check")
    def update_check(force: bool = False):
        from . import updates
        c = ctx()
        return updates.check(c.settings.data_dir / ".update-check.json", bool(c.settings.config.get("updates", {}).get("check", True)), force)

    # ======================= data model =======================
    @app.get("/model")
    def get_model():
        c = ctx()
        mp = c.settings.model_path
        return {**M.public(c.model), "errors": c.model_errors, "user_model_path": str(mp),
                "user_model_text": mp.read_text(encoding="utf-8") if mp.exists() else "",
                "last_sync": c.db.sync_report, "secrets_moved_to_keychain": c.secrets_moved,
                "rule_errors": c.rules.errors, "backups_dir": str(c.settings.backups_dir), "app_version": __version__}

    @app.post("/model/user")
    def save_user_model(p: dict = Body(...)):
        c = ctx()
        text = p.get("text", "")
        try:
            user = json.loads(text) if text.strip() else None
        except ValueError as e:
            raise HTTPException(400, f"Not valid JSON: {e}")
        pack_models = [(f"{pk.get('name', code)} pack", pk["model"]) for code, pk in c.packs.items() if pk.get("model")]
        new_model, errs = M.build(pack_models, user)
        if errs:
            raise HTTPException(400, "; ".join(errs[:6]))
        try:
            M.dry_run(c.settings.db_path, new_model)          # try it on a copy first; the real file is untouched
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Can't apply this model to your data: {M.friendly_error(e)} — nothing was changed")
        if user is None:
            if c.settings.model_path.exists():
                c.settings.model_path.rename(c.settings.model_path.with_suffix(f".json.off-{datetime.now():%Y%m%d%H%M%S}"))
        else:
            c.settings.model_path.write_text(json.dumps(user, indent=2, ensure_ascii=False), encoding="utf-8")
        c.reload()
        return {"ok": True, "sync": c.db.sync_report}

    @app.get("/data/export")
    def export_data():
        c = ctx()
        body = json.dumps(c.db.export(), ensure_ascii=False, indent=1, default=str)
        name = f"aaryaai-finance-export-{date.today().isoformat()}.json"
        return StreamingResponse(iter([body]), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/data/import")
    def import_data(p: dict = Body(...)):
        c = ctx()
        need(p.get("confirm") == "REPLACE", "Type REPLACE to confirm")
        c.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        b = c.settings.backups_dir / f"finance-before-import-{datetime.now():%Y%m%d-%H%M%S}.db"
        shutil.copy2(c.settings.db_path, b)
        counts = c.db.import_all(p.get("data") or {})
        return {"ok": True, "imported": counts, "backup": str(b)}

    def need(cond, msg, code=400):
        if not cond:
            raise HTTPException(code, msg)

    # ======================= setup & settings =======================
    @app.get("/setup/status")
    def setup_status():
        c = ctx()
        return {"configured": c.settings.is_configured, "data_dir": str(c.settings.data_dir), "version": __version__}

    @app.get("/setup/options")
    def setup_options():
        c = ctx()
        return {"packs": [pack_summary(p) for p in available_packs(c.settings).values()], "currencies": COMMON_CURRENCIES,
                "providers": {k: {kk: vv for kk, vv in v.items()} for k, v in PROVIDERS.items()},
                "default_data_dir": str(c.settings.data_dir if (c.settings.is_configured or state["explicit_dir"]) else default_data_dir())}

    @app.post("/setup/apply")
    def setup_apply(p: dict = Body(...)):
        d = Path(os.path.expandvars(str(p.get("data_dir") or ""))).expanduser()
        need(str(d).strip(), "Choose a data folder")
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / ".write-test").write_text("ok"); (d / ".write-test").unlink()
        except OSError as e:
            raise HTTPException(400, f"Can't write to {d}: {e}")
        s = Settings(d)
        cfg = s.config
        need(p.get("countries"), "Pick at least one country")
        cfg["countries"] = p["countries"]
        cfg["base_currency"] = p.get("base_currency") or cfg["base_currency"]
        cfg["extra_currencies"] = p.get("extra_currencies", [])
        cfg["profile"]["name"] = p.get("name", cfg["profile"].get("name", ""))
        cfg["profile"]["about"] = p.get("about", cfg["profile"].get("about", ""))
        cfg["profile"]["answers"] = {**cfg["profile"].get("answers", {}), **(p.get("answers") or {})}
        if p.get("documents_root"):
            cfg["documents_root"] = p["documents_root"]
        if p.get("folders"):
            cfg["folders"] = {**cfg.get("folders", {}), **p["folders"]}
        if p.get("ai"):
            cfg["ai"] = {**cfg["ai"], **{k: v for k, v in p["ai"].items() if k in cfg["ai"]}}
        s.save()
        for k in SECRET_KEYS:
            if p.get("secrets", {}).get(k):
                s.set_secret(k, p["secrets"][k])
        s.documents_root.mkdir(parents=True, exist_ok=True)
        remember_data_dir(s.data_dir)
        state["ctx"] = Ctx(Settings(s.data_dir))
        try:
            state["ctx"].refresh_fx()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "data_dir": str(s.data_dir)}

    @app.get("/config")
    def get_config():
        c = ctx()
        return {**c.settings.public(), "currencies": c.settings.currencies, "rates": c.rates,
                "packs": [pack_summary(p) for p in c.packs.values()], "all_packs": [pack_summary(p) for p in available_packs(c.settings).values()],
                "providers": PROVIDERS, "common_currencies": COMMON_CURRENCIES}

    @app.post("/config")
    def put_config(p: dict = Body(...)):
        c = ctx()
        cfg = c.settings.config
        for k in ("countries", "base_currency", "extra_currencies", "documents_root", "folders"):
            if k in p:
                cfg[k] = p[k]
        if "profile" in p:
            cfg["profile"] = {**cfg["profile"], **p["profile"]}
        if "ai" in p:
            cfg["ai"] = {**cfg["ai"], **p["ai"]}
        if "fx" in p:
            cfg["fx"] = {**cfg["fx"], **p["fx"]}
        if "updates" in p:
            cfg["updates"] = {**cfg.get("updates", {}), "check": bool(p["updates"].get("check", True))}
        c.settings.save()
        for k, v in (p.get("secrets") or {}).items():
            if k in SECRET_KEYS and v:
                c.settings.set_secret(k, v)
        c.reload()
        return get_config()

    @app.post("/config/secret/clear")
    def clear_secret(p: dict = Body(...)):
        need(p.get("key") in SECRET_KEYS, "Unknown key")
        ctx().settings.set_secret(p["key"], "")
        return {"ok": True}

    @app.post("/fx/refresh")
    def fx_refresh():
        try:
            return {"message": ctx().refresh_fx(), "rates": ctx().rates}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Couldn't fetch rates ({type(e).__name__}). Add manual rates in Settings.")

    @app.post("/ai/test")
    def ai_test():
        c = ctx()
        prov = make_provider(c.settings.config["ai"], c.settings.secret)
        need(prov, "AI is off or not fully configured (key, endpoint or model missing).")
        try:
            txt = prov.complete("Reply with exactly: OK, connected.")
        except ProviderError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "reply": txt[:200]}

    # ======================= generic tables =======================
    @app.get("/api/{table}")
    def list_rows(table: str):
        need(table in ctx().db.tables, "Unknown table", 404)
        return ctx().db.list(table, "due IS NULL, due" if table == "calendar" else None)

    @app.post("/api/{table}")
    def save_row(table: str, row: dict = Body(...)):
        need(table in ctx().db.tables and table not in ("documents",), "Unknown table", 404)
        c = ctx()
        if table == "items":
            row["updated"] = date.today().isoformat()
        if table == "paper_trades":
            row.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
            _check_paper_trade(c, row)
        if table in ("transactions", "recurring"):
            _check_money_row(c, table, row)
        if table == "calendar":
            row.setdefault("key", "user:" + datetime.now().strftime("%Y%m%d%H%M%S%f"))
            row.setdefault("source", "yours"); row.setdefault("status", "open")
        rid = c.db.upsert(table, row)
        if table == "recurring":
            ledger.materialize_recurring(c.db)
        return {"id": rid}

    @app.delete("/api/{table}/{row_id}")
    def delete_row(table: str, row_id: int):
        need(table in ctx().db.tables, "Unknown table", 404)
        ctx().db.delete(table, row_id)
        return {"ok": True}

    def _check_money_row(c: Ctx, table: str, row: dict):
        accts = {a["id"]: a for a in c.db.list("accounts")}
        need(int(row.get("account_id") or 0) in accts, "Pick an account first (Money → add an account).")
        need(float(row.get("amount") or 0) > 0, "Amount must be more than zero.")
        if row.get("kind") == "transfer":
            to = int(row.get("to_account_id") or 0)
            need(to in accts and to != int(row["account_id"]), "A transfer needs a different 'to' account.")
            if not row.get("to_amount"):
                try:
                    row["to_amount"] = round(ledger.to_ccy(float(row["amount"]), accts[int(row["account_id"])]["currency"], accts[to]["currency"], c.rates), 2)
                except ValueError as e:
                    raise HTTPException(400, str(e))
        else:
            row["to_account_id"] = row["to_amount"] = None
        if table == "transactions":
            row.setdefault("created", datetime.now().isoformat(timespec="seconds"))

    def _check_paper_trade(c: Ctx, row: dict):
        st = trading.paper_positions(c.db.list("paper_trades"), float(c.db.settings().get("paper_starting_cash", 10000)))
        if row["side"] == "sell":
            held = st["positions"].get(row["ticker"], {}).get("qty", 0)
            need(float(row["qty"]) <= held + 1e-9, f"You only hold {held} of {row['ticker']} — no short-selling in paper mode.")
        else:
            cost = float(row["qty"]) * float(row["price"]) + float(row.get("fee", 1) or 0)
            need(cost <= st["cash"] + 1e-9, f"Not enough pretend cash: need {cost:,.2f}, have {st['cash']:,.2f}.")

    # ======================= position / plan =======================
    @app.get("/calc/position")
    def position():
        c = ctx()
        ledger.materialize_recurring(c.db)
        nw = c.net_worth()
        c.db.snapshot(nw, c.base)
        cal = [d for d in c.calendar() if d["status"] == "open" and d["due"]]
        return {"net_worth": nw, "base": c.base, "rates": c.rates, "currencies": c.settings.currencies,
                "history": _history(c),
                "trackers": [trk.summarize(t) for t in c.trackers], "open_deadlines": cal[:6],
                "packs": {k: pack_summary(v) for k, v in c.packs.items()}}

    @app.get("/calc/goals")
    def goals():
        c = ctx()
        out = []
        for g in c.db.list("goals", "priority, target_date"):
            r = planning.plan_goal(g["name"], g["target_today"], date.fromisoformat(g["target_date"]), g["saved"], g["monthly"],
                                   g["annual_return"], g["inflation"], g["currency"])
            r.update(id=g["id"], priority=g["priority"], note=g["note"])
            out.append(r)
        need_base = 0.0
        for r in out:
            try:
                need_base += c.conv(r["required_monthly"], r["currency"])
            except ValueError:
                pass
        return {"goals": out, "total_required_monthly": round(need_base, 2), "base": c.base}

    @app.get("/calc/cashflow")
    def cashflow():
        c = ctx()
        s = c.db.settings()
        acts = ledger.monthly_actuals(c.db, c.base, c.rates)
        income = float(s.get("monthly_income") or acts["income"] or 0)
        budget = c.db.list("expenses")
        spend = budget or [{"amount": v} for v in acts.get("by_category", {}).values()]
        cf = planning.cash_flow(income, spend, c.net_worth()["liquid"])
        cf["actuals"] = acts
        cf["base"] = c.base
        cf["income_source"] = "your setting" if s.get("monthly_income") else (f"{acts.get('basis', 'recent months')} in Money" if acts["income"] else "not set")
        cf["spend_source"] = "your budget in Plan" if budget else (f"{acts.get('basis', 'recent months')} in Money" if acts["expense"] else "not set")
        return cf

    @app.get("/api-settings")
    def app_settings():
        s = ctx().db.settings()
        return {k: v for k, v in s.items() if not k.startswith("fx_")}

    @app.post("/api-settings")
    def put_app_settings(p: dict = Body(...)):
        for k, v in p.items():
            if k in ("monthly_income", "paper_starting_cash"):
                ctx().db.set_setting(k, v)
        return app_settings()

    # ======================= money =======================
    @app.get("/money/meta")
    def money_meta():
        c = ctx()
        inc, exp, types = list(ledger.DEFAULT_INCOME_CATEGORIES), list(ledger.DEFAULT_EXPENSE_CATEGORIES), list(ledger.DEFAULT_ACCOUNT_TYPES)
        for p in c.packs.values():
            for x in p.get("categories", {}).get("income", []):
                if x not in inc: inc.insert(-1, x)
            for x in p.get("categories", {}).get("expense", []):
                if x not in exp: exp.insert(-1, x)
            for x in p.get("account_types", []):
                if x not in types: types.insert(-1, x)
        return {"income_categories": inc, "expense_categories": exp, "account_types": types, "frequencies": ledger.FREQUENCIES,
                "base": c.base, "currencies": c.settings.currencies, "rates": c.rates,
                "countries": [pack_summary(p) for p in c.packs.values()]}

    @app.get("/money/accounts")
    def money_accounts():
        c = ctx()
        ledger.materialize_recurring(c.db)
        accts = [a for a in ledger.balances(c.db) if not a["archived"]]
        tot = {}
        for a in accts:
            tot[a["currency"]] = round(tot.get(a["currency"], 0) + a["balance"], 2)
        total_base = 0.0
        for k, v in tot.items():
            try:
                total_base += c.conv(v, k)
            except ValueError:
                pass
        rec = []
        for r in c.db.list("recurring"):
            nxt = None
            if r["active"]:
                end = date.fromisoformat(r["end_date"]) if r["end_date"] else None
                for d in ledger.occurrences(date.fromisoformat(r["start_date"]), r["frequency"], date(date.today().year + 2, 12, 31), end):
                    if d > date.today():
                        nxt = d.isoformat(); break
            rec.append(dict(r, next=nxt))
        return {"accounts": accts, "recurring": rec, "totals": tot, "total_base": round(total_base, 2), "base": c.base, "rates": c.rates}

    @app.get("/money/summary")
    def money_summary(period: str = "month", anchor: str | None = None, display: str | None = None, account: int | None = None):
        c = ctx()
        ledger.materialize_recurring(c.db)
        try:
            return ledger.summary(c.db, period, date.fromisoformat(anchor) if anchor else date.today(), display or c.base, c.rates, account)
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ======================= tax & deadlines =======================
    @app.get("/tax/calculators")
    def tax_calcs():
        c = ctx()
        return {"calculators": c.calculators(),
                "checklists": [{"pack": k, "flag": p.get("flag", ""), "name": p.get("name"), "items": p.get("checklist", [])} for k, p in c.packs.items()],
                "glossary": {k: v for p in c.packs.values() for k, v in (p.get("glossary") or {}).items()}}

    @app.post("/tax/run")
    def tax_run(p: dict = Body(...)):
        try:
            return ctx().run_calculator(p["pack"], p["calculator"], p.get("inputs", {}))
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e))

    @app.get("/calendar")
    def calendar():
        return ctx().calendar()

    @app.post("/calendar/status")
    def calendar_status(p: dict = Body(...)):
        return ctx().set_deadline_status(p["key"], p["status"])

    # ======================= rules =======================
    @app.get("/rules")
    def rules():
        c = ctx()
        files = {p.name: p.read_text(encoding="utf-8") for p in sorted(c.settings.rules_dir.glob("*.y*ml"))} if c.settings.rules_dir.exists() else {}
        return {"document_rules": [{k: v for k, v in r.items() if k in ("id", "label", "category", "country", "confidence", "match", "route", "extract", "_source", "tracker")} for r in c.rules.document_rules],
                "deadline_rules": [{k: v for k, v in r.items() if k in ("id", "title", "due", "if", "severity", "country", "_source")} for r in c.rules.deadline_rules],
                "user_files": files, "errors": c.rules.errors, "rules_dir": str(c.settings.rules_dir), "categories": c.rules.categories}

    @app.post("/rules/user")
    def save_user_rules(p: dict = Body(...)):
        c = ctx()
        name = Path(p.get("file") or "my-rules.yaml").name
        need(name.endswith((".yaml", ".yml")), "File must end in .yaml")
        errs = validate_rules_yaml(p.get("text", ""))
        if errs:
            raise HTTPException(400, "; ".join(errs))
        c.settings.rules_dir.mkdir(parents=True, exist_ok=True)
        (c.settings.rules_dir / name).write_text(p.get("text", ""), encoding="utf-8")
        c.reload()
        state["review"].clear()
        return rules()

    @app.post("/rules/test")
    def rules_test(p: dict = Body(...)):
        data = base64.b64decode(p["data"].split(",")[-1])
        a = ctx().rules.analyze(data, Path(p.get("filename") or "file").name)
        a.pop("sha256", None)
        return a

    # ======================= documents =======================
    @app.get("/docs/meta")
    def docs_meta():
        c = ctx()
        root = c.settings.documents_root
        folders = sorted({r["folder"] for r in library(root)} | {c.rules.folder("inbox")})
        return {"categories": c.rules.categories, "folders": folders, "root": str(root)}

    @app.post("/docs/analyze")
    def docs_analyze(p: dict = Body(...)):
        c = ctx()
        name = Path(p.get("filename") or "document").name
        try:
            data = base64.b64decode(p["data"].split(",")[-1])
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Couldn't read the uploaded file.")
        need(len(data) <= 60 * 1024 * 1024, "File is larger than 60 MB.")
        a = c.rules.analyze(data, name)
        if a["confidence"] < 0.6 and a["has_text"]:
            prov = make_provider(c.settings.config["ai"], c.settings.secret)
            if prov:
                a.update(_ai_classify(c, prov, data, name) or {})
        dup = next((d for d in c.db.list("documents") if d["sha256"] == a["sha256"]), None)
        a["duplicate_of"] = dup["stored_path"] if dup else None
        c.settings.inbox_dir.mkdir(parents=True, exist_ok=True)
        (c.settings.inbox_dir / (a["sha256"] + Path(name).suffix.lower())).write_bytes(data)
        return a

    def _ai_classify(c: Ctx, prov, data: bytes, name: str) -> dict | None:
        from .rules.engine import extract_text
        text, _ = extract_text(data, name)
        ids = {r["id"]: r.get("label", r["id"]) for r in c.rules.document_rules}
        prompt = (f"Pick the best document type for this file. File name: {name}\nAllowed ids: {json.dumps(ids)} or 'unknown'.\n"
                  f"Reply with JSON only: {{\"id\": ..., \"reason\": short}}\n\nText:\n{text[:3500]}")
        try:
            import re as _re
            raw = prov.complete(prompt)
            j = json.loads(_re.search(r"\{.*\}", raw, _re.S).group(0))
            rule = next((r for r in c.rules.document_rules if r["id"] == j.get("id")), None)
            if not rule:
                return None
            f = c.rules.fields(text, rule)
            return {"doc_type": rule["id"], "label": rule.get("label"), "category": rule.get("category", "Other"), "country": rule.get("country", ""),
                    "confidence": 0.7, "matched_on": "AI: " + str(j.get("reason", ""))[:120], "fields": f, **c.rules.route(rule, text, name, f)}
        except Exception:  # noqa: BLE001
            return None

    @app.post("/docs/file")
    def docs_file(p: dict = Body(...)):
        c = ctx()
        sha, name = str(p.get("sha256", "")), Path(str(p.get("filename", ""))).name
        need(re.fullmatch(r"[0-9a-f]{64}", sha), "Upload the file again — its reference is invalid.")
        src = next(c.settings.inbox_dir.glob(sha + ".*"), None) if c.settings.inbox_dir.exists() else None
        need(src, "Upload expired — please add the file again.")
        root = c.settings.documents_root
        try:
            tgt = unique_path(safe_target(root, p["folder"], name))
        except ValueError as e:
            raise HTTPException(400, str(e))
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(tgt))
        rel = tgt.relative_to(root).as_posix()
        f = p.get("fields") or {}
        row = {"sha256": sha, "original_name": p.get("original_name") or name, "stored_path": rel, "doc_type": p.get("doc_type"),
               "category": p.get("category"), "country": p.get("country"), "doc_date": (f.get("dates") or [None])[0],
               "amount": f.get("amount"), "currency": f.get("currency"), "fields": json.dumps(f, ensure_ascii=False, default=str),
               "text_excerpt": (p.get("excerpt") or "")[:600], "confidence": p.get("confidence"), "status": "filed",
               "added": datetime.now().isoformat(timespec="seconds")}
        ex = next((d for d in c.db.list("documents") if d["sha256"] == sha), None)
        if ex:
            row["id"] = ex["id"]
        state["review"].clear()
        return {"id": c.db.upsert("documents", row), "path": rel}

    @app.get("/docs/library")
    def docs_library():
        c = ctx()
        meta = {d["stored_path"]: d for d in c.db.list("documents")}
        out = []
        for r in library(c.settings.documents_root):
            m = meta.get(r["path"])
            if m:
                r.update(category=m["category"], doc_type=m["doc_type"], logged=True)
            else:
                rule, conf, _ = c.rules.classify("", r["name"] + " " + r["folder"])
                r.update(category=rule.get("category", "Other") if rule else "Other", doc_type=rule["id"] if rule else None, logged=False)
            out.append(r)
        return out

    @app.get("/docs/review")
    def docs_review():
        c = ctx()
        out, lib = [], library(c.settings.documents_root)
        for r in lib:
            key = (r["path"], r["modified"], r["size"])
            a = state["review"].get(key)
            if a is None:
                a = c.rules.analyze((c.settings.documents_root / r["path"]).read_bytes(), r["name"])
                a.pop("excerpt", None)
                state["review"][key] = a
            if a["confidence"] >= 0.8 and not same_place(r["folder"], a["folder"]):
                out.append({"path": r["path"], "current_folder": r["folder"], "label": a["label"], "category": a["category"],
                            "suggested_folder": a["folder"], "suggested_name": a["filename"], "confidence": a["confidence"], "rule_source": a.get("rule_source")})
        return {"checked": len(lib), "suggestions": out}

    @app.post("/docs/move")
    def docs_move(p: dict = Body(...)):
        c = ctx()
        root = c.settings.documents_root.resolve()
        src = (root / p["path"]).resolve()
        need(root in src.parents and src.is_file(), "Source must be a file inside your documents folder")
        try:
            tgt = unique_path(safe_target(root, p["folder"], Path(p["filename"]).name))
        except ValueError as e:
            raise HTTPException(400, str(e))
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(tgt))
        rel = tgt.relative_to(root).as_posix()
        with c.db.conn() as cn:
            cn.execute("UPDATE documents SET stored_path=? WHERE stored_path=?", (rel, p["path"]))
        state["review"].clear()
        return {"path": rel}

    @app.get("/docs/open")
    def docs_open(path: str):
        root = ctx().settings.documents_root.resolve()
        tgt = (root / path).resolve()
        need(root in tgt.parents and tgt.is_file(), "Not found", 404)
        return FileResponse(tgt)

    # ======================= invest / learn =======================
    def _prices(p: dict):
        if p.get("csv"):
            return trading.prices_from_csv(p["csv"]), "your CSV"
        t = (p.get("ticker") or "DEMO").strip()
        if t.upper() == "DEMO":
            return trading.synthetic_prices(int(p.get("years", 10))), "demo random data (not a real market)"
        try:
            return trading.fetch_prices(t, f"{date.today().year - int(p.get('years', 10))}-01-01"), f"Yahoo Finance ({t})"
        except ImportError:
            raise HTTPException(400, "yfinance isn't installed — use ticker DEMO or upload a CSV")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Couldn't load prices for {t}: {e}")

    @app.post("/calc/backtest")
    def backtest(p: dict = Body(...)):
        prices, src = _prices(p)
        params = {k: int(v) for k, v in (p.get("params") or {}).items() if str(v).strip()}
        r = trading.backtest(prices, p.get("strategy", "sma_cross"), float(p.get("capital", 10000)), float(p.get("cost_pct", 0.001)), params)
        r["source"] = src
        return r

    @app.post("/calc/sip")
    def sip(p: dict = Body(...)):
        prices, src = _prices(p)
        r = trading.sip_backtest(prices, float(p.get("monthly", 500)))
        r["source"] = src
        return r

    @app.get("/calc/paper")
    def paper():
        c = ctx()
        s = c.db.settings()
        trades = c.db.list("paper_trades", "ts")
        st = trading.paper_positions(trades, float(s.get("paper_starting_cash", 10000)))
        marks = {k[5:]: float(v) for k, v in s.items() if k.startswith("mark:")}
        value = st["cash"]
        for t, pos in st["positions"].items():
            px = marks.get(t, pos["avg_cost"])
            pos.update(price=px, value=round(pos["qty"] * px, 2), unrealized=round(pos["qty"] * (px - pos["avg_cost"]), 2))
            value += pos["value"]
        start = float(s.get("paper_starting_cash", 10000))
        st.update(total_value=round(value, 2), start=start, total_return=round(value / start - 1, 4), trades=trades)
        return st

    @app.get("/calc/quote/{ticker}")
    def quote(ticker: str):
        try:
            import yfinance as yf
            return {"ticker": ticker, "price": round(float(yf.Ticker(ticker).history(period="5d")["Close"].dropna().iloc[-1]), 4)}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"No quote for {ticker} ({type(e).__name__}). Enter the price by hand.")

    @app.post("/calc/refresh-prices")
    def refresh_prices():
        c = ctx()
        msgs = []
        try:
            msgs.append(c.refresh_fx())
        except Exception as e:  # noqa: BLE001
            msgs.append(f"Exchange rates not refreshed ({type(e).__name__})")
        try:
            import yfinance as yf
        except ImportError:
            return {"messages": msgs + ["yfinance not installed; prices not refreshed"]}
        for h in c.db.list("holdings"):
            if h["ticker"]:
                try:
                    px = float(yf.Ticker(h["ticker"]).history(period="5d")["Close"].dropna().iloc[-1])
                    h.update(last_price=round(px, 4), price_date=date.today().isoformat())
                    c.db.upsert("holdings", h)
                    msgs.append(f"{h['ticker']} {px:,.2f}")
                except Exception:  # noqa: BLE001
                    msgs.append(f"{h['ticker']}: no price")
        return {"messages": msgs}

    # ======================= chat =======================
    @app.get("/chat/meta")
    def chat_meta():
        c = ctx()
        ai = c.settings.config["ai"]
        prov = make_provider(ai, c.settings.secret)
        return {"ready": prov is not None, "provider": ai["provider"], "provider_label": PROVIDERS.get(ai["provider"], {}).get("label"),
                "model": ai.get("model") or PROVIDERS.get(ai["provider"], {}).get("default_model", ""),
                "models": PROVIDERS.get(ai["provider"], {}).get("models", []), "name": c.settings.config["profile"].get("name", ""),
                "suggestions": _suggestions(c)}

    def _suggestions(c: Ctx) -> list:
        s = [["📊", "Where do I stand financially?", "net worth, cash, what's missing"],
             ["⏰", "Which deadlines should I act on first?", "most urgent first"],
             ["🎯", "How much should I save each month for my goals?", "and am I on track"],
             ["🌱", "What is an ETF savings plan and is it right for me?", "explained for a beginner"]]
        for code, p in c.packs.items():
            s.append([p.get("flag", "🌍"), f"How am I taxed in {p.get('name')}?", "plain-English overview for my situation"])
        for t in c.trackers:
            s.append(["🏗️", f"How much is left to pay on {t.get('name')}?", "and when is the next payment"])
        return s[:8]

    @app.post("/chat/model")
    def chat_model(p: dict = Body(...)):
        c = ctx()
        c.settings.config["ai"]["model"] = p.get("model", "")
        c.settings.save()
        return chat_meta()

    @app.get("/chat/list")
    def chat_list():
        return ctx().db.chat_list()

    @app.get("/chat/{chat_id}")
    def chat_get(chat_id: int):
        return {"id": chat_id, "messages": assistant.display_messages(ctx().db.chat_history(chat_id))}

    @app.delete("/chat/{chat_id}")
    def chat_del(chat_id: int):
        ctx().db.chat_delete(chat_id)
        return {"ok": True}

    @app.post("/chat/send")
    def chat_send(p: dict = Body(...)):
        c = ctx()
        text = (p.get("text") or "").strip()
        need(text, "Empty message")
        try:
            prov = make_provider(c.settings.config["ai"], c.settings.secret)
        except ImportError as e:
            raise HTTPException(400, f"Missing package for this AI provider: {e}")
        need(prov, "Connect an AI provider in Settings → AI first (it's optional — everything else works without it).")
        chat_id = p.get("chat_id") or c.db.chat_create(text[:60] + ("…" if len(text) > 60 else ""))
        history = c.db.chat_history(chat_id)
        um = {"role": "user", "content": text}
        history.append(um)
        c.db.chat_append(chat_id, um)

        def gen():
            yield assistant._sse("chat", {"id": chat_id})
            yield from assistant.chat_stream(prov, c, history, lambda m: c.db.chat_append(chat_id, m))
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ======================= web =======================
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/")
    def index():
        html = (WEB / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("<head>", f'<head>\n<meta name="session-token" content="{token}">', 1))

    return app
