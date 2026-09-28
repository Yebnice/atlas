# Live-trading gate

The application should not be treated as live-ready merely because the executable path exists. Before mainnet trading, verify all of the following in the target deployment:

- All automated tests pass.
- Sandbox/testnet execution and reconciliation have been exercised.
- PostgreSQL and backups are configured for production.
- Secrets are externalized; exchange keys cannot withdraw funds.
- TLS and an authenticated reverse proxy are in front of the dashboard/API.
- The live deployment has one execution worker/replica.
- Model walk-forward results are independently reviewed; no profitability is assumed.
- Exchange symbol precision/minimums are verified.
- Attached stop-loss support is verified for the exact symbol.
- Kill switch and broker cancellation are exercised.
- A timeout/UNKNOWN order scenario is exercised.
- Operator runbooks are tested.

Only after these checks should production flags be changed. Starting with sandbox/testnet is strongly recommended by CCXT's own manual, and sandbox keys are distinct from mainnet keys. citeturn754682search3

## 3.4 additional gate
Production payout execution remains disabled until Redis-backed distributed controls, backup/recovery validation, staging/testnet payout reconciliation, and the 3.4 acceptance checklist have passed.
