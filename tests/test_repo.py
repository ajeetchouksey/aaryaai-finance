"""Repository checks: vendored JavaScript matches the versions listed in THIRD_PARTY.md."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "aaryaai_finance" / "web" / "vendor"
FILES = {"Chart.js": "chart.umd.js", "marked": "marked.min.js", "DOMPurify": "purify.min.js"}


def test_vendored_versions_match_third_party_md():
    table = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    for name, fname in FILES.items():
        listed = re.search(rf"\[{re.escape(name)}\]\([^)]*\) \| ([\d.]+) \|", table)
        assert listed, f"{name} has no version in THIRD_PARTY.md"
        head = (VENDOR / fname).read_text(encoding="utf-8")[:400]
        assert re.search(rf"v?{re.escape(listed.group(1))}\b", head), f"{fname} is not version {listed.group(1)}"
