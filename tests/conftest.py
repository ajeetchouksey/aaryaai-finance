import re

from fastapi.testclient import TestClient


def local_client(app) -> TestClient:
    """A client that behaves like the app's own browser tab: loopback host + the session token from the page."""
    c = TestClient(app, base_url="http://127.0.0.1:8770")
    token = re.search(r'name="session-token" content="([^"]+)"', c.get("/").text).group(1)
    c.headers["X-Session-Token"] = token
    return c


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_keychain(monkeypatch):
    """Tests never touch the machine's real keychain (the keychain test uses an in-memory stand-in)."""
    monkeypatch.setenv("AARYAAI_NO_KEYRING", "1")


@pytest.fixture(autouse=True)
def _no_real_app_settings(monkeypatch, tmp_path_factory):
    """Tests never read or write the real settings of Claude Desktop, VS Code or this app.
    Every place mcp_setup and config look for them points into a throw-away folder (tests may override it)."""
    root = tmp_path_factory.mktemp("isolated-home")
    for var, sub in (("APPDATA", "roaming"), ("LOCALAPPDATA", "local"), ("XDG_CONFIG_HOME", "config"), ("AARYAAI_FAKE_HOME", "home")):
        monkeypatch.setenv(var, str(root / sub))



@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Lets UI tests take a screenshot when they fail (see tests/test_ui_e2e.py)."""
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        item.rep_call = rep
