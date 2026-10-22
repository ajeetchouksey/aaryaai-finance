# 0001 · Model v4: remember skipped occurrences of repeating entries

**Status:** accepted

## Context

Repeating entries (rent, salary, subscriptions) are written into `transactions` when they fall due. Generation is idempotent: `materialize_recurring` walks every occurrence from the start date and inserts it unless a row for that entry and date already exists (`INSERT OR IGNORE` on `tx_recur_once(recurring_id, date)`).

That made a removed occurrence come back on the next page load. Skipping one month's rent, or moving a salary from the 31st to the 1st, was impossible, and moving one created a duplicate.

## Decision

- Add `recurring.skip_dates` (`json`, a list of ISO dates) to `model/core.json` and bump the model to version 4.
- Deleting a generated transaction adds its date to `skip_dates`. Changing a generated transaction's date adds the old date.
- `materialize_recurring` skips those dates.

## Consequences

- The change only adds a field. On first start the `recurring` table is rebuilt with the new column after `finance.db` is backed up to `backups/`. No data changes, and older exports still import.
- Generation stays idempotent and simple; there is no need for a "generated until" cursor.
- To undo a skip, edit `skip_dates` (Settings → Export, or the database) or delete and re-add the repeating entry. A UI for this can come later if people need it.
