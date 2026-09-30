"""Currency conversion for any set of currencies.

Rates are stored relative to your base currency: rates["INR"] = rupees per 1 unit of base.
Source: European Central Bank reference rates via frankfurter.dev (free, no key), or rates
you type in yourself (Settings → Currencies). ECB covers ~30 major currencies incl. INR, USD,
GBP, CHF, JPY, SGD, AED is not included — use a manual rate for those.
"""
from __future__ import annotations

import json


def get_rates(db, base: str) -> dict:
    try:
        stored = json.loads(db.settings().get("fx_rates") or "{}")
    except Exception:  # noqa: BLE001
        stored = {}
    if stored.get("_base") != base:
        stored = {"_base": base}
    stored[base] = 1.0
    return stored


def set_rates(db, base: str, rates: dict, date: str | None = None) -> dict:
    r = {"_base": base, base: 1.0, **{k: float(v) for k, v in rates.items() if v}}
    if date:
        r["_date"] = date
    db.set_setting("fx_rates", json.dumps(r))
    return r


def convert(amount: float, frm: str, to: str, rates: dict) -> float:
    if frm == to or amount is None:
        return amount or 0.0
    try:
        return amount / float(rates[frm]) * float(rates[to])
    except (KeyError, ZeroDivisionError, TypeError):
        raise ValueError(f"No exchange rate for {frm}→{to}. Refresh rates or add a manual rate in Settings.")


def fetch_ecb(base: str, symbols: list[str]) -> tuple[dict, str]:
    import httpx
    want = [s for s in symbols if s != base]
    if not want:
        return {}, ""
    r = httpx.get("https://api.frankfurter.dev/v1/latest", params={"base": base, "symbols": ",".join(want)},
                  timeout=12, follow_redirects=True)
    r.raise_for_status()
    j = r.json()
    return j.get("rates", {}), j.get("date", "")
