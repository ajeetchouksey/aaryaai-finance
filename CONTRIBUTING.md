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

## Adding a country

1. Copy `aaryaai_finance/packs/_template/` to `aaryaai_finance/packs/XX/` (ISO country code).
2. Fill in `code`, `name`, `flag`, `currency`, `default_folder`, then add questions, deadlines, document rules and a checklist.
3. For calculators, reuse an engine (`slabs` covers most progressive income taxes). The numbers belong in `params` — a new tax year should only need a YAML change. A new engine goes in `aaryaai_finance/tax/engines.py` with a test.
4. Cite a source for each deadline and rate (`source:`), and keep `detail` in plain English.
5. Run `pytest` — `tests/test_packs.py` checks every pack parses cleanly.

## Code

- Backend: FastAPI + SQLite in `aaryaai_finance/`. Frontend: plain JS in `aaryaai_finance/web/` — no build step, no CDN (everything vendored so the app runs offline).
- New AI providers go in `aaryaai_finance/ai/providers.py`; anything OpenAI-compatible can reuse `OpenAICompatProvider`.
- Keep it local: no telemetry, no calls home. Network access only for exchange rates, optional market prices, and the AI provider the user chose.
- **Never commit personal data.** `tests/test_packs.py` scans the repo for obvious personal identifiers.
