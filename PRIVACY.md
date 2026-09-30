# Privacy

**aaryaai finance runs on your computer and keeps your data there.** There is no server, no account and no telemetry.

## What is stored, and where

Everything lives in the data folder you chose during setup:

| File | Contains |
|---|---|
| `config.yaml` | your settings: name, countries, currencies, folders, AI provider (no keys) |
| `secrets.json` | API keys. Only read by the local server; never sent to the browser or written to `config.yaml` |
| `finance.db` | accounts, transactions, goals, holdings, deadlines you ticked off, chat history |
| `rules/`, `packs/`, `trackers/` | your own YAML rules |
| documents folder | files you chose to file |

The app listens only on `127.0.0.1`, so other devices on your network can't open it.

## When the app uses the internet

| What | When | What is sent |
|---|---|---|
| Exchange rates (European Central Bank via frankfurter.dev) | right after setup, and when you press refresh (Settings or Invest) | the currency codes |
| Market prices (Yahoo Finance via `yfinance`, optional) | when you refresh prices in Invest | ticker symbols |
| Your AI provider | only if you connected one: when you chat, and when you upload a document no rule is sure about (under 60%) | your question, the numbers the assistant asks for through its tools, and for documents the first part of the extracted text |

With **Ollama** as provider, AI stays on your computer too. With no AI provider, nothing about your finances ever leaves the machine.

## Backups and deletion

Copy the data folder to back up. Delete it to remove everything. The app never deletes your documents; it only moves a file after you click to confirm.
