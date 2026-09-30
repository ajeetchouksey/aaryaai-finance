"""Everything the app knows at runtime, built from one data folder. Rebuilt when settings change."""
from __future__ import annotations

from datetime import date

from .config import Settings
from .core import fx, ledger, planning, trackers as trk
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
