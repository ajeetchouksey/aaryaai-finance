"""Goal odds: how likely each goal is, instead of one straight-line projection.

Plain English:
- Markets don't grow by the same % every year. We replay your goal 2,000 times with good and bad
  years drawn at random around the expected return, with a spread that depends on how the money is
  invested (cash barely moves; shares swing a lot).
- "85% likely" means 1,700 of the 2,000 replays reached the target (in future money, after inflation).
- The random draws are seeded per goal, so the same inputs always give the same answer.

The spreads are rough long-run figures, not forecasts:
  cash      ~2% a year, spread 0.5%
  balanced  ~4.5% a year, spread 8%
  growth    ~6.5% a year, spread 15%
  glide     starts like growth and moves towards cash over the last 10 years
If you set an expected return on the goal, that is used as the middle and only the spread comes from here.
"""
from __future__ import annotations

import math
import random
from datetime import date

from .planning import months_between

RISK = {"cash": (0.02, 0.005), "balanced": (0.045, 0.08), "growth": (0.065, 0.15)}
RUNS = 2000


def guess_risk(annual_return: float | None) -> str:
    r = annual_return if annual_return is not None else 0.05
    return "cash" if r <= 0.03 else "balanced" if r <= 0.055 else "growth"


def equity_share(years_left: float, start: float = 0.8, end: float = 0.3, glide_years: float = 10) -> float:
    """Glide path: full share until 10 years out, then linearly down to `end` at the target date."""
    if years_left >= glide_years:
        return start
    return end + (start - end) * max(years_left, 0) / glide_years


def _year_params(risk: str, mean: float | None, years_left: float) -> tuple[float, float]:
    if risk == "glide":
        e = equity_share(years_left)
        mu = e * RISK["growth"][0] + (1 - e) * RISK["cash"][0]
        sd = e * RISK["growth"][1] + (1 - e) * RISK["cash"][1]
        if mean is not None:
            mu += mean - RISK["growth"][0] * 0.8 - RISK["cash"][0] * 0.2
        return mu, sd
    mu, sd = RISK.get(risk, RISK["balanced"])
    return (mean if mean is not None else mu), sd


def simulate(saved: float, monthly: float, months: int, risk: str, mean: float | None, seed: int,
             runs: int = RUNS, pause_months: int = 0, return_shift: float = 0.0) -> list[float]:
    """Final values of `runs` replays. Yearly steps; contributions spread evenly through each year."""
    rng = random.Random(seed)
    out = []
    years = months / 12
    steps = max(math.ceil(years), 1) if months > 0 else 0
    for _ in range(runs):
        v = saved
        done = 0
        for k in range(steps):
            m = min(12, months - done)
            yl = years - k
            mu, sd = _year_params(risk, mean, yl)
            mu += return_shift
            # lognormal with the given arithmetic mean and spread, scaled to the part of the year
            s2 = math.log(1 + (sd * sd) / ((1 + mu) ** 2)) if sd else 0.0
            g = math.exp(rng.gauss(math.log(1 + mu) - s2 / 2, math.sqrt(s2)) * (m / 12)) if s2 else (1 + mu) ** (m / 12)
            contrib = monthly * max(0, m - max(0, pause_months - done))
            v = v * g + contrib * math.sqrt(g)  # contributions arrive through the year, so they get about half the year's growth
            done += m
        out.append(v)
    return out


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def odds(goal: dict, today: date | None = None, monthly: float | None = None, runs: int = RUNS, **kw) -> dict:
    today = today or date.today()
    n = months_between(today, date.fromisoformat(goal["target_date"]))
    infl = goal.get("inflation") or 0.0
    target = goal["target_today"] * (1 + infl) ** (n / 12)
    risk = goal.get("risk") or guess_risk(goal.get("annual_return"))
    mean = goal.get("annual_return")
    m = (goal.get("monthly") or 0.0) if monthly is None else monthly
    seed = int(goal.get("id") or 0) * 7919 + n
    vals = simulate(goal.get("saved") or 0.0, m, n, risk, mean, seed, runs, **kw)
    p = sum(1 for v in vals if v >= target - 0.5) / len(vals) if vals else (1.0 if (goal.get("saved") or 0) >= target else 0.0)
    if n == 0:
        p = 1.0 if (goal.get("saved") or 0) >= target else 0.0
    return {"probability": round(p, 3), "p10": round(pct(vals, 0.1), 2), "p50": round(pct(vals, 0.5), 2), "p90": round(pct(vals, 0.9), 2),
            "target_future": round(target, 2), "months": n, "risk": risk, "monthly": m}


def monthly_for(goal: dict, prob: float = 0.85, today: date | None = None, runs: int = 400) -> float | None:
    """Smallest monthly saving (rounded to 10) that reaches `prob`. None if it can't within 10x the target."""
    today = today or date.today()
    n = months_between(today, date.fromisoformat(goal["target_date"]))
    if n == 0:
        return None
    if odds(goal, today, runs=runs)["probability"] >= prob and (goal.get("monthly") or 0) == 0:
        return 0.0
    lo, hi = 0.0, max(goal["target_today"] * 3 / n, 10)
    for _ in range(40):
        if odds(goal, today, monthly=hi, runs=runs)["probability"] >= prob:
            break
        hi *= 2
        if hi > goal["target_today"] * 10:
            return None
    for _ in range(16):
        mid = (lo + hi) / 2
        if odds(goal, today, monthly=mid, runs=runs)["probability"] >= prob:
            hi = mid
        else:
            lo = mid
    return float(math.ceil(hi / 10) * 10)


WHATIFS = [
    {"id": "today", "label": "Today's plan", "kw": {}},
    {"id": "save_more", "label": "Save 10% more each month", "monthly_factor": 1.10, "kw": {}},
    {"id": "gap", "label": "6 months without saving", "kw": {"pause_months": 6}},
    {"id": "weak_markets", "label": "Markets 2% a year weaker", "kw": {"return_shift": -0.02}},
    {"id": "inflation", "label": "Inflation 1.5% higher", "inflation_add": 0.015, "kw": {}},
]


def whatif(goals: list[dict], today: date | None = None, runs: int = RUNS) -> list[dict]:
    rows = []
    for w in WHATIFS:
        cells = []
        for g in goals:
            g2 = dict(g)
            if w.get("inflation_add"):
                g2["inflation"] = (g.get("inflation") or 0) + w["inflation_add"]
            m = (g.get("monthly") or 0) * w.get("monthly_factor", 1.0)
            cells.append(odds(g2, today, monthly=m, runs=runs, **w["kw"])["probability"])
        rows.append({"id": w["id"], "label": w["label"], "probabilities": cells})
    return rows


def glide_path(target_date: str, today: date | None = None, points: int = 6) -> list[dict]:
    today = today or date.today()
    total = months_between(today, date.fromisoformat(target_date)) / 12
    out = []
    for i in range(points):
        yl = total * (1 - i / (points - 1))
        out.append({"year": today.year + round(total - yl), "shares": round(equity_share(yl), 2)})
    return out
