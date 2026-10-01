# Changelog

## 0.5.1 — 2026-10-01

### One-click MCP setup
- The app connects itself to **Claude Desktop** and **VS Code (GitHub Copilot)**: a **Connect** button per app in Routines → Connections, a checkbox in the setup wizard, or `aaryaai-finance mcp --setup all` (`--status`, `--remove`).
- It adds one entry to the app's MCP settings, leaves other entries alone and keeps a backup of the file. Unreadable files are never changed; VS Code files with comments are handled.
- New **Setup guide** in the docs.


## 0.5.0 — 2026-09-30

A new look and a set of planning tools. Everything works without AI; AI only adds optional extras.

### New look
- A **Home** screen: a warning when a payment would push a currency below its floor, key figures, what's coming up, goal odds and the routine inbox.
- Flatter, calmer panels and a sidebar grouped into Plan, Records, Tax and More.

### Planning
- **Cash forecast**: 12 months per currency.
  - It uses your balances, repeating entries, planned items, the stages of a staged purchase, and your usual spending (learned from the last six months). Each line says how sure it is: known, planned, estimated or learned.
  - A **floor** per currency and a **funding plan** that proposes the transfer to make before a big payment.
  - Scenarios: late salary, early stage, no estimated income, weaker currency.
- **Goal odds**: each goal replayed in 2,000 simulated markets.
  - Shows the chance of reaching it, the range of outcomes, and the monthly saving for 85%.
  - A slider to try other amounts, where the monthly surplus goes, a glide path, and what-ifs.
- **Diversify**: looks inside index funds to show countries, currencies, sectors and the biggest companies.
  - Checks concentration against your own rules and compares with your target mix.
  - Shows the tax-cheapest way to rebalance.
- **Opportunities**: tax-aware checks from the country packs.
  - India: the yearly tax-free long-term gains allowance, and the days until a holding turns long-term.
  - Germany: moving the Freistellungsauftrag, cash for the Vorabpauschale, and the loss certificate deadline.

### Tax return workspace
- Per country and year:
  - which documents are found or missing
  - numbers read from documents
  - the questions an adviser would ask
  - what makes a difference, with an estimate
  - a filing sheet for ELSTER or ITR-2, exportable as CSV or JSON for your adviser
- Germany and India included. Defined in each pack's `tax_workspace:` section.
- With AI connected: one tailored follow-up question.

### Routines, proposals and audit log
- Routines run while the app is open:
  - forecast refresh
  - deadline sweep
  - monthly review
  - tax-year prep
  - exchange rates
- They only suggest. Proposals wait for your approval.
- Every approval, routine run, MCP call and data change is in the audit log.

### MCP server
- `aaryaai-finance mcp` lets Claude Desktop, VS Code (Copilot) and other MCP apps read your numbers over a local stdio connection, with no network port. They can also suggest transactions and planned items for you to approve. See [MCP](docs/mcp.md).
- The in-app assistant can use the same forecast, odds, diversification, opportunities and tax tools.

### Data model
- Model version 3 adds:
  - planned items
  - proposals, audit log, routine runs and tax-year answers
  - holdings: asset class, what they track, bought date, income type and yearly cost
  - goals: how the money is invested
- German accounts gain: investment income this year, and losses this year.
- The first start backs up your database and migrates it in place, as before.


## 0.4.0 — 2026-09-30

### Website and live demo
- New project website with docs and a **live demo** you can click through in the browser. The demo is the real app replaying answers recorded from it on invented sample data, so it always matches the current version. Nothing you do in the demo is saved or sent anywhere.
- New **Getting started** guide.

### Update notice
- The app checks the website's `latest.json` at most once a day and shows a small notice when a newer version is out, with what's new and how to update. It never downloads or installs anything by itself. Switch it off in **Settings → Your data**, or press **Check now** there.

## 0.3.0 — 2026-09-30

### Hide amounts
- One click (the eye button, or **Alt+H**) masks every amount in the app — cards, tables, charts, tooltips, and amounts written inside text such as deadline titles, tracker notes and chat answers. Percentages, dates and exchange rates stay visible, so the screens still make sense.
- Handy for screen-sharing, presenting or working in public. The choice is remembered on this computer, so the app can open with amounts hidden.

## 0.2.0 — 2026-09-30

### Data model in JSON
- The database is now generated from `aaryaai_finance/model/core.json`: every record type, field, type and link in one readable file.
- Country packs can add fields (a `model:` section in `pack.yaml`). Germany adds *Freistellungsauftrag* per bank; India adds the *NRE / NRO / resident* account type. They only appear on that country's records.
- You can add your own fields and whole new record types (insurance policies, loans, subscriptions…) in **Settings → Custom fields & record types** or `<data folder>/model.json`. New record types get their own list and forms automatically.
- Links between records are enforced: a transaction can't point to a missing account, and an account in use can't be deleted (archive it instead).
- Every value is checked against the model before saving (dates, amounts, currency codes, allowed options).
- **Export / import everything as JSON** from Settings. Import is all-or-nothing, checks every link first, and backs up your current data.

### Upgrading from 0.1
Nothing to do. On first start the app backs up `finance.db` to `backups/`, rebuilds the tables with links enforced, keeps any column it no longer uses (inside the record, not deleted), keeps any value that doesn't fit the new rules next to the corrected one, and repairs broken links without deleting anything: a transaction whose account was missing is attached to a new archived "Recovered" account. Net-worth history is renamed from `*_eur` to base-currency columns.

### Security
- The local API now only answers the app's own page: requests with another `Host` (DNS rebinding), from another website (`Origin`), or without the per-start session token are refused.
- Security headers (Content-Security-Policy with `connect-src 'self'`, no framing, no referrer) and no public API docs.
- API keys are stored in the operating system's keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service) when available; keys found in `secrets.json` are moved there automatically.
- Country packs and rules are validated on load; a broken rule, calculator or pack is skipped and reported in Settings instead of breaking the app. Regex patterns that could freeze the app ("catastrophic backtracking") are refused, and patterns from packs or your rules run in a separate short-lived process that is stopped after 2 seconds. Document routes can't point outside your documents folder.
- Changing your own data model is tried on a copy of the database first; if it wouldn't work (e.g. making a field unique when records have duplicates) nothing is changed. A `model.json` that can't be applied never stops the app from starting — it is ignored and reported in Settings, and Export still includes all your tables.
- Dependency ranges capped below the next major version; Dependabot, CodeQL and `pip-audit` added to the repository.

### Fixes
- Net-worth snapshots were stored in columns named `…_eur` even when the base currency wasn't EUR. History is now converted to your current base currency when shown.
- Savings rate on Position uses this month's entries until you have a full month of data.

## 0.1.0 — 2026-09-30
First release.
