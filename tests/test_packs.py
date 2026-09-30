"""Guards for the shipped country packs and for privacy of the public repo."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKS = sorted((ROOT / "aaryaai_finance" / "packs").glob("*/pack.yaml"))
INPUT_KEYS = {"id", "label", "type", "default", "from_answer", "options", "step", "min", "max", "help", "placeholder"}


def test_packs_parse_cleanly():
    assert PACKS
    for f in PACKS:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        if f.parent.name.startswith("_"):
            continue
        for k in ("code", "name", "currency"):
            assert d.get(k), f"{f}: missing {k}"
        for c in d.get("calculators") or []:
            for i in c.get("inputs", []):
                assert set(i) <= INPUT_KEYS, f"{f} {c['id']}: odd keys {set(i) - INPUT_KEYS} (unquoted comma in a label?)"
        for q in d.get("questions") or []:
            assert set(q) <= {"id", "label", "type", "help"}, f"{f}: question {q}"
        ids = [r["id"] for r in d.get("document_rules") or []] + [r["id"] for r in d.get("deadlines") or []]
        assert len(ids) == len(set(ids)), f"{f}: duplicate rule ids"


def test_no_personal_data_in_repo():
    """The public repo must never contain the author's personal details."""
    banned = [r"\bGera\b", r"\bAjeet\b", r"Chouksey", r"ajeet\.k\.", r"ajeet_planner", r"1a806", r"[A-Z]{5}[0-9]{4}[A-Z]"]  # last = Indian PAN shape
    skip = {".git", "__pycache__", ".pytest_cache", "node_modules", "vendor", ".venv", "venv", "build", "dist"}
    for p in ROOT.rglob("*"):
        if p.is_dir() or skip & set(p.relative_to(ROOT).parts) or any(x.endswith(".egg-info") for x in p.parts) or p.suffix in {".png", ".woff2", ".ico", ".pyc"} or p.name == "test_packs.py":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in banned:
            m = re.search(pat, text)
            assert not m, f"{p.relative_to(ROOT)} contains {m.group(0)!r}"


def test_examples_are_valid():
    from aaryaai_finance.core.trackers import load_trackers, summarize
    from aaryaai_finance.rules.engine import validate_rules_yaml
    for f in (ROOT / "examples" / "rules").glob("*.yaml"):
        assert validate_rules_yaml(f.read_text(encoding="utf-8")) == [], f
    ts = load_trackers(ROOT / "examples" / "trackers")
    assert ts and all("_error" not in t for t in ts)
    s = summarize(ts[0])
    assert s["stages_paid"] == 3 and s["remaining"] == 9500000 - 2850000 and s["projection"]
