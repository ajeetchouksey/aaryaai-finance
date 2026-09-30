"""AI providers — all optional. The app works fully without any of them.

Conversation history is stored in one neutral shape (Anthropic-style content blocks:
text / tool_use / tool_result). Each provider converts to and from its own wire format,
so you can switch provider mid-way and old chats still load.

  anthropic      Claude via api.anthropic.com                         key: anthropic_api_key
  azure_openai   Azure OpenAI / Azure AI Foundry deployment            key: azure_openai_api_key
  github_models  GitHub Models (models.github.ai), GitHub token        key: github_token
  ollama         A model running on your own computer (localhost)     no key
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterator

import httpx

PROVIDERS = {
    "none": {"label": "No AI", "needs": []},
    "anthropic": {"label": "Claude (Anthropic API)", "needs": ["anthropic_api_key"], "default_model": "claude-sonnet-5-5",
                  "models": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5-20251001"],
                  "help": "Create a key at platform.claude.com → Settings → API keys. Billed per use, separate from Claude Pro."},
    "azure_openai": {"label": "Azure OpenAI / AI Foundry (Microsoft)", "needs": ["azure_openai_api_key"], "default_model": "",
                     "help": "Endpoint like https://<resource>.openai.azure.com, your deployment name, and a key from the Azure portal (Keys and Endpoint)."},
    "github_models": {"label": "GitHub Models (Microsoft, free tier)", "needs": ["github_token"], "default_model": "openai/gpt-4.1",
                      "models": ["openai/gpt-4.1", "openai/gpt-4.1-mini", "openai/gpt-4o", "meta/Llama-3.3-70B-Instruct"],
                      "help": "Create a fine-grained GitHub token with the 'Models: read' permission (github.com/settings/tokens). Free tier has daily limits."},
    "ollama": {"label": "Ollama (runs on your computer)", "needs": [], "default_model": "qwen2.5:7b",
               "models": ["qwen2.5:7b", "llama3.1:8b", "mistral-nemo"],
               "help": "Install from ollama.com, then run: ollama pull qwen2.5:7b. Nothing leaves your computer. Pick a model that supports tools."},
}


@dataclass
class Event:
    kind: str            # text | tool_start | done | error
    text: str = ""
    name: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class Final:
    content: list        # neutral content blocks
    stop: str            # end_turn | tool_use
    usage: dict = field(default_factory=dict)


class ProviderError(Exception):
    pass


def make_provider(cfg: dict, secret) -> "BaseProvider | None":
    kind = (cfg or {}).get("provider", "none")
    model = cfg.get("model") or PROVIDERS.get(kind, {}).get("default_model", "")
    if kind == "anthropic":
        k = secret("anthropic_api_key")
        return AnthropicProvider(k, model, cfg.get("web_search", True)) if k else None
    if kind == "azure_openai":
        k, ep, dep = secret("azure_openai_api_key"), (cfg.get("endpoint") or "").rstrip("/"), cfg.get("deployment") or model
        if not (k and ep and dep):
            return None
        if "/openai/v1" in ep:
            url, params = f"{ep}/chat/completions", {}
        else:
            url, params = f"{ep}/openai/deployments/{dep}/chat/completions", {"api-version": cfg.get("api_version") or "2024-10-21"}
        return OpenAICompatProvider(url, {"api-key": k}, dep, params)
    if kind == "github_models":
        k = secret("github_token")
        return OpenAICompatProvider("https://models.github.ai/inference/chat/completions",
                                    {"Authorization": f"Bearer {k}"}, model) if k else None
    if kind == "ollama":
        ep = (cfg.get("endpoint") or "http://localhost:11434").rstrip("/")
        return OpenAICompatProvider(f"{ep}/v1/chat/completions", {}, model)
    return None


class BaseProvider:
    name = "base"

    def stream(self, system: str, messages: list, tools: list) -> Iterator[Event | Final]:
        raise NotImplementedError

    def complete(self, prompt: str, max_tokens: int = 300) -> str:
        text = ""
        for ev in self.stream("", [{"role": "user", "content": prompt}], []):
            if isinstance(ev, Event) and ev.kind == "text":
                text += ev.text
            elif isinstance(ev, Event) and ev.kind == "error":
                raise ProviderError(ev.text)
        return text


# ------------------------------------------------------------------ Anthropic
class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, key: str, model: str, web_search: bool = True):
        import anthropic
        self.client, self.model, self.web_search = anthropic.Anthropic(api_key=key), model, web_search

    def stream(self, system, messages, tools):
        tl = list(tools) + ([{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}] if self.web_search and tools else [])
        kw = {"model": self.model, "max_tokens": 4096, "messages": messages}
        if system:
            kw["system"] = system
        if tl:
            kw["tools"] = tl
        try:
            with self.client.messages.stream(**kw) as s:
                for ev in s:
                    if ev.type == "content_block_start" and ev.content_block.type in ("tool_use", "server_tool_use"):
                        yield Event("tool_start", name=ev.content_block.name)
                    elif ev.type == "content_block_delta" and ev.delta.type == "text_delta":
                        yield Event("text", text=ev.delta.text)
                fm = s.get_final_message()
        except Exception as e:  # noqa: BLE001
            if self.web_search and "web_search" in str(e):
                self.web_search = False
                yield from self.stream(system, messages, tools)
                return
            yield Event("error", text=_friendly(e))
            return
        yield Final([b.model_dump(exclude_none=True) for b in fm.content], "tool_use" if fm.stop_reason == "tool_use" else "end_turn",
                    {"in": fm.usage.input_tokens, "out": fm.usage.output_tokens})


# ------------------------------------------------------------------ OpenAI-compatible (Azure, GitHub Models, Ollama)
def to_openai_messages(system: str, messages: list) -> list:
    out = [{"role": "system", "content": system}] if system else []
    for m in messages:
        c = m["content"]
        if m["role"] == "user":
            if isinstance(c, str):
                out.append({"role": "user", "content": c})
            else:
                for b in c:
                    if b.get("type") == "tool_result":
                        cont = b.get("content")
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                    "content": cont if isinstance(cont, str) else json.dumps(cont)})
                    elif b.get("type") == "text":
                        out.append({"role": "user", "content": b["text"]})
        else:
            text = "".join(b.get("text", "") for b in c if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}}
                     for b in c if b.get("type") == "tool_use"]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    return out


def to_openai_tools(tools: list) -> list:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
            for t in tools if "input_schema" in t]


class OpenAICompatProvider(BaseProvider):
    name = "openai-compatible"

    def __init__(self, url: str, headers: dict, model: str, params: dict | None = None):
        self.url, self.headers, self.model, self.params = url, {"Content-Type": "application/json", **headers}, model, params or {}

    def stream(self, system, messages, tools):
        body = {"model": self.model, "messages": to_openai_messages(system, messages), "stream": True}
        ot = to_openai_tools(tools)
        if ot:
            body["tools"] = ot
        text, calls, finish = "", {}, "stop"
        try:
            with httpx.stream("POST", self.url, params=self.params, headers=self.headers, json=body, timeout=120) as r:
                if r.status_code >= 400:
                    raise ProviderError(f"HTTP {r.status_code}: {r.read().decode('utf8', 'ignore')[:300]}")
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        j = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    for ch in j.get("choices", []):
                        d = ch.get("delta") or {}
                        if d.get("content"):
                            text += d["content"]
                            yield Event("text", text=d["content"])
                        for tc in d.get("tool_calls") or []:
                            slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] = fn["name"]
                                yield Event("tool_start", name=fn["name"])
                            slot["args"] += fn.get("arguments") or ""
                        if ch.get("finish_reason"):
                            finish = ch["finish_reason"]
        except Exception as e:  # noqa: BLE001
            yield Event("error", text=_friendly(e))
            return
        blocks = [{"type": "text", "text": text}] if text else []
        for i, c in sorted(calls.items()):
            try:
                args = json.loads(c["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            blocks.append({"type": "tool_use", "id": c["id"] or f"call_{i}", "name": c["name"], "input": args})
        yield Final(blocks, "tool_use" if calls else "end_turn")


def _friendly(e: Exception) -> str:
    s = str(e)
    low = s.lower()
    if "401" in s or "authentication" in low or "unauthorized" in low or "api_key" in low or "invalid api key" in low:
        return "The AI provider rejected your key or token. Check it in Settings → AI."
    if "credit" in low or "billing" in low or "quota" in low or "429" in s:
        return "The AI provider says you're out of credit or over your rate limit. Try later or check your plan."
    if "connecterror" in low or "connection refused" in low or "11434" in s:
        return "Couldn't reach the AI provider. For Ollama, make sure it's running (ollama serve)."
    if "404" in s or "not found" in low or "deploymentnotfound" in low:
        return "Model or deployment not found — check the model / deployment name in Settings → AI."
    return f"AI provider error: {s[:300]}"
