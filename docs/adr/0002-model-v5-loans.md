# 0002 · Model v5: loans with a repayment schedule

**Status:** accepted

## Context

Debts could only be entered as an "item" with a balance typed by hand. That balance goes stale every month, the cash forecast doesn't know about the instalments, and nothing says when a loan ends or how much interest is left.

## Decision

- Add a `loans` record type to `model/core.json` and bump the model to version 5. A loan holds the amount borrowed, the interest rate (percent a year), the start date, the term or the monthly instalment, the account that pays it, and whether it is still running.
- `core/loans.py` works out the annuity schedule: the instalment (or the term), payments made, what is still owed, the payoff date and the interest left. The first instalment is due one month after the start.
- What is still owed counts as a debt in net worth. Instalments go into the cash forecast from the paying account, unless one of your repeating entries already pays the same amount from that account (within 2%), so nothing is counted twice.

## Consequences

- The change only adds a record type. On first start the `loans` table is created; no existing table is rebuilt and no data changes.
- Interest is charged monthly at a fixed rate. Variable rates, special repayments and offset accounts aren't modelled; you can edit the loan when your rate changes.
