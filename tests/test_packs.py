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


def test_unsafe_or_broken_rules_are_refused():
    from aaryaai_finance.rules.engine import pattern_problem, check_rule
    for bad in [r"(a+)+$", r"(\w|\d)*x", r"((a)|b)+", r"(?:\s*\d)+", "(", "x" * 400]:
        assert pattern_problem(bad), bad
    for ok in [r"Invoice No\.?\s*(\d+)", r"([A-Z]{2,3}\d{7,8})", r"(ab){2,}", r"(x[+*])+"]:
        assert pattern_problem(ok) is None, ok
    assert check_rule({"id": "r", "match": {"text_any": ["a"]}, "route": {"folder": "../../etc"}})
    assert check_rule({"id": "r", "match": {"text_any": ["a"]}, "confidence": 3})
    assert check_rule({"id": "r", "match": {}})


def test_user_pack_problems_are_reported_and_isolated(tmp_path):
    from aaryaai_finance.config import Settings
    from aaryaai_finance.packs import available_packs
    from aaryaai_finance.context import Ctx
    s = Settings(tmp_path / "d")
    (s.packs_dir / "FR").mkdir(parents=True)
    (s.packs_dir / "FR" / "pack.yaml").write_text(
        "code: FR\nname: France\ncurrency: EUR\n"
        "calculators: [{id: x, engine: does_not_exist}]\n"
        "deadlines: [{id: d1, title: T, due: '{year}-05-31', if: nope}]\n"
        "document_rules: [{id: fr_bad, match: {text_any: [facture]}, extract: [{name: n, pattern: '(a+)+'}]}]\n", encoding="utf-8")
    (s.packs_dir / "XX").mkdir()
    (s.packs_dir / "XX" / "pack.yaml").write_text("code: [unclosed", encoding="utf-8")
    packs = available_packs(s)
    errs = " | ".join(packs["FR"]["_errors"])
    assert "unknown engine" in errs and "doesn't match any question" in errs and "freeze" in errs
    assert packs["FR"]["calculators"] == []                   # broken calculator dropped, pack still usable
    assert "!XX" in packs and "YAML syntax" in packs["!XX"]["_errors"][0]
    s.config["countries"] = ["FR"]; s.save()
    c = Ctx(s)
    assert "fr_bad" not in [r["id"] for r in c.rules.document_rules]
    assert any("fr_bad" in e for e in c.rules.errors)
