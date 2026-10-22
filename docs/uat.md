# Acceptance test guide (UAT)

A manual check before a release. The browser tests (`pytest -m ui`) cover most of the clicking. This guide adds what they can't: real AI providers, Claude Desktop and VS Code, other operating systems, and how it feels.

Use the invented sample data, never your own:

```bash
python -c "from pathlib import Path; import sys; sys.path.insert(0, 'site'); import demo_data; demo_data.build(Path('uat-data'))"
aaryaai-finance --data-dir uat-data
```

Tick each line. Anything that fails goes into an issue with the steps and a screenshot (amounts hidden).

## 1. Install and first start

- [ ] A fresh install with `pipx install` starts and opens the browser at `http://127.0.0.1:8770`.
- [ ] On Windows, `start.bat` creates its virtual environment on the first run and starts the app.
- [ ] An empty data folder shows the four-step setup. Each step can be finished with the keyboard alone.
- [ ] `aaryaai-finance --version` prints the version from `aaryaai_finance/__init__.py`.

## 2. Every screen

For each screen in the sidebar, at laptop width and at phone width (360 px):

- [ ] It loads without an error message and without sideways scrolling.
- [ ] Alt+H hides every amount, including charts, tooltips and text. Percentages and dates stay.
- [ ] With no AI connected, nothing is broken or blank. AI-only buttons say what they need.

## 3. Main flows

- [ ] **Money:** add an income, an expense, a transfer between currencies and a repeating entry. Totals and charts update.
- [ ] **Cash forecast:** switch each scenario. Set a floor and see the warning and the funding plan.
- [ ] **Goals:** move the slider. The chance and the saving for 85% change.
- [ ] **Diversify:** a target mix that doesn't add up to 100% is refused.
- [ ] **Documents:** drop a PDF payslip and a CSV. The rule that fired is shown. Nothing moves until you confirm.
- [ ] **Tax return:** answer a question, reload, and the answer is still there. Export CSV and JSON.
- [ ] **Routines:** run a routine. Approve one proposal and dismiss another. Both appear in the audit log.
- [ ] **Settings:** export everything as JSON, then import it into an empty folder. The data matches.

## 4. AI providers (each one you can test)

- [ ] **Claude**, **Azure OpenAI**, **GitHub Models**, **Ollama:** "Test connection" works with a valid key and gives a clear message with a wrong one.
- [ ] Ask "How am I doing?" The answer uses your numbers, and amounts are hidden when Alt+H is on.

## 5. MCP apps

- [ ] **Claude Desktop:** Connect in Routines → Connections, restart Claude Desktop, and ask for the cash forecast.
- [ ] **VS Code (Copilot, Agent mode):** the same, after starting the server from *MCP: List Servers*.
- [ ] A suggested transaction waits on the Routines screen. Every call appears in the audit log.
- [ ] Disconnect removes only the aaryaai-finance entry and leaves a backup of the settings file.

## 6. Privacy and security

- [ ] With no AI connected, the browser's network tab shows requests only to `127.0.0.1`, plus the exchange-rate and update checks listed in `PRIVACY.md`.
- [ ] Opening `http://localhost:8770/api/accounts` in a new tab without the page is refused.
- [ ] API keys don't appear in `config.yaml`, `secrets.json` or the JSON export.
