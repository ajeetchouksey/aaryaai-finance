"""Everything the app knows at runtime, built from one data folder. Rebuilt when settings change."""
from __future__ import annotations

import json
from datetime import date, datetime

from .config import Settings
from .core import forecast as fc, fx, ledger, odds as od, planning, portfolio as pf, trackers as trk
from .core.db import DB
from . import model as M
from .packs import load_packs
from .rules.engine import RuleSet
from .tax import engines


class Ctx:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = None
        self.secrets_moved = settings.migrate_secrets()
        self.reload()

    def reload(self):
        self.packs = load_packs(self.settings)
        self.trackers = trk.load_trackers(self.settings.trackers_dir)
        self.rules = RuleSet(self.settings, self.packs, self.trackers)
        model, errors = self.build_model()
        if self.db is None or self.db.model != model:
            try:
                db = DB(self.settings.db_path, model, self.settings.backups_dir)
            except Exception as e:  # noqa: BLE001 — a bad model.json must never stop the app from starting
                if not self.settings.model_path.exists():
                    raise
                model, errors = self.build_model(use_user=False)
                errors.append(f"model.json couldn't be applied and is ignored until you fix it (Settings → Custom fields): {M.friendly_error(e)}")
                db = DB(self.settings.db_path, model, self.settings.backups_dir)
            self.db = db
        self.model, self.model_errors = model, errors

    def build_model(self, use_user: bool = True) -> tuple[dict, list[str]]:
        pack_models = [(f"{p.get('name', code)} pack", p["model"]) for code, p in self.packs.items() if p.get("model")]
        user, errs = None, []
        mp = self.settings.model_path
        if use_user and mp.exists():
            try:
                import json
                user = json.loads(mp.read_text(encoding="utf-8"))
            except ValueError as e:
                errs.append(f"model.json isn't valid JSON: {e}")
        model, merrs = M.build(pack_models, user)
        return model, errs + merrs

    # ---------------- money basics
    @property
    def base(self) -> str:
        return self.settings.config["base_currency"]

    @property
    def rates(self) -> dict:
        r = fx.get_rates(self.db, self.base)
        cfg = self.settings.config.get("fx", {})
        manual_wins = cfg.get("source") == "manual"
        for k, v in (cfg.get("manual_rates") or {}).items():
            if v and (manual_wins or k not in r):
                r[k] = float(v)
        return r

    def conv(self, amount, frm, to=None):
        return fx.convert(amount, frm, to or self.base, self.rates)

    def refresh_fx(self) -> str:
        if self.settings.config.get("fx", {}).get("source") == "manual":
            return "Using your manual exchange rates (Settings → Currencies)"
        cur = self.settings.currencies
        rates, d = fx.fetch_ecb(self.base, cur)
        fx.set_rates(self.db, self.base, rates, d)
        missing = [c for c in cur if c != self.base and c not in rates and c not in (self.settings.config["fx"].get("manual_rates") or {})]
        return f"Rates from the European Central Bank ({d})" + (f"; add manual rates for {', '.join(missing)}" if missing else "")

    # ---------------- net worth
    def account_items(self) -> list[dict]:
        out = []
        for a in ledger.balances(self.db):
            if a["archived"] or not a["in_networth"]:
                continue
            b = a["balance"]
            out.append({"name": a["name"], "kind": "asset" if b >= 0 else "liability", "category": f"Accounts · {a['type']}",
                        "amount": abs(b), "currency": a["currency"], "liquid": 1 if (a["liquid"] and b >= 0) else 0})
        return out

    def holding_items(self) -> list[dict]:
        return [{"name": h["name"], "kind": "asset", "category": f"Investments · {h['asset_type']}",
                 "amount": (h["qty"] or 0) * (h["last_price"] or h["avg_cost"] or 0), "currency": h["currency"], "liquid": 0}
                for h in self.db.list("holdings")]

    def all_items(self) -> list[dict]:
        return self.db.list("items") + self.account_items() + self.holding_items()

    def net_worth(self) -> dict:
        try:
            return planning.net_worth(self.all_items(), self.base, self.rates)
        except ValueError as e:
            items = [i for i in self.all_items() if i["currency"] in self.rates]
            nw = planning.net_worth(items, self.base, self.rates)
            nw["warning"] = str(e)
            return nw

    # ---------------- deadlines
    def calendar(self) -> list[dict]:
        answers = self.settings.config["profile"].get("answers", {})
        gen = self.rules.deadlines(answers)
        rows = {r["key"]: r for r in self.db.list("calendar")}
        out = []
        for g in gen:
            st = rows.get(g["key"], {}).get("status", "open")
            out.append({**g, "status": st, "origin": "rule"})
        for r in rows.values():
            if (r.get("source") or "").startswith("rule:"):
                continue
            out.append({"key": r["key"], "rule_id": None, "due": r["due"], "country": r["country"], "title": r["title"], "detail": r["detail"],
                        "severity": r["severity"], "source": r["source"], "status": r["status"], "origin": "yours", "id": r["id"]})
        return sorted(out, key=lambda x: (x["due"] is None, x["due"] or ""))

    def set_deadline_status(self, key: str, status: str) -> dict:
        with self.db.conn() as c:
            n = c.execute("UPDATE calendar SET status=? WHERE key=?", (status, key)).rowcount
            if not n:
                g = next((x for x in self.rules.deadlines(self.settings.config["profile"].get("answers", {})) if x["key"] == key), None)
                if not g:
                    return {"error": "no such deadline"}
                c.execute("INSERT INTO calendar (due,country,title,detail,severity,status,source,key) VALUES (?,?,?,?,?,?,?,?)",
                          (g["due"], g["country"], g["title"], g["detail"], g["severity"], status, "rule:" + g["rule_id"], key))
        return {"ok": True, "key": key, "status": status}

    # ---------------- calculators
    def calculators(self) -> list[dict]:
        answers = self.settings.config["profile"].get("answers", {})
        out = []
        for code, p in self.packs.items():
            for c in p.get("calculators", []) or []:
                inputs = []
                for f in c.get("inputs", []):
                    f = dict(f)
                    fa = f.get("from_answer")
                    if fa:
                        f["default"] = (not answers.get(fa[1:])) if fa.startswith("!") else bool(answers.get(fa))
                    inputs.append(f)
                out.append({"pack": code, "flag": p.get("flag", ""), "country": p.get("name"), "currency": p.get("currency"),
                            "id": c["id"], "title": c.get("title", c["id"]), "inputs": inputs, "help": c.get("help", "")})
        return out

    def run_calculator(self, pack: str, calc_id: str, inputs: dict) -> dict:
        p = self.packs.get(pack)
        if not p:
            raise ValueError(f"Country pack {pack} is not switched on")
        c = next((x for x in p.get("calculators", []) if x["id"] == calc_id), None)
        if not c:
            raise ValueError(f"No calculator {calc_id} in pack {pack}")
        return engines.run(c["engine"], c.get("params", {}), inputs, p.get("currency", self.base))

    # ---------------- snapshot for the assistant
    def snapshot(self) -> dict:
        from .core import planning as pl
        nw = self.net_worth()
        goals = []
        for g in self.db.list("goals", "priority, target_date"):
            r = pl.plan_goal(g["name"], g["target_today"], date.fromisoformat(g["target_date"]), g["saved"], g["monthly"],
                             g["annual_return"], g["inflation"], g["currency"])
            goals.append({"id": g["id"], "name": g["name"], "currency": g["currency"], "target_today": g["target_today"],
                          "target_date": g["target_date"], "required_monthly": r["required_monthly"], "status": r["verdict"]})
        return {"base_currency": self.base, "rates_per_1_base": {k: v for k, v in self.rates.items() if not k.startswith("_")},
                "net_worth": nw,
                "accounts": [{k: a[k] for k in ("id", "name", "country", "currency", "type", "balance")} for a in ledger.balances(self.db) if not a["archived"]],
                "other_assets_and_debts": [{k: i[k] for k in ("id", "name", "kind", "category", "amount", "currency")} for i in self.db.list("items")],
                "holdings": self.db.list("holdings"), "goals": goals,
                "this_month": {k: v for k, v in ledger.summary(self.db, "month", date.today(), self.base, self.rates).items()
                               if k in ("income", "expense", "net", "by_category")},
                "trackers": [trk.summarize(t) for t in self.trackers], "today": date.today().isoformat()}

    # ================================================================ planning services (shared by screens, routines, MCP)
    def accounts_with_balance(self) -> list[dict]:
        ledger.materialize_recurring(self.db)
        return [a for a in ledger.balances(self.db) if not a["archived"]]

    def floors(self) -> dict:
        out = {}
        for k, v in self.db.settings().items():
            if k.startswith("floor:") and str(v).strip() not in ("", "None"):
                try:
                    out[k[6:]] = float(v)
                except ValueError:
                    pass
        return out

    def forecast(self, scenario: str = "base", months: int = 12) -> dict:
        return fc.forecast(self.accounts_with_balance(), self.db.list("recurring"), self.db.list("planned", "date"), self.trackers,
                           self.db.list("transactions"), self.rates, self.base, self.floors(), months, scenario=scenario)

    def monthly_spend(self) -> float:
        """Typical monthly spending in the base currency: your budget if set, otherwise recent months in Money."""
        budget = self.db.list("expenses")
        if budget:
            return float(sum(e["amount"] for e in budget))
        return float(ledger.monthly_actuals(self.db, self.base, self.rates).get("expense") or 0)

    def monthly_income(self) -> float:
        s = self.db.settings()
        return float(s.get("monthly_income") or ledger.monthly_actuals(self.db, self.base, self.rates).get("income") or 0)

    def goal_odds(self, whatif: bool = True) -> dict:
        goals = self.db.list("goals", "priority, target_date")
        key = json.dumps([goals, whatif, date.today().isoformat(), self.base, self.rates.get("_date"), len(self.db.list("expenses")), len(self.db.list("transactions")), self.db.settings().get("monthly_income")], default=str, sort_keys=True)
        cache = getattr(self, "_odds_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        res = self._goal_odds(goals, whatif)
        self._odds_cache = (key, res)
        return res

    def _goal_odds(self, goals: list, whatif: bool) -> dict:
        out = []
        for g in goals:
            o = od.odds(g)
            need85 = od.monthly_for(g, 0.85) if o["probability"] < 0.85 else None
            try:
                monthly_base = self.conv(g["monthly"] or 0, g["currency"])
            except ValueError:
                monthly_base = None
            out.append({"id": g["id"], "name": g["name"], "currency": g["currency"], "target_today": g["target_today"],
                        "target_date": g["target_date"], "saved": g["saved"], "monthly": g["monthly"], "monthly_base": monthly_base,
                        "priority": g["priority"], "risk_set": g.get("risk"), **o, "monthly_for_85": need85,
                        "odds_at_85": od.odds(g, monthly=need85)["probability"] if need85 else None,
                        "glide": od.glide_path(g["target_date"]) if o["risk"] == "glide" else None})
        income, spend = self.monthly_income(), self.monthly_spend()
        surplus = income - spend
        alloc = [{"label": g["name"], "amount": round(g["monthly_base"] or 0, 2), "goal_id": g["id"]} for g in out if g["monthly_base"]]
        rest = surplus - sum(a["amount"] for a in alloc)
        return {"goals": out, "base": self.base, "income": round(income, 2), "spend": round(spend, 2), "surplus": round(surplus, 2),
                "allocation": alloc, "unallocated": round(rest, 2),
                "whatif": od.whatif(goals) if (whatif and goals) else [], "runs": od.RUNS}

    def diversify(self) -> dict:
        from .tax.opportunities import tax_on_sale
        s = self.db.settings()
        lib = pf.load_library(self.settings.data_dir / "lookthrough.json")
        rules = json.loads(s.get("diversify_rules") or "{}")
        targets = json.loads(s.get("alloc_targets") or "{}")
        try:
            used_de = float(s.get("de_allowance_used") or 0)
        except ValueError:
            used_de = 0.0

        def sale_tax(h, amount_base):
            try:
                amt = self.conv(amount_base, self.base, h.get("currency") or self.base)
            except ValueError:
                return 0.0, "no exchange rate"
            t, note = tax_on_sale(self.packs, h, amt, used_allowance=used_de)
            try:
                return self.conv(t, h.get("currency") or self.base), note
            except ValueError:
                return 0.0, note
        out = pf.analyse(self.accounts_with_balance(), self.db.list("holdings"), self.db.list("items"), self.base, self.rates, lib,
                         rules, targets, self.monthly_spend(), float(s.get("monthly_investable") or 0), sale_tax)
        out["monthly_investable"] = float(s.get("monthly_investable") or 0)
        return out

    def opportunities(self) -> dict:
        from .tax import opportunities as op
        data = op.Data(date.today(), self.base, self.rates, self.settings.config["profile"].get("answers", {}),
                       self.accounts_with_balance(), self.db.list("holdings"), self.db.settings())
        cards, errors = op.run_all(self.packs, data)
        return {"cards": cards, "errors": errors, "base": self.base,
                "total_base": round(sum(c["effect_base"] for c in cards if c["effect_base"] > 0), 2),
                "inputs": {"in_ltcg_used": data.settings.get("in_ltcg_used", "")}}

    def tax_workspace(self, country: str, year: int | None = None) -> dict:
        from .tax import workspace as tw
        p = self.packs.get(country)
        if not p or not p.get("tax_workspace"):
            raise ValueError(f"No tax workspace for {country}")
        kind = p["tax_workspace"].get("year", "calendar")
        year = int(year or tw.default_year(kind))
        row = next((r for r in self.db.list("tax_years") if r["country"] == country and r["year"] == year), None)
        saved = json.loads(row["answers"]) if row and row.get("answers") else {}
        calcs = {c["id"]: c for c in p.get("calculators", [])}

        def run_calc(cid, inputs):
            return self.run_calculator(country, cid, inputs) if cid in calcs else {}
        ws = tw.build(p, year, saved, self.known_documents(), self.settings.config["profile"].get("answers", {}), run_calc)
        ws["years"] = [tw.default_year(kind) - i for i in range(0, 4)]
        return ws

    def known_documents(self) -> list[dict]:
        """Filed documents from the database plus files already in your documents folder (recognised by name)."""
        from .rules.engine import library
        docs = self.db.list("documents")
        seen = {d["stored_path"] for d in docs}
        try:
            lib = library(self.settings.documents_root)
        except OSError:
            lib = []
        for r in lib:
            if r["path"] in seen:
                continue
            rule, _, _ = self.rules.classify("", r["name"] + " " + r["folder"])
            if rule:
                docs.append({"stored_path": r["path"], "original_name": r["name"], "doc_type": rule["id"], "fields": {}, "doc_date": None})
        return docs

    def save_tax_answers(self, country: str, year: int, answers: dict) -> None:
        row = next((r for r in self.db.list("tax_years") if r["country"] == country and r["year"] == int(year)), None)
        cur = json.loads(row["answers"]) if row and row.get("answers") else {}
        cur.update({k: v for k, v in answers.items() if isinstance(k, str) and len(k) < 60})
        self.db.upsert("tax_years", {**({"id": row["id"]} if row else {}), "country": country, "year": int(year),
                                     "answers": json.dumps(cur, ensure_ascii=False), "updated": datetime.now().isoformat(timespec="seconds")})

    # ================================================================ proposals & audit
    def audit(self, actor: str, action: str, detail: str = "") -> None:
        try:
            self.db.upsert("audit", {"ts": datetime.now().isoformat(timespec="seconds"), "actor": actor, "action": action, "detail": detail[:500]})
        except Exception:  # noqa: BLE001 — logging must never break the action it records
            pass

    def propose(self, key: str, source: str, title: str, detail: str = "", effect: str = "", action: dict | None = None) -> int | None:
        """Add a proposal once. A pending one with the same key is refreshed; decided ones are left alone."""
        ex = next((p for p in self.db.list("proposals") if p["key"] == key), None)
        row = {"key": key, "source": source, "title": title, "detail": detail, "effect": effect,
               "action": json.dumps(action or {"type": "note"}, ensure_ascii=False)}
        if ex:
            if ex["status"] != "pending":
                return None
            return self.db.upsert("proposals", {"id": ex["id"], **row})
        return self.db.upsert("proposals", {**row, "status": "pending", "created": datetime.now().isoformat(timespec="seconds")})

    def decide(self, pid: int, decision: str, actor: str = "You") -> dict:
        p = self.db.get("proposals", pid)
        if not p or p["status"] != "pending":
            raise ValueError("This proposal was already decided or no longer exists.")
        result = ""
        if decision == "approve":
            a = json.loads(p.get("action") or "{}") if isinstance(p.get("action"), str) else (p.get("action") or {})
            t = a.get("type")
            if t == "set_goal_monthly":
                g = self.db.get("goals", a["goal_id"])
                if not g:
                    raise ValueError("That goal no longer exists.")
                self.db.upsert("goals", {"id": g["id"], "monthly": a["monthly"]})
                result = f"{g['name']}: saving set to {a['monthly']:,.0f} {g['currency']} a month"
            elif t == "add_planned":
                rid = self.db.upsert("planned", a["row"])
                result = f"planned item #{rid} added"
            elif t == "add_deadline":
                row = {"status": "open", "source": "proposal", "severity": "normal", **a["row"]}
                row.setdefault("key", "proposal:" + p["key"])
                if not any(c["key"] == row["key"] for c in self.db.list("calendar")):
                    self.db.upsert("calendar", row)
                result = "deadline added"
            elif t == "add_transaction":
                row = dict(a["row"])
                row.setdefault("created", datetime.now().isoformat(timespec="seconds"))
                rid = self.db.upsert("transactions", row)
                result = f"transaction #{rid} added"
            else:
                result = "noted"
        self.db.upsert("proposals", {"id": pid, "status": "approved" if decision == "approve" else "skipped",
                                     "decided": datetime.now().isoformat(timespec="seconds")})
        self.audit(actor, ("Approved: " if decision == "approve" else "Skipped: ") + p["title"], result)
        return {"ok": True, "result": result}
