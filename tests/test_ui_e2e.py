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
    go(page, "diversify", "#dvXray .xr")
    assert page.locator("#tgtForm input[name=shares]").input_value() == "40"   # nothing was saved


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
    assert page.locator("#rtList .rt-item").count() == 5
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
def test_hide_amounts(page):
    nw = page.locator("#homeKpis .kpi").first
    assert "•" not in nw.inner_text()
    page.keyboard.press("Alt+KeyH")
    page.wait_for_function("document.body.classList.contains('amounts-hidden')")
    page.wait_for_function("document.querySelector('#homeKpis .kpi').innerText.includes('•')")
    page.keyboard.press("Alt+KeyH")
    page.wait_for_function("!document.querySelector('#homeKpis .kpi').innerText.includes('•')")


def test_api_refuses_requests_without_the_page_token(page, app):
    # (browser contexts here bypass the page's Content-Security-Policy so the test can poll the page; the policy itself is checked here)
    r = page.request.get(app["url"] + "/")
    assert "connect-src 'self'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"
    r = page.request.get(app["url"] + "/home")
    assert r.status == 401 and "Session expired" in r.text()
    r = page.request.get(app["url"] + "/home", headers={"Origin": "https://evil.example"})
    assert r.status == 403


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
