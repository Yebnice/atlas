# Atlas Trading OS 3.10.17 — Institutional Double-Entry Customer Ledger

## Purpose

Strengthen the customer-money accounting layer without changing existing live-trading or funding enablement flags.

## Changes

- Added immutable `ledger_journals` and `ledger_journal_lines` tables.
- Added balanced double-entry validation: total debits must equal total credits and each line is debit-or-credit only.
- Added idempotent journal posting.
- Customer deposits now create an on-chain asset debit and customer-liability credit.
- Trading reserves move liability from AVAILABLE to TRADING_RESERVED through a balanced journal.
- Trading releases reverse the reservation through a balanced journal.
- Added realized USDT trading P&L settlement journal.
- Added trading-fee attribution journal.
- Added customer ledger statement endpoint: `GET /api/customer/ledger`.
- Preserved the existing customer cash-only trading controls.
- Preserved all current live/funding enablement flags; no permission was disabled by this release.
- Added migration `0019_double_entry_ledger`.

## Verification

- Focused regression suite: 72 passed.
- Python compilation: passed.
- Full pytest: attempted; environment remains blocked if `aiosqlite` is unavailable during collection.
