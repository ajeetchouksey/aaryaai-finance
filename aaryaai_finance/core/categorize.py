"""Category rules: a payee or description sets the category, the same way every time.

Rules are YAML (`category_rules:`) in your rules files and the country packs; yours come first and the first match wins.
Matching ignores case, spaces and punctuation, like document rules: `text_any: [rewe]` matches "REWE Markt GmbH".
"""
from __future__ import annotations

from ..rules.engine import squash


def check_category_rule(r) -> list[str]:
    if not isinstance(r, dict) or not r.get("id"):
        return ["a category rule needs an id"]
    rid, errs = r["id"], []
    if not isinstance(r.get("category"), str) or not r["category"].strip():
        errs.append(f"{rid}: category is required")
    m = r.get("match")
    if not isinstance(m, dict) or not (m.get("text_any") or m.get("text_all")):
        errs.append(f"{rid}: match needs text_any or text_all")
    else:
        for k in ("text_any", "text_all"):
            v = m.get(k)
            if v is not None and not (isinstance(v, list) and all(isinstance(w, (str, int)) and len(squash(str(w))) >= 3 for w in v)):
                errs.append(f"{rid}: match.{k} must be a list of words of at least 3 letters")
    if r.get("kind") not in (None, "income", "expense"):
        errs.append(f"{rid}: kind must be income or expense")
    return errs


def categorize(text: str, kind: str | None, rules: list[dict]) -> tuple[str | None, str | None]:
    """(category, rule id) of the first rule that matches, or (None, None)."""
    sq = squash(text or "")
    if not sq:
        return None, None
    for r in rules:
        if r.get("kind") and kind and r["kind"] != kind:
            continue
        m = r["match"]
        words_all, words_any = m.get("text_all") or [], m.get("text_any") or []
        if all(squash(str(w)) in sq for w in words_all) and (not words_any or any(squash(str(w)) in sq for w in words_any)):
            return r["category"], r["id"]
    return None, None
