<p align="center"><img src="aaryaai_finance/web/brand/logo-horizontal-dark.svg" height="44" alt="aaryaai"></p>

# aaryaai finance

**A personal finance manager that runs on your own computer.** Net worth across countries and currencies, income and spending, goals, tax deadlines and calculators, document filing and investment learning — all driven by readable rules you can check and change. An AI assistant is optional.

- **Local-first.** One folder on your disk holds everything: settings, database, your rules. Nothing is uploaded. No account, no cloud.
- **Multi-country, multi-currency.** Countries are *packs* of YAML rules. Germany 🇩🇪 and India 🇮🇳 ship built in; add your own with a template.
- **Deterministic.** Documents are sorted and deadlines are created by rules — same input, same result, every time. The Rules tab shows exactly which rule fired and why.
- **Your data model, your way.** Record types, fields and links are defined in JSON; countries and you can add fields or whole new record types (insurance policies, loans…) without code. Links are enforced, and everything exports to JSON.
- **Locked down.** Only the app's own page can talk to it (host, origin and session-token checks), API keys live in your system keychain, and shared rules are validated before use.
- **AI if you want it.** Plug in **Claude** (Anthropic API), **Azure OpenAI / AI Foundry**, **GitHub Models** or **Ollama** (fully offline). The assistant reads your numbers through tools; it can't see files.

> Estimates only. The tax calculators and deadlines are there to help you prepare — confirm filings with a tax adviser.

## Quick start

You need **Python 3.10+**.

```bash
pipx install git+https://github.com/ajeetchouksey/aaryaai-finance
aaryaai-finance
```

No pipx? `pip install git+https://github.com/ajeetchouksey/aaryaai-finance` works too.
On Windows you can instead download the repo and double-click **`start.bat`** (it creates a virtual environment the first time).

Your browser opens at <http://127.0.0.1:8770> and a four-step setup asks for:

1. **Where** — the data folder (default `~/Documents/aaryaai-finance-data`; a OneDrive/iCloud folder gives you backups for free)
2. **Countries** — tick your packs, choose a base currency, answer a few yes/no questions that decide which deadlines apply
3. **Documents** — where filed documents go; point it at an existing folder to keep your structure
4. **AI** — optional; pick a provider and paste its key

Options: `aaryaai-finance --data-dir PATH --port 8770 --no-browser`. The app only listens on `127.0.0.1`.

## What's inside

| Tab | What it does |
|---|---|
| **Position** | Net worth by currency and in your base currency, cash cushion, what's coming up, staged purchases (e.g. a flat paid in instalments) |
| **Money** | Accounts per country, income/expense/transfer, repeating entries (daily → yearly), monthly charts |
| **Documents** | Drop PDFs, images, Excel or Word files: text is extracted, the rules decide type and folder, you confirm the move |
| **Goals / Plan** | Inflation-aware goal planning, budget, emergency fund |
| **Invest / Learn** | Holdings, SIP simulator, strategy backtests and paper trading on synthetic or real prices — no live trading |
| **Tax** | Deadlines from your packs, calculators (e.g. German refund estimate, India old vs new regime), checklists |
| **Rules** | Test a document against the rules, write your own rules in YAML |
| **Ask AI** | Chat that can read your snapshot, run calculators, add transactions and mark deadlines done |

## Your data folder

```
aaryaai-finance-data/
  config.yaml         settings — safe to edit by hand
  secrets.json        which API keys are set (the keys are in your system keychain)
  finance.db          SQLite database, generated from the data model
  model.json          your own fields and record types (optional)
  backups/            automatic copies before any database change
  rules/*.yaml        your own document & deadline rules
  packs/XX/pack.yaml  your own or overridden country packs (optional)
  trackers/*.yaml     staged purchases, e.g. a flat under construction
  documents/          filed documents (or any folder you choose)
```

Back up the folder and you've backed up everything, or use **Settings → Export everything (JSON)**. See [PRIVACY.md](PRIVACY.md).

## Architecture

```
browser tab (plain JS) ──token──▶ FastAPI on 127.0.0.1 ──▶ SQLite (finance.db)
                                   │                          ▲
                                   ├─ rules engine ◀── packs/*.yaml, your rules, trackers
                                   ├─ data model   ◀── model/core.json + pack & user extensions
                                   └─ AI provider (optional): Claude · Azure OpenAI · GitHub Models · Ollama
```

The model is the single source of truth for storage: tables, links (foreign keys), validation and the forms for your own record types are all generated from it. Upgrades back up the database, then migrate it in place. Details in [CONTRIBUTING.md](CONTRIBUTING.md).

## AI providers

| Provider | What you need | Data leaves your computer? |
|---|---|---|
| Claude (Anthropic API) | API key from console.anthropic.com (pay per use; a Claude Pro plan doesn't include API use) | yes, to Anthropic |
| Azure OpenAI / AI Foundry | endpoint, deployment name, key | yes, to your Azure tenant |
| GitHub Models | GitHub token with *Models: read* | yes, to GitHub |
| Ollama | `ollama pull qwen2.5:7b` | **no** |

Keys are stored in your system keychain. They can also come from environment variables `ANTHROPIC_API_KEY`, `AZURE_OPENAI_API_KEY`, `GITHUB_TOKEN`. Microsoft 365 Copilot isn't supported: its API needs an M365 Copilot licence and is grounded in company data, not a personal app. Details: [docs/ai-providers.md](docs/ai-providers.md).

## Adding a country or your own rules

- **Your own rules:** Rules tab → *Insert an example* → save. Same `id` as a pack rule replaces it.
- **A new country:** copy `aaryaai_finance/packs/_template` → `packs/XX/pack.yaml`, fill it in. Put it in your data folder's `packs/` to use it privately, or open a pull request.

Syntax and examples: [CONTRIBUTING.md](CONTRIBUTING.md) and [examples/](examples/).

## Development

```bash
git clone https://github.com/ajeetchouksey/aaryaai-finance && cd aaryaai-finance
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,market]"
pytest
aaryaai-finance --data-dir ./dev-data
```

Python (FastAPI + SQLite) backend, plain JavaScript frontend with no build step. Charts, fonts and libraries are vendored so the app works offline ([THIRD_PARTY.md](THIRD_PARTY.md)).

## Licence

MIT — see [LICENSE](LICENSE).
