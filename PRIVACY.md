# Privacy

**aaryaai finance runs on your computer and keeps your data there.** There is no server, no account and no telemetry.

## What is stored, and where

Everything lives in the data folder you chose during setup:

| File | Contains |
|---|---|
| `config.yaml` | your settings: name, countries, currencies, folders, AI provider (no keys) |
| `secrets.json` | Which API keys are set. The keys themselves are in your system keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service); only if there is none are they kept in this file (owner-only permissions). Never sent to the browser. |
| `finance.db` | accounts, transactions, goals, holdings, deadlines you ticked off, chat history |
| `model.json` | your own fields and record types (optional) |
| `backups/` | automatic copies of `finance.db` made before a database update or an import |
| (in `finance.db`) | planned items, tax-return answers, routine results, proposals and the audit log |
| `rules/`, `packs/`, `trackers/` | your own YAML rules |
| documents folder | files you chose to file |

The app listens only on `127.0.0.1`, so other devices on your network can't open it. It also refuses requests from other websites open in your browser: every request must come from the app's own page (checked by `Host` and `Origin`) and carry a session token that changes each time the app starts.

The data isn't encrypted by the app. Turn on disk encryption (BitLocker on Windows, FileVault on macOS) to protect it if your computer is lost, and be careful where you sync the data folder.

## When the app uses the internet

| What | When | What is sent |
|---|---|---|
| Exchange rates (European Central Bank via frankfurter.dev) | right after setup, and when you press refresh (Settings or Invest) | the currency codes |
| Market prices (Yahoo Finance via `yfinance`, optional) | when you refresh prices in Invest | ticker symbols |
| Update check (the project website on GitHub Pages) | at most once a day; switch off in Settings → Your data | nothing but a request for the public `latest.json` file; the app never downloads or installs anything by itself |
| Your AI provider | only if you connected one: when you chat, and when you upload a document no rule is sure about (under 60%) | your question, the numbers the assistant asks for through its tools, and for documents the first part of the extracted text |

| MCP apps you connect (Claude Desktop, VS Code…) | only while that app runs `aaryaai-finance mcp` on this computer | what its tools return (your numbers) goes to that app, and from there to its own AI provider; every call is in the audit log |
| Monthly review AI summary (optional) | once a month, if an AI provider is connected and the option is on (Routines) | last month's totals, savings rate and the biggest category change |
| Tax follow-up question (optional) | when you press "Ask me one more question" | your answers in the tax workspace and which documents are missing |

With **Ollama** as provider, AI stays on your computer too. With no AI provider, nothing about your finances ever leaves the machine.

## Routines and proposals

Routines run on your computer while the app is open. They only read your data and write proposals; nothing changes until you approve a proposal. Switch routines off on the Routines screen or start the app with `--no-routines`.

## Backups and deletion

Copy the data folder to back up. Delete it to remove everything. The app never deletes your documents; it only moves a file after you click to confirm.
