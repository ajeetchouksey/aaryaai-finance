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


def _read(p: Path) -> dict:
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
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
        d["_source"] = "built-in"
        out[d["code"]] = d
    if settings is not None and settings.packs_dir.exists():
        for p in sorted(settings.packs_dir.glob("*/pack.yaml")):
            d = _read(p)
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
            "questions": p.get("questions", []), "description": p.get("description", "")}


def folder_for(settings, packs: dict, key: str) -> str:
    """Resolve a logical folder key (a country code, 'inbox', ...) to a path under documents_root."""
    f = settings.config.get("folders", {})
    if key in f and f[key]:
        return f[key]
    if key in packs:
        return packs[key].get("default_folder", packs[key].get("name", key))
    return {"inbox": "_Inbox"}.get(key, key)
