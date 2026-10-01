# Setup guide

This guide takes you from nothing to a working app with your own numbers, in about an hour. You can stop after any part; each one makes the app more useful on its own.

| Part | What you get | Time |
|---|---|---|
| [1. Install](#1-install) | the app running on your computer | 10 min |
| [2. First start](#2-first-start-four-questions) | your countries, currencies and folders | 5 min |
| [3. Accounts and regular money](#3-accounts-and-regular-money) | net worth, budget and a cash forecast | 15 min |
| [4. Investments, assets and debts](#4-investments-assets-and-debts) | the full picture, and Diversify | 10 min |
| [5. Goals and plans](#5-goals-and-plans) | goal odds and the funding plan | 10 min |
| [6. Documents and tax](#6-documents-and-tax) | filed documents and your tax-return workspace | 10 min |
| [7. Optional extras](#7-optional-extras) | AI, MCP apps, your own rules | as you like |

Everything stays on your computer. Nothing you enter is uploaded. See [Privacy](../PRIVACY.md).

---

## 1. Install

You need Windows 10/11, macOS or Linux, and **Python 3.10 or newer**.

### Windows

1. Install Python from <https://www.python.org/downloads/>. On the first installer screen, tick **Add python.exe to PATH**.
2. Download the latest version from the [website](../#download) (the `.zip`) and unzip it, for example to `Documents\aaryaai-finance`.
3. Double-click **`start.bat`**. The first start takes a minute or two while it sets itself up in a private `.venv` folder.
4. Your browser opens at `http://127.0.0.1:8770`. Keep the black window open while you use the app; closing it stops the app.

To start it next time, double-click `start.bat` again. A desktop shortcut to `start.bat` makes this one click.

### macOS and Linux

```bash
python3 -m pip install --user pipx && python3 -m pipx ensurepath   # once, if you don't have pipx
pipx install git+https://github.com/ajeetchouksey/aaryaai-finance
aaryaai-finance
```

Your browser opens at `http://127.0.0.1:8770`. Press Ctrl+C in the terminal to stop.

### Start options

| Option | What it does |
|---|---|
| `--data-dir PATH` | use this data folder instead of the one you chose in setup |
| `--port 8771` | another port, if 8770 is taken |
| `--no-browser` | don't open a browser tab |
| `--no-routines` | don't run scheduled routines in the background |

With `start.bat`, put the options after it in a shortcut, e.g. `start.bat --port 8771`.

---

## 2. First start: four questions

The first time the app opens, it asks four things. You can change all of them later in **Settings**.

**1. Where your data lives.** One folder holds everything: settings, database, your own rules and trackers. The default is `Documents\aaryaai-finance-data`. A folder inside OneDrive or iCloud Drive gives you automatic backups. Pick a private location, because this folder contains your finances.

**2. Your countries.**
- Tick each country where you have money or pay tax. Germany and India are built in.
- Choose the **base currency**: totals are shown in it. Usually it's the currency you're paid in.
- Answer the yes/no questions. They decide which deadlines apply to you, for example whether you must file a German return every year, or whether you're a non-resident (NRI) for Indian tax.

**3. Your documents folder.** Point it at the folder where you already keep payslips, statements and tax papers. The app files new documents into the same structure, and never deletes or moves anything without your click. Folder names per country can be set too, for example `Finance/germany` and `Finance/india`.

**4. AI (optional).** Choose **No AI** for now if you like; every screen works without it. See [part 7](#ai-assistant).

When you finish, the **Home** screen opens. It will be mostly empty until you add accounts.

---

## 3. Accounts and regular money

This part gives you net worth, the budget and the cash forecast.

### Exchange rates

Go to **Settings → Currencies**. Rates come from the European Central Bank and refresh daily. You can type your own rates instead, for example the rate your bank actually gives you.

### Add your accounts

Go to **Money** and use **＋ Add … account** under each country (for example *＋ Add Germany account*). For each account:

- **Name and bank**, for example "Girokonto" at "Sample Bank".
- **Currency and country.**
- **Balance on the start date.** Today's balance and today's date is the easiest start.
- **Cash I can reach within a week.** Tick it for current and savings accounts, and leave it off for fixed deposits you can't touch. **Only ticked accounts count in the cash forecast and the cash cushion.**
- **Country fields** appear automatically:
  - Germany: your **Freistellungsauftrag** at that bank, **investment income this year** and **losses this year**. These feed Opportunities.
  - India: **NRE / NRO / resident**.

Add your credit card and loans as accounts too if you want them in net worth.

### Add what repeats

Still in **Money**, use **Add an entry**:

- **Salary** as income, repeating **monthly**, on the day it usually arrives.
- **Rent**, insurance, subscriptions and savings plans as expenses, with how often they repeat.
- **Transfers** between your own accounts, such as the monthly move to savings or a remittance from EUR to INR. If the currencies differ, enter the amount received, or leave it empty to use today's rate.

Repeating entries are written into your history automatically each time they're due, never twice. You don't need to log everyday spending. If you do, the forecast learns your usual "other spending" from it.

### Check the forecast

Open **Cash forecast**. You should see a bar chart per currency for the next 12 months.

- Set a **floor** for each currency: the least you want to keep, for example 3 months of essentials. The default is about one month of that currency's usual outgoings.
- If a month would drop below a floor, the **funding plan** shows the transfer to make and when.

---

## 4. Investments, assets and debts

### Investments

Go to **Invest → ＋ Add holding**. For each fund or share, enter:

- **Units and average buy price.**
- A **Yahoo ticker**, such as `VWCE.DE`, `IWDA.AS` or `^NSEI`, so **↻ Refresh prices** can update it. Or type the current price yourself.
- **First bought on.** This matters for India: holdings turn long-term after 12 months, which Opportunities uses.
- **Tracks**: which index it follows, for example MSCI World or Nifty 50. Leave it empty and the app guesses from the name. This lets **Diversify** look inside the fund.
- **Income**: accumulating or distributing. In Germany, accumulating funds trigger the January Vorabpauschale.

### Other assets and debts

Go to **Net worth → ＋ Add account or debt** for property, pensions, provident funds, gold, a car, a home loan and so on. For property under construction, enter what you've paid so far at cost. Then add a staged-purchase tracker (below) to plan what's left.

### A purchase paid in stages (optional)

A flat under construction, or a car paid in instalments, is described in a small text file in the `trackers` folder of your data folder. Copy [`examples/trackers/example-flat.yaml`](https://github.com/ajeetchouksey/aaryaai-finance/blob/main/examples/trackers/example-flat.yaml) and edit it:

```yaml
id: my-flat
type: staged_purchase
name: Riverside Towers B-1203
country: IN
currency: INR
price: 9500000                 # total price excluding GST
tax_rate_on_payments: 0.05     # GST on each stage
tds_rate: 0.01                 # optional: 1% TDS you deduct as buyer (India, property ≥ ₹50 lakh)
possession_date: 2028-06-30
stages:
  - {no: "01", name: Booking, paid: 2025-01}
  - {no: "04", name: 1st slab, due: 2027-02-10, amount: 703000}   # from the demand letter
  - {no: "05", name: 5th slab}                                     # no date yet: estimated
payments:
  - {date: 2025-01-15, cumulative: 950000, label: Booking}
```

Restart the app. The stages appear on Home and Net worth, and in the cash forecast. A stage with a `due` date and `amount` counts as known; one without counts as estimated.

### Diversify

Open **Diversify** and set your **target mix** in %, for example shares 50, bonds 15, cash 15. Enter how much you invest each month. Check **Your rules**, such as the largest single company, months of cash cushion and the property maximum. Change them to suit you.

---

## 5. Goals and plans

### Goals

Go to **Goals → ＋ New goal**. For each goal, enter:

- **Cost in today's money** and **needed by**. Inflation is added for you.
- **Already set aside** and **saving per month.**
- **How the money is invested**:
  - *cash* for money you need soon
  - *balanced* for a mix
  - *growth* for 10+ years
  - *glide* to start in shares and move to safer money as the date nears

The odds at the top show how likely each goal is, and the monthly saving that would make it 85% likely. Use the slider to try amounts, and **Use this amount** to save one.

Good first goals:
- an emergency fund of 6 months of spending
- a child's education
- the remaining instalments of a property
- a retirement top-up

### Budget

Go to **Budget → ＋ Add spending**. Enter your usual monthly spending per category. It sets the "spend" used for your cash cushion and the monthly surplus on Goals. Without a budget, the app uses the last three months from Money.

### Planned items

Go to **Cash forecast → ＋ Planned item** for one-off things you know or expect: a bonus, a holiday, school fees, a tax payment, a planned transfer. Mark how sure each one is: known, planned or estimated. The scenario **No estimated income** shows the forecast without them.

---

## 6. Documents and tax

### Documents

Open **Documents** and drop in a few files: payslips, bank statements, tax certificates, receipts. For each file, the app:

- reads the text
- recognises the document type from your country packs' rules
- suggests a folder and a file name

Check the suggestion and click to file it.

**Check my folders** reads your existing documents folder and lists files that look misplaced. Nothing moves until you click.

### Deadlines

**Deadlines** lists the tax and compliance dates that follow from your setup answers. Tick them off as you go, or add your own. The calculators give quick estimates, such as a German refund or India's old vs new regime.

### Tax return

Open **Tax return**, then choose a country and year. It works in five steps:

1. **Collect.** It shows which documents for that year are found or missing. File missing ones on the Documents tab.
2. **Numbers.** It fills in what it can read from documents, such as gross pay from the Lohnsteuerbescheinigung.
3. **Interview.** Answer the questions; amber boxes are unanswered. **Save answers** often.
4. **Optimise.** It shows what makes a difference, with a rough effect, and the estimated refund or payment.
5. **Filing sheet.** Copy each value into ELSTER (Germany) or ITR-2 (India) yourself, or **Export for your adviser**.

It is an estimate to prepare with, not a filing. Confirm with a tax adviser.

### Opportunities

Open **Opportunities**. Most checks run on what you've already entered. Two need input from you:

- **India:** enter the long-term gains you've already realised this financial year, at the bottom of the screen.
- **Germany:** for each bank, enter the Freistellungsauftrag, investment income and losses this year (Money → edit account).

---

## 7. Optional extras

### Routines

Routines run on their own while the app is open:

- forecast refresh
- deadline sweep
- monthly review
- tax-year prep
- exchange rates

They only **suggest**. Proposals appear on Home and on **Routines**, and nothing changes until you click **Approve**. Every action is in the **Audit log**. Switch individual routines off on the Routines screen, or start with `--no-routines`.

### AI assistant

Go to **Settings → AI assistant** and pick one:

| Provider | Good for | Data leaves your computer? |
|---|---|---|
| **Ollama** | privacy, no cost after setup | no |
| **Claude** (Anthropic API) | best answers; pay per use | yes, to Anthropic |
| **Azure OpenAI** | if your organisation uses Azure | yes, to your Azure tenant |
| **GitHub Models** | free within limits | yes, to GitHub |

Step-by-step instructions: [Connecting AI](ai-providers.md). With AI connected you get:

- the **Ask AI** chat
- a follow-up question in the tax workspace
- an optional summary in the monthly review

### Claude Desktop, VS Code and other MCP apps

Go to **Routines → Connections → Connect an MCP app**, copy the snippet, and paste it into Claude Desktop's or VS Code's MCP settings. Your assistant can then read your forecast, goals and tax status, and suggest entries for you to approve. Details: [MCP](mcp.md).

### Your own rules, fields and countries

- **Rules:** teach the app new document types and deadlines in YAML. *Insert an example* shows the format.
- **Settings → Custom fields & record types:** add fields to accounts, or new record types like insurance policies.
- **A new country:** copy the template pack. See [Rules, packs & data model](../CONTRIBUTING.md).

---

## Keeping it running

**Backups.** Copy the data folder, or use **Settings → Your data → Export everything (JSON)**. The app also backs up the database into `backups/` before every upgrade or import.

**Updates.** A notice appears when a new version is out.
- `start.bat`: download the new zip and unzip it over the old folder. Your data folder is separate and stays untouched.
- pipx: run `pipx upgrade aaryaai-finance` (or `pipx install --force git+https://github.com/ajeetchouksey/aaryaai-finance`).

**Moving to a new computer.** Install the app, copy the data folder across, and choose it at the first question. API keys live in the system keychain, so enter them again in Settings.

**Screen sharing.** Press **Alt+H** to hide every amount.

**Removing it.** Delete the app folder (or `pipx uninstall aaryaai-finance`) and, if you want, the data folder.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| `'python' is not recognized` or start.bat says Python is needed | Reinstall Python and tick **Add python.exe to PATH**, then open a new window. |
| "Address already in use" / the page doesn't load | Another copy is running, or the port is taken. Close the other window, or start with `--port 8771`. |
| "Session expired — reload the page" | The app was restarted. Reload the browser tab. |
| Exchange rates missing for a currency | ECB doesn't cover it (e.g. AED). Add a manual rate in Settings → Currencies. |
| A screen is empty | Most screens need accounts first (part 3). The cash forecast only counts accounts ticked "Cash I can reach within a week". |
| A document is filed in the wrong place | Use **Rules → Test a document** to see which rule matched. Add your own rule with the same `id` to replace it. |
| `model.json` or a rules file has an error | The app keeps running without it and shows the problem in Settings. Fix the file and save. |
| Prices don't refresh | Install the market extra (`start.bat` does this) and check the ticker on finance.yahoo.com. You can always type prices by hand. |

Still stuck? Open an issue on [GitHub](https://github.com/ajeetchouksey/aaryaai-finance/issues). Never paste real account numbers or personal documents there.
