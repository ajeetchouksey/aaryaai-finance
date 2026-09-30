# Planning tools

Five screens help you plan ahead. They all work from your own entries and rules, on your computer, with no AI.
They are arithmetic and education, not financial advice: the app never tells you to buy or sell a particular investment.

## Home

The first screen. It shows:

- a **warning** when a currency would drop below its floor, and the transfer that prevents it
- net worth, cash cushion, the next 90 days, and deadlines in the next 30 days
- net worth by currency
- what's coming up in the next 45 days
- the odds of reaching each goal
- the **routine inbox**: proposals waiting for your approval, tax opportunities, and what the routines last found

## Cash forecast

A 12-month view per currency, made from:

| Source | How sure | Where it comes from |
|---|---|---|
| Repeating entries | known | Money → repeating entries (salary, rent, savings plans) |
| Stages of a staged purchase | known / estimated | your tracker file: a stage with `due:` and `amount:` is *known*, otherwise estimated from the remaining price and the possession date |
| Planned items | known / planned / estimated | Cash forecast → ＋ Planned item (a bonus, a holiday, a school fee, a transfer) |
| Other spending | learned | the median of your last six months of entries that aren't repeating, so one big month doesn't skew it |

Only accounts marked **Available within a week** count.

**Floors.** Each currency has a floor: the least you want to keep. The default is about one month of that currency's usual outgoings. You can set your own below the charts.

**Funding plan.** When a month would go below a floor, the plan finds the currency with the most room above its own floor. It proposes a transfer around the 15th of the month before, big enough to reach the floor. The amount adds 1% for fees and rate moves and is rounded to a tidy number. **Add as a planned transfer** puts it into the forecast. The Forecast refresh routine also turns it into a proposal.

If a stage payment carries TDS (`tds_rate:` in the tracker), the plan shows the amount to deposit afterwards.

**Scenarios:**

- a salary arriving a month late
- the next stage coming a month early
- no estimated income (for example, no bonus)
- your base currency 7% weaker

**Watch this.** If a currency still dips below its floor and nothing can cover it, the forecast tests ways out and shows the lowest balance each one leaves:

- moving a flexible payment a month later
- pausing a savings transfer

### Tracker fields for the forecast

```yaml
tds_rate: 0.01            # optional: tax deducted at source on each stage (India, property ≥ ₹50 lakh)
stages:
  - {no: "04", name: 1st slab, due: 2027-02-10, amount: 703000}   # amount excluding GST/VAT
```

## Goals and odds

Each goal is replayed in 2,000 simulated markets, with good years and bad drawn at random. The spread depends on **how the money is invested**:

| Setting | Middle return | Spread (1 standard deviation) |
|---|---|---|
| cash | ~2% | 0.5% |
| balanced | ~4.5% | 8% |
| growth | ~6.5% | 15% |
| glide | growth until 10 years before the date, then moving towards cash | |

If you set an expected return on the goal, it is used as the middle. **85% likely** means 1,700 of the 2,000 replays reached the target in future money, after inflation. The random draws are seeded per goal, so the same inputs always give the same answer.

The screen also shows:

- the bad-case, middle and good-case outcome (10th, 50th and 90th percentile)
- the monthly saving that reaches 85%
- a slider to try other amounts
- where the monthly surplus goes
- the glide path
- what-ifs:
  - saving 10% more
  - six months without saving
  - markets 2% a year weaker
  - inflation 1.5% higher

## Diversify

Everything you own, in your base currency, split by:

- asset class
- country
- currency
- sector
- the biggest companies

Vehicles and debts are left out.

**Looking inside funds.** A built-in list covers common indexes, with approximate weights: MSCI World, FTSE All-World, S&P 500, Nasdaq 100, STOXX Europe 600, DAX, MSCI EM, Nifty 50, global bonds and gold. A holding is matched by its name or ticker, or by **Tracks** in Invest → edit. Add your own indexes in `<data folder>/lookthrough.json`, using the same shape as `aaryaai_finance/data/lookthrough.json`.

**Your rules**, changeable on the screen:

- largest single company
- months of cash cushion
- property at most
- one sector at most
- one country at most
- fund costs

**Target mix and rebalancing.** Set a target mix in %, and how much you invest each month. The cheapest way comes first: move spare cash above your cushion, then point new savings at what's short. Selling is shown last, with a rough tax figure from your country pack.

## Opportunities

Checks from your country packs (`opportunities:` in `pack.yaml`). Each card shows:

- why it applies
- the deadline
- an estimated effect
- the rule that produced it

| Rule | Country | What it needs |
|---|---|---|
| `in.ltcg_harvest` | India | Indian equity holdings with a **bought** date over 12 months ago, and the long-term gains you already realised this financial year |
| `in.short_to_long` | India | Holdings bought less than 12 months ago that turn long-term within 60 days |
| `de.fsa_rebalance` | Germany | Each bank's Freistellungsauftrag and investment income this year (Money → edit account) |
| `de.vorabpauschale` | Germany | Accumulating funds held in Germany. The base rate (Basiszins) is in the pack; check it each January |
| `de.loss_certificate` | Germany | Losses this year at a bank, plus gains taxed elsewhere |

## Tax return workspace

One workspace per country and tax year, defined by `tax_workspace:` in the pack. It has five steps:

1. **Collect.** It checks which documents are already filed, using your document rules and your documents folder.
2. **Numbers.** It reads numbers from documents where a rule extracts them. For example, gross pay from the Lohnsteuerbescheinigung.
3. **Interview.** Short questions grouped by topic. Your setup answers are filled in.
4. **Optimise.** It runs the pack's calculator and lists what makes a difference, with a rough effect.
5. **Filing sheet.** The values per form and field, to copy into ELSTER or the ITR yourself. Export as CSV or JSON for an adviser.

With an AI provider connected, **Ask me one more question** gets one tailored follow-up question. Everything else works without AI. Nothing is sent to a tax office.

## Routines

| Routine | How often | What it does |
|---|---|---|
| Forecast refresh | daily | rebuilds the forecast; each funding-plan transfer becomes a proposal |
| Deadline sweep | weekly | deadlines in the next 30 days; reminders for opportunities due within 60 days |
| Monthly review | monthly | last month's income, spending and savings rate; proposes raising a goal when the surplus allows |
| Tax-year prep | monthly | which documents for last year's return are still missing |
| Exchange rates | daily | refreshes ECB rates (skipped with manual rates) |

Routines run while the app is open: shortly after start and then every 15 minutes, for whatever is due. Start the app with `--no-routines` to switch them off. You can also switch each one off on the Routines screen.

**Proposals change nothing until you approve them.** Approving can:

- add a planned transfer
- set a goal's monthly saving
- add a deadline
- add a transaction suggested by an MCP app

Every approval, routine run, MCP call and data change is written to the **audit log**.

With an AI provider connected, the monthly review can add a short summary written by it. The numbers always come from the app.
