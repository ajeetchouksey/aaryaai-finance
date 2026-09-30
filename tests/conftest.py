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
