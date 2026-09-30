"""Run the real app on the sample data, click through every screen, and record what the API answered.

The public demo replays these recordings in the browser, so it always matches the real app and needs no server.
Also takes the screenshots used on the landing page.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

SKIP = ("/static/",)


def request_key(method: str, url: str, body: str | None) -> str:
    """Same function as keyOf() in demo.js — keep them in step."""
    u = urlsplit(url)
    q = sorted((k, v) for k, v in parse_qsl(u.query) if k != "t")
    key = f"{method.upper()} {u.path}" + (f"?{urlencode(q)}" if q else "")
    if method.upper() != "GET" and body:
        try:
            body = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except ValueError:
            pass
        key += "#" + hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
    return key


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _serve(data_dir: Path, port: int):
    import uvicorn
    from aaryaai_finance.server import create_app
    cfg = uvicorn.Config(create_app(data_dir), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return server
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("app did not start")


async def _crawl(base: str, shots: Path) -> dict:
    from playwright.async_api import async_playwright
    rec: dict = {}
    errors: list[str] = []

    async def on_response(r):
        u = urlsplit(r.url)
        if u.path == "/" or u.path.startswith(SKIP):
            return
        try:
            body = await r.text()
        except Exception:  # noqa: BLE001
            return
        req = r.request
        rec[request_key(req.method, r.url, req.post_data)] = {"status": r.status, "type": r.headers.get("content-type", ""), "body": body}

    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        pg.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.goto(base + "/#position")
        await pg.wait_for_timeout(1800)

        async def tab(t, wait=1400):
            await pg.evaluate(f"go('{t}')")
            await pg.wait_for_timeout(wait)

        await tab("position", 1800)
        await pg.screenshot(path=str(shots / "position.png"))
        await tab("money")
        for label in ("Day", "Week", "Year", "Month"):
            b_ = pg.locator(f"#periodSeg button:has-text('{label}'), .seg button:has-text('{label}')").first
            if await b_.count():
                await b_.click(); await pg.wait_for_timeout(600)
        for ccy in ("INR", "USD", "EUR"):
            b_ = pg.locator(f"#ccySeg button:has-text('{ccy}')").first
            if await b_.count():
                await b_.click(); await pg.wait_for_timeout(600)
        await pg.screenshot(path=str(shots / "money.png"))
        for t in ("documents", "goals", "plan", "invest", "learn"):
            await tab(t, 1800)
        # run each strategy once so the demo can replay real backtests
        sel = pg.locator("#btForm select").first
        opts = await sel.locator("option").evaluate_all("os => os.map(o => o.value)") if await sel.count() else [None]
        for v in opts:
            if v is not None:
                await sel.select_option(v)
            await pg.click("#btForm button"); await pg.wait_for_timeout(1500)
        await pg.click("#sipForm button"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(shots / "learn.png"))
        await tab("goals"); await pg.screenshot(path=str(shots / "goals.png"))
        await tab("tax", 1800)
        calcs = pg.locator("#calcs form button:has-text('Calculate'), #calcs button:has-text('Calculate')")
        for i in range(await calcs.count()):
            await calcs.nth(i).click(); await pg.wait_for_timeout(500)
        await pg.evaluate("scrollTo(0,0)")
        await pg.screenshot(path=str(shots / "tax.png"))
        await tab("rules", 1600)
        await tab("settings", 1800)
        btn = pg.locator("button:has-text('Insurance policy')").first
        if await btn.count():
            await btn.click(); await pg.wait_for_timeout(900)
        await tab("chat", 1200)
        await pg.evaluate("api('/setup/options')")
        await pg.wait_for_timeout(500)
        # hide-amounts view for the landing page
        await tab("position", 1600)
        await pg.keyboard.press("Alt+KeyH"); await pg.wait_for_timeout(3200)     # let the toast fade
        await pg.screenshot(path=str(shots / "hidden.png"))
        await pg.keyboard.press("Alt+KeyH"); await pg.wait_for_timeout(600)
        # phone size
        m = await b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        m.on("response", lambda r: asyncio.ensure_future(on_response(r)))
        await m.goto(base + "/#position"); await m.wait_for_timeout(2200)
        await m.screenshot(path=str(shots / "mobile.png"))
        await b.close()
    if errors:
        raise RuntimeError("page errors while recording: " + "; ".join(errors[:3]))
    return rec


def record(data_dir: Path, out_dir: Path) -> dict:
    """Returns the recordings; writes screenshots into out_dir/shots."""
    shots = out_dir / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    server = _serve(data_dir, port)
    try:
        rec = asyncio.run(_crawl(f"http://127.0.0.1:{port}", shots))
    finally:
        server.should_exit = True
    return rec
