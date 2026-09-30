"""Country packs: everything country-specific, as data (YAML), not code.

A pack = aaryaai_finance/packs/<CODE>/pack.yaml (built in) or <data>/packs/<CODE>/pack.yaml
(yours). A user pack with the same code replaces the built-in one. Copy packs/_template to
add a country — see CONTRIBUTING.md.
"""
from __future__ import annotations

from pathlib import Path

import yaml

BUILTIN = Path(__file__).parent
_cache: dict = {}


def validate_pack(d) -> list[str]:
    """Structural checks for a pack. Problems are reported in Settings; broken parts are skipped, the rest still loads."""
    import re
    from ..rules.engine import check_rule
    from ..tax.engines import ENGINES
    if not isinstance(d, dict):
        return ["pack.yaml must be a mapping"]
    e = []
    if not re.fullmatch(r"[A-Z]{2}", str(d.get("code", ""))):
        e.append("code must be a 2-letter country code (e.g. FR)")
    if not re.fullmatch(r"[A-Z]{3}", str(d.get("currency", ""))):
        e.append("currency must be a 3-letter code (e.g. EUR)")
    if not d.get("name"):
        e.append("name is missing")
    qids = set()
    for q in d.get("questions") or []:
        if not isinstance(q, dict) or not q.get("id") or not q.get("label"):
            e.append("each question needs id and label")
        else:
            qids.add(q["id"])
    for c in d.get("calculators") or []:
        if not isinstance(c, dict) or not c.get("id"):
            e.append("each calculator needs an id"); continue
        if c.get("engine") not in ENGINES:
            e.append(f"calculator {c['id']}: unknown engine '{c.get('engine')}' (available: {', '.join(sorted(ENGINES))})")
    for r in d.get("deadlines") or []:
        if not isinstance(r, dict) or not all(r.get(k) for k in ("id", "title", "due")):
            e.append("each deadline needs id, title and due"); continue
        cond = str(r.get("if", "")).lstrip("!")
        if cond and cond not in qids:
            e.append(f"deadline {r['id']}: 'if: {r['if']}' doesn't match any question id")
    for r in d.get("document_rules") or []:
        e += check_rule(r)
    from ..tax.opportunities import ENGINES as OPP
    for o in d.get("opportunities") or []:
        if not isinstance(o, dict) or o.get("engine") not in OPP:
            e.append(f"opportunity {o.get('id') if isinstance(o, dict) else o}: unknown engine (available: {', '.join(sorted(OPP))})")
    if d.get("tax_workspace") is not None:
        from ..tax.workspace import validate_workspace
        e += validate_workspace(d["tax_workspace"])
    m = d.get("model")
    if m is not None and not isinstance(m, dict):
        e.append("model must be a mapping with 'extends' and/or 'entities'")
    return e


def _read(p: Path) -> dict:
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as ex:
        return {"code": p.parent.name, "name": p.parent.name, "_errors": [f"YAML syntax: {ex}"], "_path": str(p), "_broken": True}
    if not isinstance(d, dict):
        d = {}
    errs = validate_pack(d)
    d.setdefault("code", p.parent.name)
    d["_errors"] = errs
    # drop parts that would break at run time; the rest of the pack still works
    from ..tax.engines import ENGINES
    d["calculators"] = [c for c in d.get("calculators") or [] if isinstance(c, dict) and c.get("engine") in ENGINES]
    from ..tax.opportunities import ENGINES as OPP
    d["opportunities"] = [o for o in d.get("opportunities") or [] if isinstance(o, dict) and o.get("engine") in OPP]
    if d.get("tax_workspace") is not None:
        from ..tax.workspace import validate_workspace
        if validate_workspace(d["tax_workspace"]):
            d.pop("tax_workspace")
    d["_source"] = "user" if "packs" in p.parts[-3:-1] and BUILTIN not in p.parents else "built-in"
    d["_path"] = str(p)
    return d


def available_packs(settings=None) -> dict:
    """All packs: built-in first, then user packs overriding by code."""
    out = {}
    for p in sorted(BUILTIN.glob("*/pack.yaml")):
        if p.parent.name.startswith("_"):
            continue
        d = _read(p)
        if d.get("_broken"):
            continue
        d["_source"] = "built-in"
        out[d["code"]] = d
    if settings is not None and settings.packs_dir.exists():
        for p in sorted(settings.packs_dir.glob("*/pack.yaml")):
            d = _read(p)
            if d.get("_broken"):
                out[f"!{p.parent.name}"] = d          # listed so the error can be shown, never loaded
                continue
            d["_source"] = "yours"
            out[d["code"]] = d
    return out


def load_packs(settings) -> dict:
    """Only the packs switched on in config (countries), keyed by code."""
    allp = available_packs(settings)
    return {c: allp[c] for c in settings.config.get("countries", []) if c in allp}


def pack_summary(p: dict) -> dict:
    return {"code": p["code"], "name": p.get("name"), "flag": p.get("flag", ""), "currency": p.get("currency"),
            "default_folder": p.get("default_folder", p.get("name")), "source": p.get("_source"),
            "questions": p.get("questions", []), "description": p.get("description", ""), "errors": p.get("_errors", [])}


def folder_for(settings, packs: dict, key: str) -> str:
    """Resolve a logical folder key (a country code, 'inbox', ...) to a path under documents_root."""
    f = settings.config.get("folders", {})
    if key in f and f[key]:
        return f[key]
    if key in packs:
        return packs[key].get("default_folder", packs[key].get("name", key))
    return {"inbox": "_Inbox"}.get(key, key)
