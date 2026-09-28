# Atlas 3.10.17 Review

## Scope
Institutional double-entry customer money ledger and trade settlement.

## Implemented
- Immutable ledger journal and journal-line tables.
- Balanced debit/credit validation.
- Journal idempotency.
- Deposit: TRON asset debit -> customer available liability credit.
- Trading reserve: available liability -> trading-reserved liability.
- Trading release: trading-reserved liability -> available liability.
- Realized trading P&L settlement.
- Trading fee attribution.
- Customer ledger statement API.
- Existing customer cash-only trading controls preserved.
- Existing live/funding configuration flags preserved unchanged.

## Verification
- Python compilation: PASS.
- Focused regression suite: 72 passed.
- Full pytest attempt: collection blocked by missing `aiosqlite` in the execution environment. This is not reported as a green full-suite result.
