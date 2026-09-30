"""Trackers: long-running purchases paid in stages (a flat under construction, a car loan...).

One YAML file per tracker in <data>/trackers/. Example:

    id: my-flat
    type: staged_purchase
    name: My flat, Tower B-1203
    country: IN
    currency: INR
    price: 9500000               # total price excl. taxes
    tax_rate_on_payments: 0.05   # e.g. GST on each stage (optional)
    possession_date: 2028-06-30
    documents_folder: India/Property/My flat
    stages_folder: India/Property/My flat/Milestones
    stages:                      # in order; 'paid' = YYYY-MM when paid, empty if not yet
      - {no: "01", name: Booking, paid: 2025-01, keywords: [booking]}
      - {no: "02", name: Foundation, keywords: [foundation]}
    payments:                    # cumulative amount paid (excl. tax) after each payment
      - {date: 2025-01-15, cumulative: 950000, label: Booking}
    facts: [{label: "RERA no.", value: "P5210..."}]
    warning: Optional one-line risk note.
    document_rules: [...]        # optional rules that file this tracker's documents (use {stage_folder})
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml


def load_trackers(folder: Path) -> list[dict]:
    out = []
    if not folder.exists():
        return out
    for p in sorted(folder.glob("*.y*ml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if d.get("id"):
                d["_file"] = p.name
                out.append(d)
        except Exception as e:  # noqa: BLE001
            out.append({"id": p.stem, "name": p.stem, "_error": str(e), "_file": p.name})
    return out


def summarize(t: dict) -> dict:
    if t.get("_error"):
        return {"id": t["id"], "name": t["name"], "error": t["_error"]}
    price = float(t.get("price") or 0)
    pays = sorted(t.get("payments") or [], key=lambda p: str(p["date"]))
    paid = float(pays[-1]["cumulative"]) if pays else 0.0
    stages = t.get("stages") or []
    n_paid = sum(1 for s in stages if s.get("paid"))
    unpaid = [s for s in stages if not s.get("paid")]
    remaining = max(price - paid, 0)
    rate = float(t.get("tax_rate_on_payments") or 0)
    per_stage = float(t.get("remaining_per_stage") or (remaining / len(unpaid) if unpaid else 0))
    # evenly spread estimate of remaining stages up to possession
    proj = []
    poss = t.get("possession_date")
    if unpaid and poss:
        today = date.today()
        start = date(today.year + (today.month == 12), today.month % 12 + 1, 28)
        end = date.fromisoformat(str(poss))
        k = len(unpaid)
        for i, s in enumerate(unpaid, 1):
            d = start + (end - start) * ((i - 1) / max(k - 1, 1))
            proj.append({"date": d.isoformat(), "cumulative": round(min(paid + per_stage * i, price)), "label": f"{s.get('name', 'Stage')} (estimate)"})
    return {"id": t["id"], "name": t.get("name", t["id"]), "subtitle": t.get("subtitle", ""), "country": t.get("country", ""),
            "currency": t.get("currency", ""), "price": price, "paid": paid, "paid_pct": round(paid / price, 4) if price else 0,
            "remaining": remaining, "remaining_with_tax": round(remaining * (1 + rate)), "next_stage": round(per_stage * (1 + rate)),
            "possession_date": str(poss) if poss else None, "stages": [{**s, "paid": str(s["paid"]) if s.get("paid") else None} for s in stages],
            "stages_paid": n_paid, "payments": [{**p, "date": str(p["date"])} for p in pays], "projection": proj,
            "facts": t.get("facts", []), "warning": t.get("warning", "")}
