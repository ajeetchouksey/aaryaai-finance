"""The website builds, fills every placeholder, and publishes a valid latest.json."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_site_builds_without_leftover_placeholders(tmp_path):
    pytest.importorskip("markdown")
    out = tmp_path / "_site"
    r = subprocess.run([sys.executable, str(ROOT / "site/build_site.py"), "--out", str(out), "--skip-demo"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    from aaryaai_finance import __version__
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert latest["version"] == __version__ and latest["download_url"].endswith(f"v{__version__}.zip")
    for page in [out / "index.html", *(out / "docs").glob("*.html")]:
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"\{\{\w+\}\}", html), f"unfilled placeholder in {page.name}"
    docs = {p.name for p in (out / "docs").glob("*.html")}
    assert {"getting-started.html", "privacy.html", "changelog.html", "rules-and-packs.html"} <= docs
    links = re.findall(r'href="([^"#]+\.html)"', (out / "docs" / "getting-started.html").read_text(encoding="utf-8"))
    for l in links:
        if not l.startswith("http"):
            assert (out / "docs" / l).exists(), f"broken docs link {l}"


def test_demo_data_is_fictional():
    text = (ROOT / "site/demo_data.py").read_text(encoding="utf-8")
    assert "invented" in text.lower()
