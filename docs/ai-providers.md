# Connecting an AI assistant

The assistant is optional. It answers questions using tools that read your snapshot (net worth, accounts, goals, deadlines), run the country calculators, add transactions, save goals and tick off deadlines. Choose a provider in **Settings → AI assistant** (or during setup). Keys are stored in `secrets.json` in your data folder.

## Claude (Anthropic API)

1. Create an account at <https://console.anthropic.com>, add a small prepaid credit, and create an API key.
2. Paste the key (`sk-ant-…`). Models: `claude-sonnet-*` (best balance), `claude-haiku-*` (cheapest).
3. Optional: *web search* lets Claude look up current rules; it costs a little extra per search.

A Claude Pro/Max subscription doesn't include API use; the API is billed separately per token. Typical personal use is a few euros a month.

## Azure OpenAI / Azure AI Foundry

1. In the Azure portal create an **Azure OpenAI** resource (or an AI Foundry project) and **deploy** a model such as `gpt-4.1` or `gpt-4o-mini`.
2. Copy the **endpoint** (`https://<name>.openai.azure.com`), the **deployment name**, and a **key**.
3. API version defaults to `2024-10-21`. Endpoints ending in `/openai/v1` are also accepted.

Good fit if your organisation already uses Microsoft: data stays in your Azure tenant under your own policies.

## GitHub Models

1. Create a fine-grained personal access token at <https://github.com/settings/tokens> with the **Models: read** permission.
2. Paste it; default model `openai/gpt-4.1`. Free within GitHub's rate limits — enough for occasional chats.

## Ollama (fully local)

1. Install from <https://ollama.com> and run `ollama pull qwen2.5:7b` (or `llama3.1:8b`).
2. Choose Ollama; the address defaults to `http://localhost:11434`.

Nothing leaves your computer. Pick a model with tool-calling support; smaller models make more mistakes.

## What about Microsoft 365 Copilot?

The Microsoft 365 Copilot Chat API requires an M365 Copilot licence, an Entra ID app registration, and answers from your organisation's Microsoft 365 data — it isn't built for a personal app with its own tools. Use Azure OpenAI or GitHub Models for Microsoft-hosted models instead.

## Adding a provider

Anything with an OpenAI-compatible `/chat/completions` endpoint (streaming + tools) can reuse `OpenAICompatProvider` in `aaryaai_finance/ai/providers.py`: add an entry to `PROVIDERS` and a branch in `make_provider`.
