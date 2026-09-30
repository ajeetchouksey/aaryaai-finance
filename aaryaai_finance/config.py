"""Where your data lives and how the app is configured.

Everything personal is stored in ONE folder you choose (the "data folder"):

    <data folder>/
      config.yaml          your settings: countries, currencies, folders, AI provider
      secrets.json         API keys (never leaves your computer; not in config.yaml)
      finance.db           accounts, transactions, goals, chats (SQLite)
      rules/*.yaml         your own document & deadline rules (override the country packs)
      packs/<CODE>/pack.yaml   your own country packs (optional)
      trackers/*.yaml      property purchases and other trackers
      documents/           default place where filed documents go (can point elsewhere)

The app remembers which data folder you picked in a tiny pointer file in your user
profile (%APPDATA%/aaryaai-finance/location.json on Windows, ~/.config/... elsewhere).
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import yaml

APP_NAME = "aaryaai-finance"

DEFAULT_CONFIG: dict = {
    "version": 1,
    "profile": {"name": "", "about": "", "answers": {}},
    "countries": [],
    "base_currency": "EUR",
    "extra_currencies": [],
    "documents_root": "documents",
    "folders": {},              # e.g. {"DE": "Germany", "IN": "India", "inbox": "_Inbox"}
    "fx": {"source": "ecb", "manual_rates": {}},
    "ai": {"provider": "none", "model": "", "endpoint": "", "deployment": "", "api_version": "2024-10-21",
           "web_search": True},
}

SECRET_KEYS = ["anthropic_api_key", "azure_openai_api_key", "github_token", "ollama_api_key"]


def pointer_file() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME / "location.json"


def default_data_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "aaryaai-finance-data"


def remembered_data_dir() -> Path | None:
    p = pointer_file()
    try:
        d = Path(json.loads(p.read_text(encoding="utf-8"))["data_dir"])
        return d if d.is_dir() else None
    except Exception:  # noqa: BLE001
        return None


def remember_data_dir(d: Path) -> None:
    p = pointer_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"data_dir": str(d)}), encoding="utf-8")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Settings:
    """A data folder plus its parsed config."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.config = _merge(DEFAULT_CONFIG, self._read_yaml(self.config_path))

    # paths
    @property
    def config_path(self) -> Path: return self.data_dir / "config.yaml"
    @property
    def secrets_path(self) -> Path: return self.data_dir / "secrets.json"
    @property
    def db_path(self) -> Path: return self.data_dir / "finance.db"
    @property
    def rules_dir(self) -> Path: return self.data_dir / "rules"
    @property
    def packs_dir(self) -> Path: return self.data_dir / "packs"
    @property
    def trackers_dir(self) -> Path: return self.data_dir / "trackers"
    @property
    def inbox_dir(self) -> Path: return self.data_dir / ".inbox"

    @property
    def documents_root(self) -> Path:
        r = Path(os.path.expandvars(str(self.config.get("documents_root") or "documents"))).expanduser()
        return (r if r.is_absolute() else self.data_dir / r).resolve()

    @property
    def is_configured(self) -> bool:
        return self.config_path.exists() and bool(self.config.get("countries"))

    @property
    def currencies(self) -> list[str]:
        from .packs import load_packs  # local import to avoid a cycle
        packs = load_packs(self)
        cs = [self.config["base_currency"]]
        for c in self.config.get("countries", []):
            if c in packs and packs[c].get("currency") not in cs:
                cs.append(packs[c]["currency"])
        for c in self.config.get("extra_currencies", []):
            if c not in cs:
                cs.append(c)
        return cs

    # io
    @staticmethod
    def _read_yaml(p: Path) -> dict:
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return {}

    def save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for d in (self.rules_dir, self.trackers_dir):
            d.mkdir(exist_ok=True)
        self.config_path.write_text(
            "# aaryaai-finance settings — safe to edit by hand; the app re-reads it on restart.\n"
            + yaml.safe_dump(self.config, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def secrets(self) -> dict:
        try:
            return json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def set_secret(self, key: str, value: str) -> None:
        if key not in SECRET_KEYS:
            raise ValueError(key)
        s = self.secrets()
        if value:
            s[key] = value.strip()
        else:
            s.pop(key, None)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.secrets_path.write_text(json.dumps(s, indent=2), encoding="utf-8")
        try:
            os.chmod(self.secrets_path, 0o600)
        except OSError:
            pass

    def secret(self, key: str) -> str:
        env = {"anthropic_api_key": "ANTHROPIC_API_KEY", "azure_openai_api_key": "AZURE_OPENAI_API_KEY",
               "github_token": "GITHUB_TOKEN"}.get(key)
        return self.secrets().get(key) or (os.environ.get(env, "") if env else "")

    def public(self) -> dict:
        """Config safe to send to the browser (no secrets, just whether they're set)."""
        c = copy.deepcopy(self.config)
        c["data_dir"] = str(self.data_dir)
        c["documents_root_resolved"] = str(self.documents_root)
        c["secrets_set"] = {k: bool(self.secret(k)) for k in SECRET_KEYS}
        c["configured"] = self.is_configured
        return c
