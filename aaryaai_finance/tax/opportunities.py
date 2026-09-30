"""Tax-aware opportunities: allowances, holding periods and deadlines you'd otherwise miss.

Each country pack lists which checks apply (an `opportunities:` section in pack.yaml) with their
parameters; the checks themselves are small deterministic functions here. Every card names the rule
that produced it. These are tax facts about your own holdings and accounts — never a tip to buy or
sell a particular investment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..core.fx import convert
from ..core.planning import fmt

ENGINES = {}


def engine(name):
    def deco(fn):
        ENGINES[name] = fn
        return fn
    return deco


@dataclass
class Data:
    today: date
    base: str
    rates: dict
    answers: dict
    accounts: list          # with balance and pack fields (de_freistellungsauftrag, de_capital_income_ytd, ...)
    holdings: list
    settings: dict          # app settings (key/value)
    extra: dict = field(default_factory=dict)

    def to_base(self, v, ccy):
        try:
            return convert(v, ccy, self.base, self.rates)
        except ValueError:
            return None


def _n(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _value(h) -> float:
    return _n(h.get("qty")) * _n(h.get("last_price") or h.get("avg_cost"))


def _gain(h) -> float:
    return _n(h.get("qty")) * (_n(h.get("last_price") or h.get("avg_cost")) - _n(h.get("avg_cost")))


def india_fy_end(d: date) -> date:
    return date(d.year + (1 if d.month >= 4 else 0), 3, 31)


def card(rule, country, title, why, deadline, effect, effect_value, ccy, data: Data, tone="lilac", extra=None, caveat=""):
    return {"id": f"{rule}", "rule": rule, "country": country, "title": title, "why": why,
            "deadline": deadline.isoformat() if isinstance(deadline, date) else deadline, "effect": effect,
            "effect_value": round(effect_value, 2), "effect_ccy": ccy, "effect_base": round(data.to_base(effect_value, ccy) or 0, 2),
            "tone": tone, "extra": extra or {}, "caveat": caveat}


# ---------------------------------------------------------------- India
def _in_equity(h) -> bool:
    return (h.get("currency") == "INR" or h.get("country") == "IN") and (h.get("asset_class") or "shares") == "shares"


@engine("in_ltcg_harvest")
def in_ltcg_harvest(p, d: Data):
    exempt, rate, months = _n(p.get("ltcg_exempt", 125000)), _n(p.get("ltcg_rate", 0.125)), int(p.get("long_term_months", 12))
    cutoff = d.today - timedelta(days=round(months * 365 / 12))
    lt = [h for h in d.holdings if _in_equity(h) and h.get("bought") and date.fromisoformat(h["bought"]) <= cutoff and _gain(h) > 0]
    if not lt:
        return []
    gains = sum(_gain(h) for h in lt)
    used = _n(d.settings.get("in_ltcg_used"))
    room = max(exempt - used, 0)
    harvest = min(room, gains)
    if harvest < 1000:
        return []
    caveat = ("You're set up as non-resident in India: check how your tax treaty treats these gains, and that selling "
              "doesn't trigger tax where you live, before acting.") if d.answers.get("in_nri") else ""
    return [card("in.ltcg_harvest", "IN", "India · use this year's tax-free gains allowance",
                 f"Long-term gains on Indian equity funds are tax-free up to {fmt(exempt, 'INR')} a year. "
                 f"You've entered {fmt(used, 'INR')} used so far. Selling units with {fmt(harvest, 'INR')} of gains and "
                 f"buying them back raises your cost price, so that much of today's gain is never taxed later. "
                 f"Exit loads and costs still apply.",
                 india_fy_end(d.today), f"≈ {fmt(harvest * rate, 'INR')} less tax later", harvest * rate, "INR", d,
                 extra={"kind": "progress", "used": used, "room": room, "total": exempt, "ccy": "INR",
                        "holdings": [h["name"] for h in lt]}, caveat=caveat)]


@engine("in_short_to_long")
def in_short_to_long(p, d: Data):
    months, window = int(p.get("long_term_months", 12)), int(p.get("window_days", 60))
    stcg, ltcg = _n(p.get("stcg_rate", 0.20)), _n(p.get("ltcg_rate", 0.125))
    out = []
    for h in d.holdings:
        if not (_in_equity(h) and h.get("bought")) or _gain(h) <= 0:
            continue
        b = date.fromisoformat(h["bought"])
        y, m = divmod(b.month - 1 + months, 12)
        lt_day = date(b.year + y, m + 1, min(b.day, 28)) + timedelta(days=1)
        left = (lt_day - d.today).days
        if 0 < left <= window:
            g = _gain(h)
            out.append(card("in.short_to_long", "IN", f"India · wait {left} days before selling {h['name']}",
                            f"Bought on {b:%d %b %Y}, it counts as long-term from {lt_day:%d %b %Y}. Before that, gains are taxed at "
                            f"{stcg:.0%}; after it at {ltcg:.1%} and inside the yearly allowance.",
                            lt_day, f"≈ {fmt(g * (stcg - ltcg), 'INR')} less tax", g * (stcg - ltcg), "INR", d, tone="warn",
                            extra={"kind": "countdown", "days": left}))
    return out


# ---------------------------------------------------------------- Germany
def _de_accounts(d: Data):
    return [a for a in d.accounts if a.get("country") == "DE" and not a.get("archived")]


@engine("de_fsa")
def de_fsa(p, d: Data):
    allowance = _n(p.get("allowance_single", 1000)) * (2 if d.answers.get("de_joint") else 1)
    rate = _n(p.get("rate", 0.26375))
    rows = []
    for a in _de_accounts(d):
        fsa, inc = _n(a.get("de_freistellungsauftrag")), _n(a.get("de_capital_income_ytd"))
        if fsa or inc:
            rows.append({"name": a["name"], "fsa": fsa, "income": inc})
    if not rows:
        return []
    over = sum(max(r["income"] - r["fsa"], 0) for r in rows)
    spare = sum(max(r["fsa"] - r["income"], 0) for r in rows) + max(allowance - sum(r["fsa"] for r in rows), 0)
    move = min(over, spare)
    if move < 25:
        return []
    for r in rows:
        r["suggested"] = r["fsa"]
    left = move
    for r in sorted(rows, key=lambda r: -(r["income"] - r["fsa"])):
        need = max(r["income"] - r["fsa"], 0)
        add = min(need, left)
        r["suggested"] += add
        left -= add
    take = move - max(allowance - sum(r["fsa"] for r in rows), 0)
    for r in sorted(rows, key=lambda r: -(r["fsa"] - r["income"])):
        if take <= 0:
            break
        spare_here = max(r["fsa"] - r["income"], 0)
        cut = min(spare_here, take)
        r["suggested"] -= cut
        take -= cut
    return [card("de.fsa_rebalance", "DE", "Germany · move your Freistellungsauftrag",
                 f"Your {fmt(allowance)} tax-free allowance isn't where the income is: {fmt(over)} of this year's investment income "
                 f"is above the allowance at its bank, while {fmt(spare)} of allowance sits unused elsewhere. Moving it stops tax "
                 f"being withheld; otherwise you reclaim it with your tax return (Anlage KAP).",
                 date(d.today.year, 12, 31), f"≈ {fmt(move * rate)} not withheld", move * rate, "EUR", d,
                 extra={"kind": "table", "head": ["Bank", "Allowance now", "Income this year", "Suggested"],
                        "rows": [[r["name"], fmt(r["fsa"]), fmt(r["income"]), fmt(r["suggested"])] for r in rows]})]


@engine("de_vorabpauschale")
def de_vorabpauschale(p, d: Data):
    year = d.today.year
    bz_table = p.get("basiszins") or {}
    bz = bz_table.get(year) or bz_table.get(str(year))
    if bz is None:
        return []
    factor, rate, exempt = _n(p.get("factor", 0.7)), _n(p.get("rate", 0.26375)), _n(p.get("equity_fund_exempt", 0.30))
    funds = [h for h in d.holdings if h.get("country") == "DE" and (h.get("payout") or "accumulating") == "accumulating"
             and (h.get("currency") or "EUR") == "EUR" and _value(h) > 0]
    if not funds:
        return []
    value = sum(_value(h) for h in funds)
    gain_year = sum(max(_gain(h), 0) for h in funds)
    base_income = min(value * _n(bz) * factor, gain_year) if gain_year else value * _n(bz) * factor
    taxable = base_income * (1 - exempt)
    tax = taxable * rate
    if tax < 5:
        return []
    return [card("de.vorabpauschale", "DE", "Germany · keep cash for the Vorabpauschale",
                 f"In early January the broker takes the advance lump-sum tax on accumulating funds from the account's cash: "
                 f"about {fmt(value)} × {_n(bz):.2%} base rate × {factor:.0%}, less the {exempt:.0%} exemption for equity funds. "
                 f"If there isn't enough cash it can use your allowance or sell a few units. The amount is credited when you sell later.",
                 date(year + 1, 1, 2), f"≈ {fmt(tax)} debit", -tax, "EUR", d, tone="muted",
                 caveat=f"Base rate {_n(bz):.2%} for {year}; the Finance Ministry publishes it each January — update it in the pack if it changed.")]


@engine("de_loss_certificate")
def de_loss_certificate(p, d: Data):
    rate = _n(p.get("rate", 0.26375))
    mm, dd = (int(x) for x in str(p.get("deadline", "12-15")).split("-"))
    accs = _de_accounts(d)
    losers = [a for a in accs if _n(a.get("de_losses_ytd")) > 0]
    gains = sum(max(_n(a.get("de_capital_income_ytd")) - _n(a.get("de_freistellungsauftrag")), 0) for a in accs)
    out = []
    for a in losers:
        loss = _n(a.get("de_losses_ytd"))
        use = min(loss, gains) if gains else 0
        if use < 10:
            continue
        out.append(card("de.loss_certificate", "DE", f"Germany · ask {a['name']} for a loss certificate",
                        f"{a['name']} holds {fmt(loss)} of losses you can't use there. With a Verlustbescheinigung the tax office offsets "
                        f"them against gains taxed at your other banks when you file.",
                        date(d.today.year, mm, dd), f"≈ {fmt(use * rate)} back", use * rate, "EUR", d, tone="warn"))
    return out


# ---------------------------------------------------------------- runner
def run_all(packs: dict, data: Data) -> tuple[list[dict], list[str]]:
    cards, errors = [], []
    for code, pk in packs.items():
        for o in pk.get("opportunities") or []:
            fn = ENGINES.get(o.get("engine"))
            if not fn:
                continue
            try:
                for c in fn(o.get("params") or {}, data):
                    c["rule_id"] = o.get("id", c["rule"])
                    cards.append(c)
            except Exception as e:  # noqa: BLE001 — one broken check must not hide the others
                errors.append(f"{code} {o.get('id')}: {type(e).__name__}: {e}")
    cards.sort(key=lambda c: (c["deadline"] or "9999", -abs(c["effect_base"])))
    return cards, errors


def tax_on_sale(packs: dict, holding: dict, amount: float, today: date | None = None, used_allowance: float = 0.0) -> tuple[float, str]:
    """Rough tax if `amount` (in the holding's currency) of this holding were sold today."""
    today = today or date.today()
    v = _value(holding)
    if v <= 0:
        return 0.0, "nothing to sell"
    g = _gain(holding) * min(amount / v, 1)
    if g <= 0:
        return 0.0, "sold at or below cost: no tax, and the loss can offset other gains"
    ccy = holding.get("currency") or "EUR"
    if holding.get("country") == "IN" or ccy == "INR":
        inv = (packs.get("IN") or {}).get("investing") or {}
        long = holding.get("bought") and date.fromisoformat(holding["bought"]) <= today - timedelta(days=365)
        if long:
            room = max(_n(inv.get("ltcg_exempt", 125000)) - used_allowance, 0)
            t = max(g - room, 0) * _n(inv.get("ltcg_equity", 0.125))
            return t, f"gain about {fmt(g, 'INR')}, long-term: {fmt(room, 'INR')} of it tax-free, rest at {_n(inv.get('ltcg_equity', 0.125)):.1%}"
        return g * _n(inv.get("stcg_equity", 0.20)), f"gain about {fmt(g, 'INR')}, short-term at {_n(inv.get('stcg_equity', 0.20)):.0%}"
    inv = (packs.get("DE") or {}).get("investing") or {}
    taxable = g * (1 - _n(inv.get("equity_fund_exempt", 0.30)))
    room = max(_n(inv.get("allowance_single", 1000)) - used_allowance, 0)
    t = max(taxable - room, 0) * _n(inv.get("capital_gains_rate", 0.26375))
    return t, f"gain about {fmt(g, ccy)}; {_n(inv.get('equity_fund_exempt', 0.30)):.0%} exempt for equity funds, then your remaining allowance, then ~26.4%"
