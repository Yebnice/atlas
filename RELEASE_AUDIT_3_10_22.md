# Atlas Trading 3.10.22 — Root-Bug Audit

## Second-pass findings and fixes

This release includes a second source-level audit focused on failure modes that can corrupt customer balances, duplicate customer resources, or leave execution state inconsistent.

### Confirmed root bugs fixed

1. **Customer profile creation race**
   - Two concurrent authenticated first requests could both observe no `CustomerProfile` and race on the unique `auth_user_id` constraint.
   - Fixed with a database savepoint and winner re-read.

2. **Customer ledger initialization race**
   - Two concurrent first-use requests could race on the unique customer/currency ledger row.
   - Fixed with a savepoint and winner re-read.

3. **Customer USDT/TRON wallet initialization race and network mismatch**
   - The product has one wallet row per customer/currency, but the TRON endpoint previously searched only for a TRON row. A USDT wallet created by another funding path could therefore cause a unique-constraint failure when the TRON endpoint tried to create a second USDT row.
   - Fixed by reusing the existing USDT wallet row and provisioning its TRON deposit metadata when appropriate; non-TRON conflicting network assignments fail closed.

4. **Unknown broker order released customer trading reserve**
   - A live broker timeout was correctly marked `UNKNOWN`, but the customer reserve was incorrectly released immediately.
   - If the exchange had actually accepted/filled the order, this could expose funds as available while the position existed.
   - Fixed: `UNKNOWN` now retains the reserve until reconciliation establishes the broker outcome.

5. **Partial-fill/cancel reserve leakage**
   - Terminal broker states did not consistently release the unused portion of the original order reserve, especially partial fills followed by cancellation.
   - Fixed with idempotent terminal reserve reconciliation based on requested reserve versus cumulative filled cost.

6. **Paper/customer trading fee failure when available cash was zero**
   - A fully reserved cash-only order could fill successfully but then fail fee settlement because the fee routine required all fees to come from `available` cash.
   - Fixed so a fee can consume available cash first and then the customer's trading reserve when necessary, with ledger balances updated consistently.

7. **Customer subscription initialization race**
   - Concurrent first requests could race on the unique internal subscription identifier.
   - Fixed with the same savepoint/re-read pattern.

## Validation

- Python compilation: passed (`python -m compileall -q app tests`)
- Targeted regression suite: **21 passed**
- Full pytest: collection remains blocked in this isolated audit runner because `aiosqlite` is not installed. The project requirements declare `aiosqlite==0.21.0`; outbound package installation was unavailable in this environment.
- Android CLI build: not run because the bundle has no Gradle wrapper and the audit environment has no `gradle` executable.

## Production validation still required

Before enabling real customer live trading or real payout execution, run the complete suite in CI/staging with declared dependencies and PostgreSQL, then perform end-to-end tests for:

- Supabase signup/login/MFA/logout and customer isolation
- customer-specific TRON USDT address provisioning
- confirmed deposit attribution and 19-block minimum confirmation
- ledger deposit/reserve/release/settlement invariants
- paper and live order partial-fill/cancel/timeout/reconciliation paths
- Binance customer-account isolation
- withdrawal dual approval, provider success/failure/unknown, and reconciliation
- Android build/install and authentication on a real device

The release should not be represented as production-accepted until those environment-dependent tests pass.
