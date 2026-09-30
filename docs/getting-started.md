# Getting started

This takes about five minutes. You need a computer with Windows, macOS or Linux and [Python 3.10 or newer](https://www.python.org/downloads/). On Windows, tick "Add Python to PATH" when installing it.

## 1. Install

**Windows, the easy way:** download the latest version from the [home page](../#download), unzip it anywhere (for example `Documents\aaryaai-finance`), and double-click `start.bat`. The first start takes a minute while it sets itself up.

**Any system, with pipx:**

```bash
pipx install git+https://github.com/ajeetchouksey/aaryaai-finance
aaryaai-finance
```

Your browser opens at `http://127.0.0.1:8770`. The app only runs while that window is open.

## 2. Answer four setup questions

1. **Your data folder.** Everything goes here: settings, database, your own rules. A folder inside Documents or a synced drive like OneDrive gives you backups for free.
2. **Your countries.** Tick every country you have money or tax in, pick the currency totals are shown in, and answer a few yes/no questions. The answers decide which deadlines apply to you — for example "Do you have to file a German tax return every year?"
3. **Your documents folder.** Point it at the folder where you already keep bank statements and payslips, and the app files new documents into the same structure. It never deletes anything.
4. **AI (optional).** Skip it; everything works without. You can connect Claude, Azure OpenAI, GitHub Models or Ollama later in Settings.

## 3. Add what you have

- **Position → Add account or debt:** your bank accounts with today's balance, then property, pensions, loans and anything else you own or owe.
- **Money → Add an entry:** your salary and rent, set to repeat monthly. They'll be logged for you each month.
- **Goals:** what you're saving for and by when. The app works out what that costs after inflation and what to put aside each month.
- **Documents:** drop a few files. Check where the app suggests filing them, then click to move them.

## 4. Check the Tax tab

Deadlines come from your country packs and your answers in step 2. Tick them off as you go. The calculators give quick estimates, such as a German refund or India's old vs new regime. They're estimates only, so confirm filings with a tax adviser.

## Everyday tips

- **Hide amounts:** press **Alt+H** (or the eye button) before sharing your screen.
- **Your own rules:** the **Rules** tab shows why a document went where it did, and lets you add rules for anything the packs don't know.
- **Your own fields:** in Settings, under Custom fields, you can add fields like "IBAN last 4 digits" to accounts, or new record types like insurance policies.
- **Backups:** copy the data folder, or use **Settings → Export everything (JSON)**.
- **Updates:** the app tells you when a new version is out. Your data is backed up automatically before any database change.

Next: [how rules and country packs work](../CONTRIBUTING.md) · [connecting an AI](ai-providers.md) · [privacy](../PRIVACY.md)
