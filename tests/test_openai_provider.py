"""The OpenAI-compatible path (Azure OpenAI, GitHub Models, Ollama) against a local fake server
that streams a tool call, then a text answer — the same wire format those services use."""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def fake_llm():
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse
    app, seen = FastAPI(), []

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        seen.append(body)
        has_tool_result = any(m["role"] == "tool" for m in body["messages"])

        def gen():
            if not has_tool_result and body.get("tools"):
                chunks = [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "list_deadlines", "arguments": ""}}]}}]},
                          {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"include_done\": false}"}}]}}]},
                          {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}]
            else:
                chunks = [{"choices": [{"delta": {"content": "You have "}}]}, {"choices": [{"delta": {"content": "deadlines."}, "finish_reason": "stop"}]}]
            for c in chunks:
                yield f"data: {json.dumps(c)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True); th.start()
    for _ in range(50):
        if srv.started: break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", seen
    srv.should_exit = True


def test_tool_loop_over_openai_wire(fake_llm, tmp_path, monkeypatch):
    url, seen = fake_llm
    monkeypatch.setenv("APPDATA", str(tmp_path / "ad")); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "ad"))
    from fastapi.testclient import TestClient
    from aaryaai_finance.server import create_app
    from conftest import local_client
    c = local_client(create_app(tmp_path / "boot"))
    c.post("/setup/apply", json={"data_dir": str(tmp_path / "d"), "countries": ["IN"], "base_currency": "INR",
                                 "ai": {"provider": "ollama", "endpoint": url, "model": "fake"}})
    assert c.get("/chat/meta").json()["ready"] is True
    assert c.post("/ai/test").json()["ok"] is True
    out = c.post("/chat/send", json={"text": "What's due?"}).text
    assert "event: tool" in out and "list_deadlines" in out and "event: done" in out
    # second request carried the tool result back in OpenAI format
    last = seen[-1]["messages"]
    assert last[-1]["role"] == "tool" and last[-2]["tool_calls"][0]["id"] == "call_1"
    chat = c.get("/chat/1").json()["messages"]
    assert chat[-1]["text"].strip() == "You have deadlines." and chat[-1]["tools"] == ["Checked your deadlines"]
