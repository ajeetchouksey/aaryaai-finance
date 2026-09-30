"""Update check: at most once a day, fetch latest.json from the project website and compare versions.

Sends nothing but a plain request for that one public file. Switch it off in Settings (updates.check: false).
Never downloads or installs anything by itself — it only tells you a new version exists.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import __version__

LATEST_URL = os.environ.get("AARYAAI_UPDATE_URL", "https://ajeetchouksey.github.io/aaryaai-finance/latest.json")
CHECK_EVERY = 24 * 3600


def parse_version(v: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def fetch_latest(url: str | None = None, timeout: float = 5.0) -> dict:
    url = url or LATEST_URL
    import httpx
    r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": f"aaryaai-finance/{__version__}"})
    r.raise_for_status()
    d = r.json()
    if not isinstance(d, dict) or "version" not in d:
        raise ValueError("unexpected update file")
    return d


def check(cache: Path, enabled: bool = True, force: bool = False, fetch=fetch_latest, now: float | None = None) -> dict:
    now = now or time.time()
    out = {"current": __version__, "enabled": enabled}
    if not enabled:
        return out
    cached = {}
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if force or "checked" not in cached or now - float(cached["checked"]) > CHECK_EVERY:
        try:
            latest = fetch()
            cached = {"checked": now, "latest": {k: latest.get(k) for k in ("version", "released", "notes_url", "download_url", "install", "notes")}}
        except Exception as e:  # noqa: BLE001 — offline or site down: try again tomorrow, never bother the user
            cached = {"checked": now, "latest": cached.get("latest"), "error": str(e)[:200]}
        try:
            cache.write_text(json.dumps(cached), encoding="utf-8")
        except OSError:
            pass
    latest = cached.get("latest") or {}
    out.update({"checked": cached.get("checked"), "latest": latest, "error": cached.get("error"),
                "newer": bool(latest.get("version")) and parse_version(latest["version"]) > parse_version(__version__)})
    return out
