# Contributing

Thanks for helping! The most valuable contributions are **country packs** and **better rules** — they are plain YAML, no Python needed.

## How the app decides things

Everything that sorts documents or creates deadlines is a rule. Rules are read in this order, and the **first rule with a given `id` wins**:

1. **Your rules** — `<data folder>/rules/*.yaml`
2. **Trackers** — `<data folder>/trackers/*.yaml` (a tracker can bring its own document rules)
3. **Country packs** — `packs/<CODE>/pack.yaml`, only for the countries you switched on. A pack in `<data folder>/packs/<CODE>/` replaces the built-in one.

No AI is involved in any of this. If the AI assistant is connected, it is only asked about an uploaded document when no rule is at least 60% sure — and you still confirm the move.

## Document rules

```yaml
document_rules:
  - id: de_payslip                      # unique; reuse a pack id to replace that rule
    label: German payslip
    category: Salary & payslips
    confidence: 0.95                    # 0..1: how sure a match makes us
    match:                              # need at least one of these
      text_all: [bruttonetto]           # every word must appear
      text_any: [gehaltsabrechnung, verdienstabrechnung]   # at least one
      filename_any: [payslip, brutto-netto]                # hint in the file name
    extract:                            # optional named fields, regex with one capture group
      - {name: period, pattern: "abrechnungfür(\\w+)(20\\d\\d)", source: squashed, parse: de_month_year}
      - {name: invoice_no, pattern: "Invoice No\\.?\\s*(\\d+)"}
    route:
      folder: "{folder:DE}/Payslips/{first_year}"
      filename: "Payslip {period_year}-{period_month}{ext}"
```

**Matching** ignores case, spaces and punctuation: `text_any: [bruttonetto]` matches "Brutto / Netto". The score is `confidence` × how much matched; the best score wins and the others are shown as alternatives.

**Extract options:** `source: squashed` runs the regex on the text with all spaces removed. `parse` can be `date`, `amount` or `de_month_year` (gives `_year`, `_month`, `_month_name_de`).

**Pattern safety:** rules are data that anyone can share, so the app refuses patterns that could freeze it: longer than 300 characters, or a repeated group that itself contains a repeat or `|` — e.g. `(\d+)+` or `(a|b)*`. Write `\d+` or `[ab]*` instead. A refused rule is skipped and listed under **Settings → Your data**.

**Placeholders** in `folder` and `filename`:

| Placeholder | Value |
|---|---|
| `{folder:XX}` | the folder for country XX (Settings → Documents, else the pack's `default_folder`) |
| `{first_date}` `{first_month}` `{first_year}` | first date found in the document (`2026-03-15`, `2026-03`, `2026`) |
| `{stem}` `{ext}` `{original}` | original file name without extension, extension, full name |
| `{any_extracted_field}` | anything from `extract` |
| `{stage_folder}` | tracker rules only: folder of the matching stage |

Paths can't escape the documents folder, and existing files are never overwritten — a number is added instead.

## Deadline rules

```yaml
deadlines:
  - id: de_return_mandatory
    title: "German tax return {tax_year} — due (no advisor)"
    due: "{tax_year+1}-07-31"          # or "{year}-01-15", or "ongoing"
    if: de_mandatory_filing           # a setup question; "!id" means "answered no"
    severity: critical                # critical | high | normal
    detail: What to do, in plain words.
    source: § 149 AO
```

`{year}` is the calendar year; `{tax_year}` the year the filing is about. The app generates every occurrence in the next ~15 months; ticking one off is stored in the database under a stable key, so edits to wording don't lose your ticks.

## The data model (`model.json`)

The database is generated from `aaryaai_finance/model/core.json`. Each record type (*entity*) lists its fields:

| Type | Stored as | Notes |
|---|---|---|
| `text`, `date`, `datetime`, `currency`, `country` | text | dates `YYYY-MM-DD`; currency `EUR`; country `DE` |
| `int`, `bool` | integer | |
| `number`, `money` | real | |
| `enum` | text | needs `values`; `strict: false` allows other values |
| `ref` | integer | a link: `"to": "accounts"`, `"on_delete": "restrict" \| "cascade" \| "set_null"` |
| `json` | text | |

Field options: `label`, `help`, `required`, `default`, `unique`, `renamed_from` (list of old column names — data is carried over).

**Extending it** — a country pack adds a `model:` section to `pack.yaml`; a user writes `<data folder>/model.json` (or Settings → Custom fields):

```json
{
  "extends":  { "accounts": { "fields": { "iban_last4": { "type": "text", "label": "IBAN (last 4)" } } } },
  "entities": { "policies": { "label": "Insurance policy", "fields": {
      "name":      { "type": "text", "required": true },
      "premium":   { "type": "money" },
      "paid_from": { "type": "ref", "to": "accounts", "on_delete": "set_null" } } } }
}
```

Extra fields on built-in record types live in each row's `extra` JSON column, so adding one never changes the table. A pack's extra fields only show on records of that pack's country. New record types get their own table, list and forms.

**Changing core.json** (contributors): edit the model and bump `version`. On start-up the app compares the SQL generated from the model with the database; any table that differs is rebuilt inside one transaction after `finance.db` is backed up to `backups/`. Columns that disappear are kept inside `extra._legacy`, never dropped; use `renamed_from` for renames. Links that point nowhere are repaired without deleting data. Add a test with an old-schema database in `tests/test_model.py`.

## Adding a country

1. Copy `aaryaai_finance/packs/_template/` to `aaryaai_finance/packs/XX/` (ISO country code).
2. Fill in `code`, `name`, `flag`, `currency`, `default_folder`, then add questions, deadlines, document rules and a checklist.
3. For calculators, reuse an engine (`slabs` covers most progressive income taxes). The numbers belong in `params` — a new tax year should only need a YAML change. A new engine goes in `aaryaai_finance/tax/engines.py` with a test.
4. Cite a source for each deadline and rate (`source:`), and keep `detail` in plain English.
5. Need extra fields (like India's NRE/NRO account type)? Add a `model:` section — see above.
6. Run `pytest` — `tests/test_packs.py` checks every pack parses cleanly. Problems in a user's own pack show under Settings → Your data.

## Code

- Backend: FastAPI + SQLite in `aaryaai_finance/`. Frontend: plain JS in `aaryaai_finance/web/` — no build step, no CDN (everything vendored so the app runs offline).
- New AI providers go in `aaryaai_finance/ai/providers.py`; anything OpenAI-compatible can reuse `OpenAICompatProvider`.
- Keep it local: no telemetry, no calls home. Network access only for exchange rates, optional market prices, and the AI provider the user chose.
- **Security:** the server only answers requests with a loopback `Host`, a same-origin `Origin` and the per-start session token (see `create_app` in `server.py`). New endpoints get this for free — don't add routes outside `/static/` that skip it. `tests/test_security.py` covers it.
- **Never commit personal data.** `tests/test_packs.py` scans the repo for obvious personal identifiers.


## Planning sections in a pack (0.5)

Three optional sections make a country work with the planning screens. Built-in examples are in `packs/DE/pack.yaml` and `packs/IN/pack.yaml`.

```yaml
investing: {capital_gains_rate: 0.26375, equity_fund_exempt: 0.30, allowance_single: 1000}   # used for "tax if you sold"

opportunities:                      # checks on the Opportunities screen; engines live in aaryaai_finance/tax/opportunities.py
  - {id: de_fsa, engine: de_fsa, params: {allowance_single: 1000, rate: 0.26375}}

tax_workspace:                      # the Tax return screen
  title: "Germany {year}"
  year: calendar                    # or india_fy (April–March)
  documents:  [{id: lstb, label: Lohnsteuerbescheinigung, doc_types: [de_lohnsteuerbescheinigung], required: true}]
  questions:  [{id: gross, section: Income, label: "Gross pay", type: number, prefill: lstb.gross}]   # also: bool, text; from_answer; default
  derived:    [{id: homeoffice, label: Home-office allowance, value: "min(homeoffice_days, 210) * 6"}]
  estimate:   {calculator: refund, inputs: {gross: "gross", werbungskosten: "work_expenses"}}   # results available as est_<name>
  checks:     [{id: itemise, title: "Itemise work expenses", when: "work_expenses > 1230", detail: "…{work_expenses}…", effect: "(work_expenses - 1230) * est_marginal"}]
  sheet:      [{form: "Anlage N", field: Bruttoarbeitslohn, value: "gross"}]   # format: money (default), days, number, bool, percent
```

Formulas are evaluated by a small safe evaluator: numbers, names of answers and derived values, `+ - * /`, comparisons, `and`/`or`/`not`, `a if cond else b`, and `min`, `max`, `round`, `abs`. Unanswered names count as 0. Anything else (attributes, strings, other calls) is refused when the pack loads, and the workspace is skipped with an error in Settings.
