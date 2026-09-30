"""Diversification check: what you really own once you look inside funds.

Plain English:
- Adds up accounts (cash), investments and other assets (property, gold, pensions) in your base currency.
  Vehicles and debts are left out: they aren't investments.
- Index funds are opened up using a small built-in list of what common indexes hold (approximate;
  add your own in <data folder>/lookthrough.json). A fund the app doesn't recognise is counted in the
  holding's own country until you set what it tracks.
- Flags concentration against *your* rules (Settings → Diversify rules), compares with your target mix,
  and shows the cheapest way to move towards it: point new savings at what's short before selling anything.

Education and arithmetic, not investment advice: the app never names a fund to buy.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from .fx import convert

LIB_PATH = Path(__file__).resolve().parents[1] / "data" / "lookthrough.json"
CLASSES = ["shares", "bonds", "cash", "property", "gold", "pension", "other"]
CLASS_LABEL = {"shares": "Shares", "bonds": "Bonds", "cash": "Cash", "property": "Property", "gold": "Gold", "pension": "Pensions", "other": "Other"}
DEFAULT_RULES = {"max_single_company": 0.10, "min_cash_months": 6, "max_property": 0.30, "max_sector": 0.30, "max_ter": 0.003, "max_one_country": 0.60}
SKIP_ITEM_CATEGORIES = ("vehicle",)


def load_library(user_path: Path | None = None) -> dict:
    lib = json.loads(LIB_PATH.read_text(encoding="utf-8"))
    if user_path and user_path.exists():
        try:
            u = json.loads(user_path.read_text(encoding="utf-8"))
            lib["indexes"].update(u.get("indexes") or {})
            lib["country_currency"].update(u.get("country_currency") or {})
            lib["country_names"].update(u.get("country_names") or {})
        except (ValueError, AttributeError):
            lib["error"] = "lookthrough.json in your data folder isn't valid JSON — using the built-in list"
    return lib


def match_index(h: dict, lib: dict) -> str | None:
    key = (h.get("lookthrough") or "").strip()
    if key in lib["indexes"]:
        return key
    hay = f" {(h.get('name') or '').lower()} {(h.get('ticker') or '').lower()} "
    best = None
    for k, ix in lib["indexes"].items():
        for word in ix.get("match", []):
            w = word.lower()
            if w in hay and (best is None or len(w) > best[1]):
                best = (k, len(w))
    return best[0] if best else None


def item_class(i: dict) -> str | None:
    if i.get("asset_class"):
        return i["asset_class"]
    c = (i.get("category") or "").lower()
    if any(s in c for s in SKIP_ITEM_CATEGORIES):
        return None
    if "property" in c or "flat" in c or "house" in c or "land" in c:
        return "property"
    if "gold" in c or "valuable" in c:
        return "gold"
    if "pension" in c or "retirement" in c or "provident" in c or "ppf" in c or "epf" in c or "nps" in c:
        return "pension"
    return "other"


def _norm(d: dict) -> dict:
    t = sum(v for v in d.values() if v > 0) or 1
    return {k: v / t for k, v in d.items() if v > 0}


def analyse(accounts: list[dict], holdings: list[dict], items: list[dict], base: str, rates: dict, lib: dict,
            rules: dict | None = None, targets: dict | None = None, monthly_spend: float = 0.0,
            monthly_investable: float = 0.0, tax_on_sale=None) -> dict:
    rules = {**DEFAULT_RULES, **(rules or {})}
    cc, names = lib["country_currency"], lib["country_names"]
    positions = []  # {name, kind, cls, value, country weights, currency weights, sectors, companies}

    def conv(v, c):
        try:
            return convert(v, c, base, rates)
        except ValueError:
            return None

    missing_rates = set()
    for a in accounts:
        if a.get("archived") or not a.get("in_networth", 1) or a["balance"] <= 0:
            continue
        v = conv(a["balance"], a["currency"])
        if v is None:
            missing_rates.add(a["currency"]); continue
        positions.append({"name": a["name"], "kind": "account", "cls": "cash", "value": v, "countries": {a.get("country") or "other": 1},
                          "currencies": {a["currency"]: 1}, "sectors": {}, "companies": {}})
    unknown = []
    for h in holdings:
        price = h.get("last_price") or h.get("avg_cost") or 0
        v = conv((h.get("qty") or 0) * price, h.get("currency") or base)
        if v is None:
            missing_rates.add(h.get("currency")); continue
        if v <= 0:
            continue
        ix_key = match_index(h, lib)
        ix = lib["indexes"].get(ix_key) if ix_key else None
        single = not ix and any(s in (h.get("asset_type") or "").lower() for s in ("stock", "share", "aktie", "equity"))
        cls = (ix or {}).get("asset_class") or h.get("asset_class") or "shares"
        if ix:
            ctry = _norm(ix["countries"])
            cur = defaultdict(float)
            for k, w in ctry.items():
                cur[cc.get(k, "other")] += w
            pos = {"countries": ctry, "currencies": dict(cur), "sectors": _norm(ix.get("sectors", {})),
                   "companies": {k: w / 100 for k, w in ix.get("top", {}).items()}, "tracks": ix["label"]}
        else:
            c = h.get("country") or "other"
            pos = {"countries": {c: 1}, "currencies": {h.get("currency") or base: 1}, "sectors": {"Unclassified": 1} if cls == "shares" else {},
                   "companies": {h["name"]: 1} if single else {}, "tracks": "single company" if single else None}
            if not single and cls == "shares":
                unknown.append(h["name"])
        positions.append({"name": h["name"], "kind": "holding", "cls": cls, "value": v, "id": h.get("id"), "ter": h.get("ter"),
                          "holding": h, **pos})
    for i in items:
        if i.get("kind") != "asset":
            continue
        cls = item_class(i)
        if not cls:
            continue
        v = conv(i["amount"], i["currency"])
        if v is None:
            missing_rates.add(i["currency"]); continue
        positions.append({"name": i["name"], "kind": "item", "cls": cls, "value": v, "countries": {i.get("country") or "other": 1},
                          "currencies": {i["currency"]: 1}, "sectors": {}, "companies": {}})

    total = sum(p["value"] for p in positions) or 0.0
    by_cls, by_ctry, by_cur, by_sec, comp, comp_src = defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(float), defaultdict(set)
    shares_total = 0.0
    for p in positions:
        by_cls[p["cls"]] += p["value"]
        for k, w in p["countries"].items():
            by_ctry[k] += p["value"] * w
        for k, w in p["currencies"].items():
            by_cur[k] += p["value"] * w
        if p["cls"] == "shares":
            shares_total += p["value"]
            for k, w in p["sectors"].items():
                by_sec[k] += p["value"] * w
        for k, w in p["companies"].items():
            comp[k] += p["value"] * w
            comp_src[k].add(p["name"])

    def share(d, tot):
        return [{"key": k, "value": round(v, 2), "share": round(v / tot, 4) if tot else 0} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]

    classes = share(by_cls, total)
    for r in classes:
        r["label"] = CLASS_LABEL.get(r["key"], r["key"])
    countries = share(by_ctry, total)
    for r in countries:
        r["label"] = names.get(r["key"], r["key"])
    currencies = share(by_cur, total)
    sectors = share(by_sec, shares_total)
    companies = [{"name": k, "value": round(v, 2), "share": round(v / total, 4) if total else 0, "via": sorted(comp_src[k])}
                 for k, v in sorted(comp.items(), key=lambda kv: -kv[1])[:12]]

    flags, checks = [], []
    cash = by_cls.get("cash", 0.0)
    months = cash / monthly_spend if monthly_spend else None
    prop = by_cls.get("property", 0.0) / total if total else 0
    top_sector = sectors[0] if sectors else None
    top_country = countries[0] if countries else None
    top_company = companies[0] if companies else None
    biggest_single = max((p for p in positions if p["kind"] != "account"), key=lambda p: p["value"], default=None)
    overlap = [c for c in companies if len(c["via"]) >= 2]

    def check(label, value_text, ok, rule_key):
        checks.append({"label": label, "value": value_text, "ok": ok, "rule": rule_key})

    check(f"No single company above {rules['max_single_company']:.0%}", f"largest {top_company['share']:.1%}" if top_company else "none",
          not top_company or top_company["share"] <= rules["max_single_company"], "max_single_company")
    if months is not None:
        check(f"Cash covers at least {rules['min_cash_months']:g} months of spending", f"{months:.1f} months", months >= rules["min_cash_months"], "min_cash_months")
    check(f"Property at most {rules['max_property']:.0%}", f"{prop:.0%}", prop <= rules["max_property"], "max_property")
    if top_sector:
        check(f"No sector above {rules['max_sector']:.0%} of shares", f"{top_sector['key']} {top_sector['share']:.0%}", top_sector["share"] <= rules["max_sector"], "max_sector")
    if top_country:
        check(f"No country above {rules['max_one_country']:.0%}", f"{names.get(top_country['key'], top_country['key'])} {top_country['share']:.0%}",
              top_country["share"] <= rules["max_one_country"], "max_one_country")
    ters = [(p["ter"], p["value"]) for p in positions if p.get("ter")]
    if ters:
        avg_ter = sum(t * v for t, v in ters) / sum(v for _, v in ters)
        check(f"Fund costs below {rules['max_ter']:.2%} a year", f"{avg_ter:.2%} on average", avg_ter <= rules["max_ter"], "max_ter")

    if biggest_single and total and biggest_single["value"] / total > 0.2:
        flags.append({"tone": "warn", "title": f"{biggest_single['name']} is {biggest_single['value'] / total:.0%} of everything",
                      "detail": "One asset carries a big part of your wealth." + (" Property can't be sold in pieces." if biggest_single["cls"] == "property" else "")})
    if overlap:
        o = overlap[:3]
        flags.append({"tone": "warn", "title": "The same companies through more than one fund",
                      "detail": ", ".join(c["name"] for c in o) + f" add up to {sum(c['share'] for c in o):.1%} of everything, via " + " and ".join(sorted(set().union(*[set(c['via']) for c in o])))})
    for c in checks:
        if not c["ok"]:
            flags.append({"tone": "bad", "title": c["label"], "detail": f"Now: {c['value']}"})
    if unknown:
        flags.append({"tone": "muted", "title": "Not looked inside yet", "detail": ", ".join(unknown) + " — set what each tracks (Invest → edit) to see its countries and sectors."})
    if missing_rates:
        flags.append({"tone": "muted", "title": "Some amounts left out", "detail": "No exchange rate for " + ", ".join(sorted(x for x in missing_rates if x))})

    tgt_rows, gap_under = [], 0.0
    targets = {k: float(v) for k, v in (targets or {}).items() if v not in (None, "")}
    for k in CLASSES:
        if k not in targets and not by_cls.get(k):
            continue
        actual = by_cls.get(k, 0.0) / total if total else 0
        t = targets.get(k)
        gap = (t / 100 - actual) if t is not None else None
        if gap and gap > 0:
            gap_under += gap * total
        tgt_rows.append({"key": k, "label": CLASS_LABEL[k], "target": t, "actual": round(actual, 4), "gap": round(gap, 4) if gap is not None else None,
                         "gap_value": round(gap * total, 2) if gap is not None else None})

    options = []
    if targets and total:
        under = [r for r in tgt_rows if r["gap"] and r["gap"] > 0.005 and r["key"] not in ("property", "pension")]
        over = [r for r in tgt_rows if r["gap"] and r["gap"] < -0.005]
        gap_under = sum(r["gap_value"] for r in under)
        cash_over = next((r for r in over if r["key"] == "cash"), None)
        if cash_over and under and (months is None or months > rules["min_cash_months"]):
            spare = -cash_over["gap_value"]
            if months is not None and monthly_spend:
                spare = min(spare, (months - rules["min_cash_months"]) * monthly_spend)
            if spare > 0:
                options.append({"title": f"Move about {spare:,.0f} {base} of spare cash into " + " and ".join(r["label"].lower() for r in under),
                                "detail": f"Cash is above your target and still covers {rules['min_cash_months']:g}+ months of spending afterwards. No selling, no tax.",
                                "tax": 0.0, "best": True})
        if under and monthly_investable > 0:
            m = gap_under / monthly_investable
            options.append({"title": "Point new savings at " + " and ".join(r["label"].lower() for r in under),
                            "detail": f"{monthly_investable:,.0f} {base} a month closes the gap in about {m:.0f} months. No selling, no tax.",
                            "tax": 0.0, "best": not options})
        elif under:
            options.append({"title": "Point new savings at " + " and ".join(r["label"].lower() for r in under),
                            "detail": "Set how much you invest each month (below) to see how long it takes. No selling, no tax.",
                            "tax": 0.0, "best": not options})
        if over and tax_on_sale:
            for r in [o for o in over if o["key"] not in ("cash", "property", "pension")]:
                sell = -r["gap_value"]
                cands = sorted([p for p in positions if p["cls"] == r["key"] and p["kind"] == "holding"], key=lambda p: -p["value"])
                if not cands:
                    continue
                p = cands[0]
                amt = min(sell, p["value"])
                tax, note = tax_on_sale(p["holding"], amt)
                options.append({"title": f"Sell {amt:,.0f} {base} of {p['name']}", "detail": note, "tax": round(tax, 2), "best": False})
    return {"base": base, "total": round(total, 2), "classes": classes, "countries": countries, "currencies": currencies,
            "sectors": sectors, "companies": companies, "overlap": overlap, "flags": flags, "checks": checks,
            "targets": tgt_rows, "options": options, "rules": rules, "cash_months": round(months, 1) if months is not None else None,
            "positions": [{k: v for k, v in p.items() if k != "holding"} for p in positions], "library_error": lib.get("error"),
            "as_of": date.today().isoformat()}
