"""Automated UI tests: the real app in a real browser (Chromium via Playwright), on the invented sample data.

They follow the acceptance test (UAT) guide: every screen loads, and the main things a person does
work end to end. Numbers depend on today's date, so tests check structure and *changes* (an amount
goes up, a card disappears), not exact figures.

Run:   pip install -e ".[dev,ui]" && python -m playwright install chromium
       pytest -m ui            (only these)      pytest   (everything; these skip without Playwright)
Screenshots of failing tests land in ui-artifacts/.
"""
from __future__ import annotations

import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.ui
sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright not installed (pip install -e .[ui])")

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ui-artifacts"
TABS = ["home", "forecast", "goals", "diversify", "opportunities", "plan", "money", "position", "invest", "documents",
        "taxreturn", "tax", "learn", "routines", "rules", "settings", "chat"]


# ---------------------------------------------------------------- the app and the browser
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(data_dir: Path):
    import uvicorn
    from aaryaai_finance.server import create_app
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(data_dir), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(150):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return server, f"http://127.0.0.1:{port}"
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("the app did not start")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "site"))
    from demo_data import build
    data = build(tmp_path_factory.mktemp("ui") / "data")
    server, url = _serve(data)
    yield {"url": url, "data": data}
    server.should_exit = True


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium not available ({type(e).__name__}); run: python -m playwright install chromium")
        yield b
        b.close()


@pytest.fixture()
def page(browser, app, request):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, bypass_csp=True)
    pg = ctx.new_page()
    pg.errors = []
    pg.answer_ok = True                                   # "Delete this?" dialogs: answer like a person clicking OK
    pg.on("dialog", lambda d: d.accept() if pg.answer_ok else d.dismiss())
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and pg.errors.append(m.text))
    pg.set_default_timeout(15000)
    pg.goto(app["url"] + "/")
    pg.wait_for_function("document.querySelector('#homeKpis .kpi')")
    yield pg
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        ARTIFACTS.mkdir(exist_ok=True)
        pg.screenshot(path=str(ARTIFACTS / f"{request.node.name}.png"), full_page=True)
    ctx.close()
    assert not pg.errors, f"JavaScript errors: {pg.errors}"


def go(pg, tab, ready=None):
    pg.evaluate(f"go('{tab}')")
    pg.wait_for_selector(f"section#{tab}.on")
    if ready:
        pg.wait_for_selector(ready)
    pg.wait_for_load_state("networkidle")


def amounts(text: str) -> list[int]:
    """Whole numbers in a text, ignoring currency signs and grouping (€1,400 / ₹1,36,000 / €1.400)."""
    return [int(re.sub(r"[^\d]", "", m)) for m in re.findall(r"\d[\d.,]*", text)]


# ---------------------------------------------------------------- every screen
def test_every_screen_loads_without_errors(page):
    for tab in TABS:
        go(page, tab)
        sec = page.locator(f"section#{tab}")
        assert sec.is_visible(), tab
        assert len(sec.inner_text().strip()) > 40, f"{tab} looks empty"
        assert page.evaluate("document.documentElement.scrollWidth") <= 1440, f"{tab} scrolls sideways"


def test_phone_layout_has_no_sideways_scroll(browser, app):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, bypass_csp=True)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(app["url"] + "/")
    pg.wait_for_function("document.querySelector('#homeKpis .kpi')")
    for tab in ["home", "forecast", "goals", "diversify", "opportunities", "taxreturn", "routines", "money"]:
        go(pg, tab)
        assert pg.evaluate("document.documentElement.scrollWidth") <= 390, f"{tab} scrolls sideways on a phone"
    assert pg.locator("nav#tabs").bounding_box()["y"] > 700           # navigation moved to the bottom
    ctx.close()
    assert not errors, errors


# ---------------------------------------------------------------- Home
def test_home_dashboard(page):
    assert "Alex" in page.locator("#homeHello").inner_text()
    banner = page.locator("#homeAttention .banner")
    assert banner.is_visible() and "transfer" in banner.inner_text() and "INR" in banner.inner_text()
    assert page.locator("#homeKpis .kpi").count() == 4
    assert page.locator("#homeGoals .goalrow").count() == 4
    assert page.locator("#homeInbox .prop button:has-text('Approve')").count() >= 1
    assert page.locator("#homeTracker .stagestrip i").count() == 7
    assert page.locator("#homeTracker .stagestrip i.paid").count() == 3
    banner.locator("button:has-text('See the plan')").click()
    page.wait_for_selector("section#forecast.on")


# ---------------------------------------------------------------- Cash forecast
def _first_send(pg) -> int:
    row = pg.locator("#fcPlan .fstep tr.hl").first.inner_text()
    return amounts(row.split("\n")[-1] if "\n" in row else row)[-1]


def test_forecast_scenarios_and_floors(page):
    go(page, "forecast", "#fcCharts .vbars")
    assert page.locator("#fcCharts .vbars").count() == 2
    assert page.locator("#fcCharts .vb-col").count() == 24
    steps = page.locator("#fcPlan .fstep")
    assert steps.count() >= 1
    before = amounts(page.locator("#fcPlan .fstep tr.hl").first.inner_text())
    eur_low = page.locator("#fcCharts .card").first.locator(".chip").inner_text()

    page.locator("#fcScenarios button", has_text="Salary a month late").click()
    page.wait_for_selector("#fcScenarios button.on:has-text('Salary a month late')")
    assert page.locator("#fcCharts .card").first.locator(".chip").inner_text() != eur_low
    page.locator("#fcScenarios button", has_text="Base plan").click()
    page.wait_for_selector("#fcScenarios button.on:has-text('Base plan')")

    page.fill("#floorForm input[name=INR]", "150000")
    page.click("#floorForm button")
    page.wait_for_function("document.querySelector('#fcCharts').innerText.includes('floor ₹1,50,000')")
    after = amounts(page.locator("#fcPlan .fstep tr.hl").first.inner_text())
    assert max(after) > max(before), (before, after)          # a higher floor needs a bigger transfer
    page.fill("#floorForm input[name=INR]", "50000")
    page.click("#floorForm button")
    page.wait_for_function("document.querySelector('#fcCharts').innerText.includes('floor ₹50,000')")


def test_planned_item_add_edit_delete(page):
    go(page, "forecast", "#fcPlanned")
    page.click("#forecast .pagehead button:has-text('Planned item')")
    dlg = page.locator("#dlg")
    dlg.wait_for(state="visible")
    dlg.locator("select[name=kind]").select_option("expense")
    dlg.locator("input[name=amount]").fill("3000")
    dlg.locator("input[name=note]").fill("UI test car repair")
    dlg.locator("select[name=confidence]").select_option("estimated")
    dlg.locator("button:has-text('Save')").click()
    row = page.locator("#fcPlanned tr", has_text="UI test car repair")
    row.wait_for()
    assert "estimated" in row.inner_text()
    assert page.locator("#fcSources tr", has_text="UI test car repair").count() == 1
    row.locator("button:has-text('Edit')").click()
    dlg.wait_for(state="visible")
    page.answer_ok = False                                # Cancel on "Delete this for good?": nothing happens
    dlg.locator("#dlgDel").click()
    assert dlg.is_visible() and page.locator("#fcPlanned tr", has_text="UI test car repair").count() == 1
    page.answer_ok = True
    dlg.locator("#dlgDel").click()
    page.wait_for_function("!document.querySelector('#fcPlanned').innerText.includes('UI test car repair')")


# ---------------------------------------------------------------- Goals
def test_goal_odds_and_slider(page):
    go(page, "goals", "#goalOdds .oddrow")
    assert page.locator("#goalOdds .oddrow").count() == 4
    assert page.locator("#goalOdds table tbody tr").count() == 5          # what-if rows
    page.wait_for_function("document.querySelector('#lvProb').textContent.includes('%')")
    low = int(page.locator("#lvProb").inner_text().strip("%"))
    page.evaluate("const r = document.querySelector('#lvRange'); r.value = r.max; r.dispatchEvent(new Event('input'))")
    page.wait_for_function(f"parseInt(document.querySelector('#lvProb').textContent) > {low}")
    assert "at steady growth" in page.locator("#goalCards").text_content()


# ---------------------------------------------------------------- Diversify
def test_diversify_xray_and_target_validation(page):
    go(page, "diversify", "#dvXray .xr")
    assert page.locator("#dvXray .xr").count() == 4
    assert "USA" in page.locator("#dvXray").inner_text()                    # look-through of index funds
    assert page.locator("#dvCompanies .chip", has_text="in 2 funds").count() >= 1
    page.fill("#tgtForm input[name=shares]", "95")
    page.click("#tgtForm button")
    page.wait_for_function("document.querySelector('#toast').textContent.includes('more than 100%')")
    page.reload()                                                              # nothing was saved: a fresh load shows 40
    page.wait_for_function("typeof go === 'function'")
    go(page, "diversify", "#tgtForm input[name=shares]")
    page.wait_for_function("document.querySelector('#tgtForm input[name=shares]').value === '40'")


# ---------------------------------------------------------------- Opportunities
def test_opportunities_react_to_your_numbers(page):
    go(page, "opportunities", "#opCards .opcard")
    cards = page.locator("#opCards .opcard")
    n = cards.count()
    assert n >= 4 and page.locator("#opCards .opcard", has_text="tax-free gains allowance").count() == 1
    page.fill("#opForm input[name=in_ltcg_used]", "125000")
    page.click("#opForm button")
    page.wait_for_function(f"document.querySelectorAll('#opCards .opcard').length === {n - 1}")
    page.fill("#opForm input[name=in_ltcg_used]", "38000")
    page.click("#opForm button")
    page.wait_for_function(f"document.querySelectorAll('#opCards .opcard').length === {n}")


# ---------------------------------------------------------------- Tax return
def test_tax_return_answers_change_the_estimate_and_export(page, app):
    go(page, "taxreturn", "#twSheet table")
    assert page.locator("#twSteps .step").count() == 5
    assert "Found" in page.locator("#twDocs").inner_text()
    refund = amounts(page.locator(".bigest").inner_text())[0]
    page.fill("#twForm input[name=homeoffice_days]", "200")
    page.click("#twForm button:has-text('Save answers')")
    page.wait_for_function(f"parseInt(document.querySelector('.bigest').textContent.replace(/[^0-9]/g,'')) > {refund}")
    href = page.locator("#twSheet a.btnlink").first.get_attribute("href")
    csv = page.request.get(app["url"] + href)
    assert csv.ok and "Bruttoarbeitslohn" in csv.text()
    page.fill("#twForm input[name=homeoffice_days]", "180")
    page.click("#twForm button:has-text('Save answers')")
    page.wait_for_function(f"parseInt(document.querySelector('.bigest').textContent.replace(/[^0-9]/g,'')) === {refund}")
    page.locator("#twPick button", has_text="India").click()
    page.wait_for_function("document.querySelector('#twTitle').textContent.includes('India')")
    assert "regime" in page.locator("#twOptimise").inner_text()


# ---------------------------------------------------------------- Routines, proposals, audit
def test_approve_a_proposal_and_see_it_in_the_audit_log(page):
    go(page, "routines", "#rtProposals .prop")
    pending = page.locator("#rtProposals > .prop")
    n = pending.count()
    assert n >= 1
    title = pending.first.locator("b").inner_text()
    pending.first.locator("button:has-text('Approve')").click()
    page.wait_for_function(f"document.querySelectorAll('#rtProposals > .prop').length === {n - 1}")
    page.wait_for_selector("#rtAudit td:has-text('Approved:')")
    assert title[:20] in page.locator("#rtAudit").inner_text()
    badge = page.locator("#navProposals")
    assert (badge.is_hidden() and n == 1) or badge.inner_text() == str(n - 1)


def test_run_a_routine(page):
    go(page, "routines", "#rtList .rt-item")
    from aaryaai_finance.core.routines import ROUTINES
    assert page.locator("#rtList .rt-item").count() == len(ROUTINES)
    page.locator("#rtList .rt-item", has_text="Forecast refresh").locator("button:has-text('Run')").click()
    page.wait_for_function("document.querySelector('#toast').textContent.startsWith('Ran 1 routine')")


def test_connect_claude_desktop_through_mcp(page):
    import json
    from aaryaai_finance import mcp_setup as ms
    cfg = ms.config_paths("claude")[0]                 # inside the isolated test folder (see conftest)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    go(page, "routines", "#rtConnections")

    def row():
        return page.locator("#rtConnections .li").filter(has=page.locator(".li-t", has_text=re.compile(r"^Claude Desktop$")))
    assert row().locator(".chip").inner_text() == "Not connected"
    row().locator("button", has_text="Connect").click()
    page.wait_for_function("[...document.querySelectorAll('#rtConnections .li')].some(r => r.querySelector('.li-t').textContent === 'Claude Desktop' && r.innerText.includes('Disconnect'))")
    assert row().locator(".chip").inner_text() == "Connected"
    assert "aaryaai-finance" in json.loads(cfg.read_text())["mcpServers"]
    row().locator("button", has_text="Disconnect").click()
    page.wait_for_function("[...document.querySelectorAll('#rtConnections .li')].some(r => r.querySelector('.li-t').textContent === 'Claude Desktop' && r.innerText.includes('Connect') && !r.innerText.includes('Disconnect'))")
    assert "aaryaai-finance" not in json.loads(cfg.read_text())["mcpServers"]


# ---------------------------------------------------------------- privacy and security
# ---------------------------------------------------------------- Money: search, edit and export
def test_search_edit_and_export_transactions(page):
    acc = page.evaluate("api('/api/accounts')")[0]["id"]
    today = page.evaluate("new Date().toLocaleDateString('sv')")
    page.evaluate(f"api('/api/transactions', {{method: 'POST', body: {{date: '{today}', kind: 'expense', account_id: {acc}, amount: 12.5, "
                  f"category: 'Groceries', note: '=UI test formula shop'}}}})")
    go(page, "money", "#txList")
    page.click("#perSeg button[data-p=month]")
    page.wait_for_function("document.querySelector('#txList').innerText.includes('UI test formula shop')")
    total = page.locator("#txList .tx").count()
    page.fill("#txSearch", "formula shop")
    page.wait_for_function("document.querySelectorAll('#txList .tx').length === 1")
    assert " of " in page.locator("#txCount").inner_text() and total > 1
    with page.expect_download() as dl:
        page.click("#txExport")
    text = Path(dl.value.path()).read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Date,Type,Amount") and "'=UI test formula shop" in text
    page.locator("#txList .tx button[aria-label=Edit]").click()
    dlg = page.locator("#dlg")
    dlg.wait_for(state="visible")
    dlg.locator("input[name=amount]").fill("13.75")
    dlg.locator("button:has-text('Save')").click()
    page.wait_for_function("document.querySelector('#txList').innerText.includes('13,75') || document.querySelector('#txList').innerText.includes('13.75')")
    assert any(t["amount"] == 13.75 and (t["note"] or "").endswith("formula shop") for t in page.evaluate("api('/api/transactions')"))
    page.fill("#txSearch", "")


def test_hide_amounts(page):
    nw = page.locator("#homeKpis .kpi").first
    assert "•" not in nw.inner_text()
    page.keyboard.press("Alt+KeyH")
    page.wait_for_function("document.body.classList.contains('amounts-hidden')")
    page.wait_for_function("document.querySelector('#homeKpis .kpi').innerText.includes('•')")
    page.keyboard.press("Alt+KeyH")
    page.wait_for_function("!document.querySelector('#homeKpis .kpi').innerText.includes('•')")


# ---------------------------------------------------------------- charts say what they show
def test_charts_have_a_summary_and_a_table(page):
    go(page, "position", "#chCat[role=img]")
    label = page.get_attribute("#chCat", "aria-label")
    assert label.startswith("What you own, by type:") and "%" in label
    det = page.locator("#chCat").locator("xpath=ancestor::div[contains(@class,'chartbox')]/following-sibling::details[1]")
    assert det.locator("summary").inner_text() == "View as table" and not det.get_attribute("open")
    det.locator("summary").click()
    rows = det.locator("tbody tr")
    assert rows.count() >= 2 and "€" in rows.first.inner_text()
    hist = page.get_attribute("#chHist", "aria-label")
    assert "So far:" in hist and "Outlook:" in hist and "lowest" in hist
    go(page, "forecast", "#fcCharts .vbars[role=img]")
    bars = page.locator("#fcCharts .vbars").first.get_attribute("aria-label")
    assert "month-end balance" in bars and "lowest" in bars and "floor" in bars
    assert page.locator("#fcCharts details.charttable").first.locator("tbody tr").count() == 12
    page.keyboard.press("Alt+KeyH")
    page.wait_for_function("document.body.classList.contains('amounts-hidden')")
    try:
        go(page, "position", "#chCat[role=img]")
        page.wait_for_function("document.querySelector('#chCat').getAttribute('aria-label').includes('•')")
        assert not re.search(r"€\s?\d", det.locator("tbody").inner_text())                  # the table hides amounts too
    finally:
        page.keyboard.press("Alt+KeyH")


def test_hide_amounts_covers_fields_units_toasts_and_chat(page):
    page.keyboard.press("Alt+KeyH")
    page.wait_for_function("document.body.classList.contains('amounts-hidden')")
    try:
        go(page, "invest", "#holdTbl td[data-l=Units]")
        units = page.locator("td[data-l=Units]").first.inner_text()
        assert units == "•••"
        assert page.evaluate("hideAmt('Paid ¥12,000 and S$300 and 500 SGD')") == "Paid ¥•••• and S$ •••• and •••• SGD"
        page.evaluate("toast('Saved: 1,234.50 EUR transferred')")
        assert "1,234" not in page.locator("#toast").inner_text()
        assert "4,000" not in page.evaluate("userMsg('my salary is €4,000')")
        go(page, "forecast", "#floorForm input[type=number]")
        field = page.locator("#floorForm input[type=number]").first
        assert "blur" in field.evaluate("e => getComputedStyle(e).filter")
        field.focus()
        assert field.evaluate("e => getComputedStyle(e).filter") == "none"      # readable while you edit it
    finally:
        page.keyboard.press("Alt+KeyH")


# ---------------------------------------------------------------- text from rules, packs and documents is shown, never run
HOSTILE = ["it's", 'a "quote"', "&quot;);window.__xss=1;//", "'><img src=x onerror=window.__xss=1>", "</script><b>x</b>", "\\", "${x}"]


def test_attribute_helpers_keep_hostile_text_inert(page):
    for s in HOSTILE:
        got = page.evaluate("""(s) => { const d = document.createElement('div');
            d.innerHTML = `<button title="${esc(s)}" onclick="window.__v=${jsArg(s)}"></button>`;
            d.firstChild.click(); return [window.__v, d.firstChild.title]; }""", s)
        assert got == [s, s]
    assert page.evaluate("safeUrl('javascript:alert(1)')") == "" and page.evaluate("safeUrl('https://example.org/a')") == "https://example.org/a"
    assert page.evaluate("window.__xss") is None


def test_deadline_with_hostile_title_renders_as_text(page):
    title = "Pay \"'><img src=x onerror=window.__xss=1> &quot;);window.__xss=2;// tax"
    page.evaluate("(t) => api('/api/calendar', {method: 'POST', body: {due: '2099-01-15', country: 'DE', title: t, severity: 'normal'}})", title)
    go(page, "tax", ".tl-item")
    item = page.locator(".tl-item", has_text="window.__xss=2").first
    assert title in item.inner_text()
    item.locator("button:has-text('Ask')").click()               # the title travels inside the button's onclick
    page.wait_for_selector("section#chat.on")
    assert page.evaluate("window.__xss") is None
    go(page, "tax", ".tl-item")
    item = page.locator(".tl-item", has_text="window.__xss=2").first
    item.locator("button:has-text('Mark done')").click()
    page.wait_for_function("CAL.some((c) => c.title.includes('window.__xss=2') && c.status === 'done')")
    assert page.evaluate("window.__xss") is None


def test_keyboard_reaches_nav_rows_and_file_inputs(page):
    nav = page.locator("#tabs button[data-tab=money]")
    assert nav.get_attribute("aria-label") == "Money"
    go(page, "money")
    assert nav.get_attribute("aria-current") == "page"
    assert page.locator("#tabs button[data-tab=home]").get_attribute("aria-current") is None
    go(page, "documents")
    page.focus("#fileIn")                                  # visually hidden, but focusable
    assert page.evaluate("document.activeElement.id") == "fileIn"
    go(page, "position")
    row = page.locator("tr.click").first
    row.focus()
    page.keyboard.press("Enter")
    page.locator("#dlg").wait_for(state="visible")
    page.keyboard.press("Escape")


def test_a_screen_that_fails_to_load_offers_a_retry(page):
    page.evaluate("window.__realLoader = loaders.goals; loaders.goals = async () => { throw new Error('disk on fire'); }; 0")
    go(page, "goals")
    banner = page.locator("section#goals .tab-error")
    banner.wait_for()
    assert "disk on fire" in banner.inner_text() and banner.get_attribute("role") == "alert"
    page.evaluate("loaders.goals = window.__realLoader; 0")
    banner.locator("button:has-text('Try again')").click()
    page.wait_for_function("!document.querySelector('section#goals .tab-error')")


def test_api_refuses_requests_without_the_page_token(page, app):
    # (browser contexts here bypass the page's Content-Security-Policy so the test can poll the page; the policy itself is checked here)
    r = page.request.get(app["url"] + "/")
    assert "connect-src 'self'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    r = page.request.get(app["url"] + "/home")
    assert r.status == 401 and "Session expired" in r.text()
    r = page.request.get(app["url"] + "/home", headers={"Origin": "https://evil.example"})
    assert r.status == 403


# ---------------------------------------------------------------- Ask AI: suggestions wait for approval
def test_chat_suggestion_waits_for_approval(page, monkeypatch):
    from aaryaai_finance import server as srv
    from aaryaai_finance.ai.providers import Event, Final
    acc = page.evaluate("api('/api/accounts')")[0]["id"]

    class Scripted:
        def __init__(self):
            self.turn = 0

        def stream(self, system, history, tools):
            self.turn += 1
            if self.turn == 1:
                yield Event("tool_start", name="add_transaction")
                yield Final([{"type": "tool_use", "id": "t1", "name": "add_transaction",
                              "input": {"kind": "expense", "account_id": acc, "amount": 12.34, "category": "Groceries"}}], "tool_use")
            else:
                yield Event("text", text="I proposed it.")
                yield Final([{"type": "text", "text": "I proposed it."}], "end_turn")

    monkeypatch.setattr(srv, "make_provider", lambda cfg, secret: Scripted())
    before = len(page.evaluate("api('/api/transactions')"))
    go(page, "chat")
    page.fill("#prompt", "log 12.34 for groceries")
    page.press("#prompt", "Enter")
    card = page.locator(".aiprop").last
    card.wait_for()
    assert "12.34" in card.inner_text() and len(page.evaluate("api('/api/transactions')")) == before
    card.locator("button:has-text('Approve')").click()
    card.locator(".chip:has-text('Approved')").wait_for()
    assert len(page.evaluate("api('/api/transactions')")) == before + 1


# ---------------------------------------------------------------- Money: import a bank statement
def test_import_a_statement_with_preview(page, tmp_path):
    csv = tmp_path / "statement.csv"
    csv.write_text("Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag\n"
                   "02.10.2026;Einkauf;UI test bakery;-7,40\n03.10.2026;Erstattung;UI test refund;12,00\n", encoding="utf-8")
    go(page, "money", "#impForm")
    page.wait_for_function("document.querySelectorAll('#impForm select option[value]:not([value=\"\"])').length > 0")
    before = len(page.evaluate("api('/api/transactions')"))
    page.set_input_files("#impFile", str(csv))
    dlg = page.locator("#impDlg")
    dlg.wait_for(state="visible")
    assert "2 new" in dlg.inner_text() and "UI test bakery" in dlg.inner_text()
    dlg.locator("tbody input[type=checkbox]").nth(1).uncheck()               # keep only the bakery
    dlg.locator("#impGo:has-text('Import 1 entry')").click()
    dlg.wait_for(state="hidden")
    after = page.evaluate("api('/api/transactions')")
    assert len(after) == before + 1 and any((t["note"] or "").startswith("UI test bakery") for t in after)


def test_category_rules_suggest_while_typing_and_in_the_import_preview(page, tmp_path):
    go(page, "money", "#txForm")
    page.click("#kindSeg button[data-k=expense]")
    page.fill("#txForm input[name=note]", "REWE Markt")
    page.wait_for_function("document.querySelector('#txForm select[name=category]').value === 'Groceries'")
    page.select_option("#txForm select[name=category]", "Eating out")                 # your own pick wins from now on
    page.fill("#txForm input[name=note]", "Stadtwerke")
    page.wait_for_timeout(700)
    assert page.eval_on_selector("#txForm select[name=category]", "e => e.value") == "Eating out"
    csv = tmp_path / "cats.csv"
    csv.write_text("Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag\n04.10.2026;Abschlag;Stadtwerke UI test;-80,00\n", encoding="utf-8")
    page.wait_for_function("document.querySelectorAll('#impForm select option').length > 0")
    page.set_input_files("#impFile", str(csv))
    sel = page.locator("#impDlg select[data-cat]").first
    sel.wait_for()
    assert sel.input_value() == "Utilities & internet" and "de_utilities" in sel.get_attribute("title")
    page.click("#impCancel")


# ---------------------------------------------------------------- first-time setup
def test_setup_wizard_on_an_empty_folder(browser, tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    server, url = _serve(fresh)
    try:
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(url + "/")
        pg.wait_for_selector("#wizard:not([hidden]) #wDir")
        assert pg.locator("#wDir").input_value() == str(fresh)
        pg.fill("#wName", "Robin")
        pg.click("#wizNext")
        pg.locator(".packpick label", has_text="Germany").click()
        pg.wait_for_selector("#wQs .qlist")
        pg.click("#wizNext")
        pg.click("#wizNext")
        pg.wait_for_selector("input[name=prov][value=none]", state="attached")
        pg.click("#wizNext")                                   # Finish setup
        pg.wait_for_selector("#wizard[hidden]", state="attached")
        pg.wait_for_function("document.querySelector('#homeHello').textContent.includes('Robin')")
        assert (fresh / "config.yaml").exists() and (fresh / "finance.db").exists()
        for tab in ["forecast", "goals", "diversify", "opportunities", "taxreturn"]:
            go(pg, tab)
        ctx.close()
        assert not errors, errors
    finally:
        server.should_exit = True


# ---------------------------------------------------------------- light and dark theme
def test_theme_follows_the_computer_and_can_be_chosen(browser, app):
    def open_(scheme):
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme=scheme, bypass_csp=True)
        pg = ctx.new_page()
        pg.goto(app["url"] + "/"); pg.wait_for_function("document.querySelector('#homeKpis .kpi')")
        return ctx, pg
    theme = "document.documentElement.dataset.theme"
    paper = "getComputedStyle(document.documentElement).getPropertyValue('--paper').trim()"
    slice2 = "charts.chCat.data.datasets[0].backgroundColor[1]"                       # doughnut colours are theme tokens too
    ctx, pg = open_("dark")
    assert pg.evaluate(theme) == "dark" and pg.evaluate(paper) == "#0e1a2d"
    go(pg, "position", "#chCat[role=img]")
    assert pg.evaluate(slice2) == "#fbbf24"
    ctx.close()
    ctx, pg = open_("light")
    assert pg.evaluate(theme) == "light" and pg.evaluate(paper) == "#f4f6fb"           # "System" is the default
    go(pg, "position", "#chCat[role=img]")
    assert pg.evaluate(slice2) == "#b45309"
    go(pg, "settings", "#themeSeg")
    assert pg.get_attribute("#themeSeg [data-theme-mode=system]", "aria-pressed") == "true"
    pg.click("#themeSeg [data-theme-mode=dark]")
    assert pg.evaluate(theme) == "dark" and pg.get_attribute("#themeSeg [data-theme-mode=dark]", "aria-pressed") == "true"
    assert pg.get_attribute('meta[name="theme-color"]', "content") == "#0e1a2d"
    pg.reload(); pg.wait_for_load_state("load")
    assert pg.evaluate(theme) == "dark"                                                 # remembered in this browser
    go(pg, "settings", "#themeSeg")
    pg.click("#themeSeg [data-theme-mode=system]")
    assert pg.evaluate(theme) == "light"
    ctx.close()
