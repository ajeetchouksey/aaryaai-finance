"""Tax calculators. The formulas live here; every number (rates, brackets, allowances)
comes from the country pack's `calculators[].params`, so updating a rate is a YAML edit.

Each engine returns:
  {"headline": "...", "headline_label": "...", "tone": "good|bad|neutral",
   "rows": [[label, value], ...], "table": {"columns": [...], "rows": [[...]]} (optional),
   "explanation": "plain English"}
"""
from __future__ import annotations

import math
from datetime import date

from ..core.planning import fmt

ENGINES = {}


def engine(name):
    def deco(fn):
        ENGINES[name] = fn
        return fn
    return deco


def run(name: str, params: dict, inputs: dict, currency: str) -> dict:
    if name not in ENGINES:
        raise ValueError(f"Unknown calculator engine '{name}'. Available: {', '.join(sorted(ENGINES))}")
    return ENGINES[name](params or {}, inputs or {}, currency)


def _n(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _b(v) -> bool:
    return v in (True, 1, "1", "true", "on", "yes")


def progressive(income: float, slabs: list) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in slabs:
        up = math.inf if upper is None else float(upper)
        if income > lower:
            tax += (min(income, up) - lower) * float(rate)
        lower = up
    return tax


# ---------------------------------------------------------------- generic
@engine("slabs")
def slabs_engine(p, i, ccy):
    income = max(_n(i.get("income")) - _n(p.get("allowance")), 0)
    tax = progressive(income, p["slabs"])
    avg = tax / income if income else 0
    return {"headline": fmt(tax, ccy), "headline_label": "Estimated income tax", "tone": "neutral",
            "rows": [["Taxable income", fmt(income, ccy)], ["Average rate", f"{avg:.1%}"]],
            "explanation": f"On {fmt(income, ccy)} of taxable income the brackets give about {fmt(tax, ccy)} ({avg:.1%} on average)."}


# ---------------------------------------------------------------- Germany
def de_income_tax(zve: float, tariff: list) -> int:
    gfb, z2, a2, z3, a3, c3, c4, z4, c5 = tariff
    x = math.floor(max(zve, 0))
    if x <= gfb:
        t = 0.0
    elif x <= z2:
        y = (x - gfb) / 10000
        t = (a2 * y + 1400) * y
    elif x <= z3:
        z = (x - z2) / 10000
        t = (a3 * z + 2397) * z + c3
    elif x <= z4:
        t = 0.42 * x - c4
    else:
        t = 0.45 * x - c5
    return math.floor(t)


def _tariff(p, year):
    t = p["tariffs"]
    return t.get(year) or t.get(str(year)) or t[max(t, key=lambda k: int(k))]


@engine("de_32a_refund")
def de_refund(p, i, ccy):
    year = int(i.get("year") or 2025)
    joint, church = _b(i.get("joint")), _b(i.get("church"))
    tariff = _tariff(p, year)
    gross = _n(i.get("gross"))
    wk = max(_n(i.get("werbungskosten")), _n(p.get("workers_allowance", 1230)))
    zve = max(gross - wk - _n(i.get("vorsorge")) - _n(i.get("other")), 0)
    est = 2 * de_income_tax(zve / 2, tariff) if joint else de_income_tax(zve, tariff)
    fg = p.get("soli_freigrenze", {})
    free = _n(fg.get(year) or fg.get(str(year)) or 0) * (2 if joint else 1)
    soli = 0.0 if est <= free else round(min(0.055 * est, 0.119 * (est - free)), 2)
    kist = round(est * _n(p.get("church_rate", 0.09)), 2) if church else 0.0
    total = est + soli + kist
    withheld = _n(i.get("lohnsteuer")) + _n(i.get("soli_paid"))
    refund = round(withheld - total, 2)
    nxt = (2 * de_income_tax((zve + 100) / 2, tariff) if joint else de_income_tax(zve + 100, tariff)) - est
    return {"headline": fmt(abs(refund), ccy), "headline_label": "Estimated refund" if refund >= 0 else "Estimated back-payment",
            "tone": "good" if refund >= 0 else "bad",
            "rows": [["Taxable income (zvE)", fmt(zve, ccy)], ["Income tax", fmt(est, ccy)], ["Soli", fmt(soli, ccy)],
                     ["Church tax", fmt(kist, ccy)], ["Withheld by employer", fmt(withheld, ccy)],
                     ["Average rate", f"{(total / zve if zve else 0):.1%}"], ["Marginal rate", f"{nxt / 100:.0%}"]],
            "explanation": (f"Taxable income comes out at {fmt(zve, ccy)}. Tax on that is about {fmt(total, ccy)}; "
                            f"{fmt(withheld, ccy)} was withheld. Each extra €100 of deductions saves about €{nxt:.0f}. "
                            "Rough estimate — ELSTER will differ for child allowances, insurance caps and foreign income."),
            "data": {"zve": zve, "tax": total, "withheld": withheld, "refund": refund, "avg_rate": round(total / zve, 4) if zve else 0.0,
                     "marginal": round(nxt / 100, 4)}}


@engine("de_capital")
def de_capital(p, i, ccy):
    gains, joint, church = _n(i.get("gains")), _b(i.get("joint")), _b(i.get("church"))
    allowance = _n(p.get("allowance_single", 1000)) * (2 if joint else 1)
    base = gains * (1 - _n(p.get("equity_fund_exempt", 0.3))) if _b(i.get("equity_etf")) else gains
    taxable = max(base - allowance, 0)
    rate, cr = _n(p.get("rate", 0.25)), _n(p.get("church_rate", 0.09))
    abg = taxable * (rate / (1 + rate * cr) if church else rate)
    kist = abg * cr if church else 0
    sol = abg * _n(p.get("soli", 0.055))
    total = abg + sol + kist
    return {"headline": fmt(total, ccy), "headline_label": "Tax on investment income", "tone": "neutral",
            "rows": [["Taxable after allowance", fmt(taxable, ccy)], ["Abgeltungsteuer", fmt(abg, ccy)], ["Soli", fmt(sol, ccy)], ["Church tax", fmt(kist, ccy)]],
            "explanation": f"Investment income is taxed at a flat ~26.4%. The first {fmt(allowance, ccy)} a year is tax-free if you've given your banks a Freistellungsauftrag."}


# ---------------------------------------------------------------- India
def _in_regime(p, i, regime):
    salary, other = _n(i.get("salary")), _n(i.get("other_income"))
    resident = _b(i.get("resident"))
    std = _n(p["std_deduction"][regime]) if salary > 0 else 0
    caps = p.get("caps", {})
    ded = 0.0
    if regime == "old":
        ded = (min(_n(i.get("ded_80c")), _n(caps.get("c80", 150000))) + min(_n(i.get("ded_80d")), _n(caps.get("d80", 25000)))
               + min(_n(i.get("home_loan_interest")), _n(caps.get("home_loan_interest", 200000))))
    normal = max(max(salary - std, 0) + other - ded, 0)
    base = progressive(normal, p["new_slabs" if regime == "new" else "old_slabs"])
    cg = p.get("capital_gains", {})
    st, lt = _n(i.get("stcg_equity")), _n(i.get("ltcg_equity"))
    cgt = st * _n(cg.get("stcg_equity", 0.2)) + max(lt - _n(cg.get("ltcg_exempt", 125000)), 0) * _n(cg.get("ltcg_equity", 0.125))
    limit, cap = p["rebate"][regime]
    rebate = min(base, cap) if resident and normal <= limit else 0
    tax = base - rebate + cgt
    total_income = normal + st + lt
    sr = 0 if total_income <= 5e6 else .10 if total_income <= 1e7 else .15 if total_income <= 2e7 else .25 if (total_income <= 5e7 or regime == "new") else .37
    sur = tax * sr
    cess = (tax + sur) * _n(p.get("cess", 0.04))
    return {"taxable": normal, "slab": base, "rebate": rebate, "cg": cgt, "sur": sur, "cess": cess, "total": round(tax + sur + cess)}


@engine("in_regimes")
def in_regimes(p, i, ccy):
    n, o = _in_regime(p, i, "new"), _in_regime(p, i, "old")
    better = "new" if n["total"] <= o["total"] else "old"
    saving = abs(n["total"] - o["total"])
    rows = [["Taxable income", "taxable"], ["Slab tax", "slab"], ["Rebate 87A", "rebate"], ["Capital-gains tax", "cg"],
            ["Surcharge", "sur"], ["Cess", "cess"], ["Total", "total"]]
    expl = f"The {better.upper()} regime saves {fmt(saving, ccy)}. "
    if not _b(i.get("resident")):
        expl += "As a non-resident you don't get the 87A rebate, and only Indian-source income counts here. "
    expl += "Your deductions don't beat the new regime's lower rates." if better == "new" else "Your deductions outweigh the new regime's lower rates."
    return {"headline": f"{better.title()} regime", "headline_label": f"saves {fmt(saving, ccy)}", "tone": "good",
            "table": {"columns": ["", "New", "Old"], "rows": [[l, fmt(n[k], ccy), fmt(o[k], ccy)] for l, k in rows]},
            "rows": [], "explanation": expl,
            "data": {"new_total": n["total"], "old_total": o["total"], "best_total": min(n["total"], o["total"]), "better_new": better == "new",
                     "saving": saving}}


@engine("in_property_tds")
def in_property_tds(p, i, ccy):
    price, inst = _n(i.get("consideration")), _n(i.get("instalment"))
    applies = price >= _n(p.get("threshold", 5e6))
    tds = round(inst * _n(p.get("rate", 0.01))) if applies else 0
    paid = i.get("paid_on")
    due = None
    if paid:
        d = date.fromisoformat(paid)
        nm = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        due = date.fromordinal(nm.toordinal() + 29)
    return {"headline": fmt(tds, ccy), "headline_label": "TDS to deposit" if applies else "No TDS needed", "tone": "neutral",
            "rows": [["Pay the seller", fmt(inst - tds, ccy)], ["Deposit as TDS", fmt(tds, ccy)]] + ([["Deposit by", due.strftime("%d %b %Y")]] if due else []),
            "explanation": ("Deduct 1% of the instalment (excluding GST), pay the seller the rest, deposit the TDS with Form 141 / 26QB "
                            "within 30 days of the end of the month you paid, then give the seller Form 16B.") if applies else
                           "Below the threshold — no TDS on property purchase applies."}
