# Changelog

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
