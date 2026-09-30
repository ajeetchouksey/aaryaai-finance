"""Fictional sample data for the public demo. Everything here is invented — no real person, account or document.

Persona: "Alex", works in Germany, has savings and a flat under construction in India.
Dates are relative to the day the site is built, so the demo always looks current.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))


def _months_ago(n: int, day: int = 1) -> date:
    t = date.today()
    y, m = t.year, t.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(day, 28))


def _pdf(text: str) -> bytes:
    """A tiny valid one-page PDF with a line of text, so the document tools have something real to read."""
    body = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def build(data_dir: Path) -> Path:
    """Create a complete demo data folder. Returns its path."""
    from aaryaai_finance.config import Settings
    from aaryaai_finance.context import Ctx
    from aaryaai_finance.core import ledger

    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    today = date.today()

    # ---- your own rules, tracker and model (the same examples shipped in the repo)
    (data_dir / "rules").mkdir()
    shutil.copy(ROOT / "examples/rules/my-rules.yaml", data_dir / "rules/my-rules.yaml")
    (data_dir / "trackers").mkdir()
    flat = yaml.safe_load((ROOT / "examples/trackers/example-flat.yaml").read_text(encoding="utf-8"))
    flat["subtitle"] = "2 BHK · under construction · sample data"
    (data_dir / "trackers/example-flat.yaml").write_text(yaml.safe_dump(flat, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (data_dir / "model.json").write_text(json.dumps({"entities": {"policies": {"label": "Insurance policy", "fields": {
        "name": {"type": "text", "required": True, "label": "Policy"},
        "insurer": {"type": "text", "label": "Insurer"},
        "premium": {"type": "money", "label": "Premium per year"},
        "renews_on": {"type": "date", "label": "Renews on"},
        "paid_from": {"type": "ref", "to": "accounts", "on_delete": "set_null", "label": "Paid from account"}}}}}, indent=2))

    # ---- sample documents (tiny PDFs with a line of text each)
    docs = data_dir / "documents"
    samples = {
        "Germany/Brutto-Netto-Abrechnung {y} {m} Sample.pdf": "Brutto/Netto-Abrechnung sample employer GmbH",
        "Germany/Lohnsteuerbescheinigung {py}.pdf": "Ausdruck der elektronischen Lohnsteuerbescheinigung {py}",
        "Germany/Bank/{y}-{m}_Kontoauszug.pdf": "Kontoauszug Girokonto IBAN DE00 sample",
        "India/Bank/{y}-{m}_AccountStatement.pdf": "Account Statement NRE sample bank",
        "India/Property/TDS/AB12345678_Statement.pdf": "Form 26QB statement Acknowledgement Number AB12345678",
        "India/Property/Riverside/Milestones/03_Plinth_{py2}/Demand_letter.pdf": "Riverside Towers demand letter plinth",
    }
    lm = _months_ago(1)
    fill = {"y": lm.year, "m": f"{lm.month:02d}", "py": today.year - 1, "py2": f"{today.year - 1}-06"}
    for rel, text in samples.items():
        p = docs / rel.format(**fill)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_pdf(text.format(**fill)))

    # ---- settings
    s = Settings(data_dir)
    cfg = s.config
    cfg["profile"].update({"name": "Alex", "about": "Sample persona: employee in Germany with savings and a flat under construction in India.",
                           "answers": {"de_mandatory_filing": False, "de_joint": True, "de_church": False,
                                       "in_nri": True, "in_property_tds": True, "in_advance_tax": False}})
    cfg.update({"countries": ["DE", "IN"], "base_currency": "EUR", "extra_currencies": ["USD"], "documents_root": "documents",
                "folders": {"DE": "Germany", "IN": "India", "inbox": "_Inbox"},
                "fx": {"source": "manual", "manual_rates": {"INR": 98.5, "USD": 1.12}}, "updates": {"check": False}})
    s.save()

    c = Ctx(s)
    db = c.db
    A = lambda **r: db.upsert("accounts", r)  # noqa: E731
    giro = A(name="Girokonto", institution="Sample Bank", country="DE", currency="EUR", type="Current account",
             opening_balance=3200, opening_date=_months_ago(7).isoformat(), liquid=1)
    tages = A(name="Tagesgeld", institution="Sample Direktbank", country="DE", currency="EUR", type="Savings account",
              opening_balance=18500, opening_date=_months_ago(7).isoformat(), liquid=1, de_freistellungsauftrag=1000)
    nre = A(name="NRE savings", institution="Sample Bank India", country="IN", currency="INR", type="Savings account",
            opening_balance=420000, opening_date=_months_ago(7).isoformat(), liquid=1, in_account_kind="NRE")
    nro = A(name="NRO savings", institution="Sample Bank India", country="IN", currency="INR", type="Savings account",
            opening_balance=185000, opening_date=_months_ago(7).isoformat(), liquid=1, in_account_kind="NRO")

    start = _months_ago(6).isoformat()
    R = lambda **r: db.upsert("recurring", {"active": 1, "start_date": start, **r})  # noqa: E731
    R(kind="income", account_id=giro, amount=5400, category="Salary", note="Salary", frequency="monthly", start_date=_months_ago(6, 25).isoformat())
    R(kind="expense", account_id=giro, amount=1450, category="Rent / Warmmiete", note="Rent", frequency="monthly")
    R(kind="expense", account_id=giro, amount=115, category="Groceries", note="Supermarket", frequency="weekly")
    R(kind="expense", account_id=giro, amount=89, category="Utilities & internet", note="Electricity + internet", frequency="monthly", start_date=_months_ago(6, 5).isoformat())
    R(kind="expense", account_id=giro, amount=58, category="Transport", note="Deutschlandticket", frequency="monthly", start_date=_months_ago(6, 3).isoformat())
    R(kind="transfer", account_id=giro, to_account_id=tages, amount=900, to_amount=900, category="Savings", note="Monthly saving", frequency="monthly", start_date=_months_ago(6, 26).isoformat())
    R(kind="income", account_id=nro, amount=18000, category="Rent received", note="Rent from Pune flat", frequency="monthly", start_date=_months_ago(6, 7).isoformat())
    R(kind="income", account_id=nre, amount=2900, category="FD interest", note="NRE FD interest", frequency="quarterly", start_date=_months_ago(6, 15).isoformat())
    ledger.materialize_recurring(db)
    T = lambda d, **r: db.upsert("transactions", {"date": d.isoformat(), **r})  # noqa: E731
    T(_months_ago(4, 12), account_id=giro, kind="expense", amount=640, category="Travel", note="Flights to Pune")
    T(_months_ago(3, 9), account_id=giro, kind="expense", amount=212, category="Eating out", note="Birthday dinner")
    T(_months_ago(2, 18), account_id=giro, kind="expense", amount=399, category="Shopping", note="New laptop bag and monitor")
    T(_months_ago(1, 20), account_id=giro, kind="expense", amount=1180, category="Insurance", note="Car insurance (yearly)")
    T(_months_ago(0, 2), account_id=giro, kind="expense", amount=76, category="Eating out", note="Lunch with team")

    db.upsert("items", {"name": "Car", "kind": "asset", "category": "Vehicle", "amount": 14000, "currency": "EUR", "country": "DE", "updated": today.isoformat()})
    db.upsert("items", {"name": "Car loan", "kind": "liability", "category": "Personal loan", "amount": 6200, "currency": "EUR", "country": "DE", "updated": today.isoformat()})
    db.upsert("items", {"name": "Flat under construction (paid so far, at cost)", "kind": "asset", "category": "Property (under construction)",
                        "amount": 2850000, "currency": "INR", "country": "IN", "updated": today.isoformat(), "note": "See the Riverside tracker on Position"})
    db.upsert("items", {"name": "Company pension (bAV)", "kind": "asset", "category": "Retirement / pension", "amount": 11800, "currency": "EUR", "country": "DE", "updated": today.isoformat()})

    db.upsert("holdings", {"name": "FTSE All-World ETF", "ticker": "VWCE.DE", "asset_type": "ETF", "country": "DE", "account": "Sample broker",
                           "qty": 85, "avg_cost": 98.4, "currency": "EUR", "last_price": 121.3, "price_date": today.isoformat()})
    db.upsert("holdings", {"name": "Nifty 50 index fund", "ticker": "", "asset_type": "Mutual fund", "country": "IN", "account": "Sample AMC",
                           "qty": 1200, "avg_cost": 180, "currency": "INR", "last_price": 236, "price_date": today.isoformat()})

    db.upsert("goals", {"name": "Emergency fund (6 months)", "target_today": 20000, "currency": "EUR", "target_date": date(today.year + 1, 6, 30).isoformat(),
                        "saved": 12500, "monthly": 450, "annual_return": 0.02, "inflation": 0.02, "priority": 1})
    db.upsert("goals", {"name": "Flat: remaining instalments", "target_today": 7300000, "currency": "INR", "target_date": "2028-06-30",
                        "saved": 600000, "monthly": 90000, "annual_return": 0.065, "inflation": 0.0, "priority": 1})
    db.upsert("goals", {"name": "Child's university", "target_today": 60000, "currency": "EUR", "target_date": date(today.year + 12, 9, 1).isoformat(),
                        "saved": 4000, "monthly": 250, "annual_return": 0.06, "inflation": 0.025, "priority": 2})

    for cat, amt in [("Rent / Warmmiete", 1450), ("Groceries", 500), ("Utilities & internet", 89), ("Transport", 58), ("Eating out", 180),
                     ("Insurance", 120), ("Shopping", 150), ("Travel", 150), ("Subscriptions", 35)]:
        db.upsert("expenses", {"category": cat, "amount": amt})

    db.upsert("policies", {"name": "Haftpflicht (liability)", "insurer": "Sample Versicherung", "premium": 65, "renews_on": date(today.year + 1, 1, 1).isoformat(), "paid_from": giro})
    db.upsert("policies", {"name": "Health insurance (India, parents)", "insurer": "Sample Health", "premium": 24000, "renews_on": _months_ago(-3).isoformat()})

    # ---- a year of net-worth history so the charts have a shape
    now = c.net_worth()["net_worth"]
    with db.conn() as con:
        for i in range(12, 0, -1):
            d = _months_ago(i, 28)
            nw = round(now - i * 1350 + (700 if i % 4 == 0 else -300 if i % 3 == 0 else 0))
            con.execute("INSERT OR REPLACE INTO snapshots (day, net_worth, assets, liabilities, currency) VALUES (?,?,?,?,?)",
                        (d.isoformat(), nw, nw + 6200, 6200, "EUR"))
    return data_dir


if __name__ == "__main__":
    print(build(Path(sys.argv[1] if len(sys.argv) > 1 else "demo-data")))
