"""The local API must only answer this computer's own browser tab."""
import pytest
from fastapi.testclient import TestClient

from aaryaai_finance.server import create_app
from conftest import local_client


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "ad"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "ad"))
    return create_app(tmp_path / "data")


def test_dns_rebinding_is_blocked(app):
    evil = TestClient(app, base_url="http://attacker.example:8770")
    assert evil.get("/").status_code == 403
    assert evil.get("/setup/status").status_code == 403
    ok = local_client(app)
    assert ok.get("/setup/status").status_code == 200
    assert TestClient(app, base_url="http://localhost:8770").get("/").status_code == 200


def test_session_token_required(app):
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    assert c.get("/").status_code == 200                       # the page itself (it carries the token)
    assert c.get("/static/app.js").status_code == 200          # static assets hold no data
    assert c.get("/setup/status").status_code == 401
    assert c.get("/config", headers={"X-Session-Token": "guess"}).status_code == 401
    good = local_client(app)
    tok = good.headers["X-Session-Token"]
    assert c.get(f"/setup/status?t={tok}").status_code == 200  # links (e.g. open a document) pass it in the URL


def test_other_websites_cannot_post(app):
    c = local_client(app)
    r = c.post("/config", json={"profile": {"name": "x"}}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.post("/config", json={"profile": {"name": "x"}}, headers={"Origin": "null"})
    assert r.status_code == 403
    r = c.post("/config", json={}, headers={"Origin": "http://127.0.0.1:9999"})   # other local port = other app
    assert r.status_code == 403


def test_token_changes_every_start(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "ad"))
    a = local_client(create_app(tmp_path / "d")).headers["X-Session-Token"]
    b = local_client(create_app(tmp_path / "d")).headers["X-Session-Token"]
    assert a != b and len(a) >= 40


def test_security_headers_and_no_api_docs(app):
    c = local_client(app)
    h = c.get("/").headers
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert "connect-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    for p in ("/docs", "/openapi.json", "/redoc"):
        assert c.get(p).status_code == 404


class MemoryKeyring:
    """Stand-in for the OS keychain."""
    priority = 1

    def __init__(self):
        self.d = {}

    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))
    def delete_password(self, s, u): self.d.pop((s, u), None)


def test_api_keys_go_to_the_keychain(tmp_path, monkeypatch):
    import keyring
    from aaryaai_finance.config import Settings
    for v in ("GITHUB_TOKEN", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY", "AARYAAI_NO_KEYRING"):
        monkeypatch.delenv(v, raising=False)
    kr = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: kr)
    monkeypatch.setattr(keyring, "set_password", kr.set_password)
    monkeypatch.setattr(keyring, "get_password", kr.get_password)
    monkeypatch.setattr(keyring, "delete_password", kr.delete_password)
    s = Settings(tmp_path / "d")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "secrets.json").write_text('{"anthropic_api_key": "sk-ant-OLD-PLAINTEXT"}')
    assert s.migrate_secrets() == ["anthropic_api_key"]
    assert "sk-ant" not in (tmp_path / "d" / "secrets.json").read_text()           # file no longer holds it
    assert s.secret("anthropic_api_key") == "sk-ant-OLD-PLAINTEXT"
    s.set_secret("github_token", "ghp_x")
    assert s.secret("github_token") == "ghp_x" and s.public()["secrets_storage"] == "keychain"
    s.set_secret("github_token", "")
    assert s.secret("github_token") == "" and not kr.d.get(("aaryaai-finance", s._kr_user("github_token")))


def test_file_fallback_without_keychain(tmp_path, monkeypatch):
    from aaryaai_finance.config import Settings
    monkeypatch.setenv("AARYAAI_NO_KEYRING", "1")
    s = Settings(tmp_path / "d")
    s.set_secret("anthropic_api_key", "sk-ant-abc")
    assert s.secret("anthropic_api_key") == "sk-ant-abc" and s.public()["secrets_storage"] == "file"
    assert "sk-ant-abc" not in str(s.public())


def test_keychain_keys_survive_moving_the_data_folder(tmp_path, monkeypatch):
    import shutil
    import keyring
    from aaryaai_finance.config import Settings
    monkeypatch.delenv("AARYAAI_NO_KEYRING", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kr = MemoryKeyring()
    for n in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, n, getattr(kr, n))
    monkeypatch.setattr(keyring, "get_keyring", lambda: kr)
    a = Settings(tmp_path / "A"); a.set_secret("anthropic_api_key", "sk-ant-move-me")
    shutil.move(str(tmp_path / "A"), str(tmp_path / "B"))
    assert Settings(tmp_path / "B").secret("anthropic_api_key") == "sk-ant-move-me"


def test_document_filing_rejects_bad_references(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "ad"))
    c = local_client(create_app(tmp_path / "d"))
    c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["DE"], "base_currency": "EUR"})
    r = c.post("/docs/file", json={"sha256": "../finance", "filename": "x.pdf", "folder": "x"})
    assert r.status_code == 400 and (tmp_path / "d" / "finance.db").exists()
    assert c.post("/config/secret/clear", json={"key": "nope"}).status_code == 400


def test_slow_rule_patterns_are_stopped():
    import time
    from aaryaai_finance.rules.engine import run_patterns
    t = time.time()
    with pytest.raises(TimeoutError):
        run_patterns([(r"(a+)+$", 0, "a" * 40 + "!")])
    assert time.time() - t < 5
    assert run_patterns([(r"(\d+)", 0, "no 42")]) == [("42", ("42",))]


def test_update_check_is_daily_quiet_and_optional(tmp_path):
    from aaryaai_finance import updates, __version__
    calls = []
    def fake(): calls.append(1); return {"version": "99.0.0", "notes_url": "https://x/notes", "install": "pipx install ..."}
    cache = tmp_path / "u.json"
    r = updates.check(cache, fetch=fake, now=1000.0)
    assert r["newer"] and r["latest"]["version"] == "99.0.0" and r["current"] == __version__
    updates.check(cache, fetch=fake, now=1000.0 + 3600)                   # within a day: no new request
    assert len(calls) == 1
    updates.check(cache, fetch=fake, now=1000.0 + 90000)
    assert len(calls) == 2
    assert updates.check(cache, enabled=False, fetch=fake) == {"current": __version__, "enabled": False}
    def offline(): raise OSError("no network")
    r = updates.check(tmp_path / "v.json", fetch=offline, now=5.0)
    assert r["newer"] is False and "no network" in r["error"]              # offline never breaks anything
    assert updates.parse_version("0.10.0") > updates.parse_version("0.9.9")
    same = updates.check(tmp_path / "w.json", fetch=lambda: {"version": __version__}, now=5.0)
    assert same["newer"] is False
