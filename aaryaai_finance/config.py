"""Where your data lives and how the app is configured.

Everything personal is stored in ONE folder you choose (the "data folder"):

    <data folder>/
      config.yaml          your settings: countries, currencies, folders, AI provider
      secrets.json         which API keys are set; the keys themselves are in the OS keychain when there is one
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
    def model_path(self) -> Path: return self.data_dir / "model.json"
    @property
    def backups_dir(self) -> Path: return self.data_dir / "backups"
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

    # ---- secrets: OS keychain when available (Windows Credential Manager, macOS Keychain, Secret Service),
    # otherwise secrets.json in the data folder (owner-only permissions). The file then only says "keychain".
    KEYCHAIN = "keychain"

    def _keyring(self):
        if os.environ.get("AARYAAI_NO_KEYRING"):
            return None
        try:
            import keyring
            kr = keyring.get_keyring()
            if getattr(kr, "priority", 0) <= 0 or type(kr).__module__.startswith(("keyring.backends.fail", "keyring.backends.null")):
                return None
            return keyring
        except Exception:  # noqa: BLE001
            return None

    def _kr_user(self, key: str) -> str:
        """Keychain entry name. Uses an id stored in secrets.json, so keys survive moving or renaming the data folder."""
        s = self.secrets()
        if not s.get("_id"):
            import uuid
            s["_id"] = uuid.uuid4().hex[:16]
            self._write_secrets(s)
        return f"{key}@{s['_id']}"

    def secrets(self) -> dict:
        try:
            return json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _write_secrets(self, s: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not s:
            if self.secrets_path.exists():
                self.secrets_path.write_text("{}", encoding="utf-8")
            return
        self.secrets_path.write_text(json.dumps(s, indent=2), encoding="utf-8")
        try:
            os.chmod(self.secrets_path, 0o600)
        except OSError:
            pass

    @property
    def secret_storage(self) -> str:
        return "keychain" if self._keyring() else "file"

    def set_secret(self, key: str, value: str) -> None:
        if key not in SECRET_KEYS:
            raise ValueError(key)
        kr = self._keyring()
        user = self._kr_user(key) if kr else None           # creates the stable id first, so it isn't overwritten below
        s = self.secrets()
        value = (value or "").strip()
        if kr:
            try:
                if value:
                    kr.set_password("aaryaai-finance", user, value)
                else:
                    kr.delete_password("aaryaai-finance", user)
            except Exception:  # noqa: BLE001  — keychain locked/unavailable: fall back to the file
                kr = None
        if value:
            s[key] = self.KEYCHAIN if kr else value
        else:
            s.pop(key, None)
        self._write_secrets(s)

    def secret(self, key: str) -> str:
        env = {"anthropic_api_key": "ANTHROPIC_API_KEY", "azure_openai_api_key": "AZURE_OPENAI_API_KEY",
               "github_token": "GITHUB_TOKEN"}.get(key)
        v = self.secrets().get(key) or ""
        if v == self.KEYCHAIN:
            kr = self._keyring()
            try:
                v = (kr.get_password("aaryaai-finance", self._kr_user(key)) if kr else "") or ""
            except Exception:  # noqa: BLE001
                v = ""
        return v or (os.environ.get(env, "") if env else "")

    def migrate_secrets(self) -> list[str]:
        """Move keys still stored in plain text into the keychain (when there is one)."""
        if not self._keyring():
            return []
        moved = [k for k, v in self.secrets().items() if k in SECRET_KEYS and v and v != self.KEYCHAIN]
        for k in moved:
            self.set_secret(k, self.secrets()[k])
        return moved

    def public(self) -> dict:
        """Config safe to send to the browser (no secrets, just whether they're set)."""
        c = copy.deepcopy(self.config)
        c["data_dir"] = str(self.data_dir)
        c["documents_root_resolved"] = str(self.documents_root)
        c["secrets_set"] = {k: bool(self.secret(k)) for k in SECRET_KEYS}
        c["secrets_storage"] = self.secret_storage
        c["configured"] = self.is_configured
        return c
