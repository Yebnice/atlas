# Atlas 3.10.31 — Deriv Live Trading Audit

## Result
- Exact release tree compiled successfully.
- Non-billing regression suite: 215 passed, 1 skipped.
- The skipped billing test is due to the audit environment lacking the already-declared `aiosqlite` package.
- API routes: 115 total, 115 unique, 0 duplicate method/path pairs.
- Alembic migration head: 0026_customer_deriv_accounts.
- Python source/tests compilation: PASS.

## Deriv implementation
- Customer-scoped encrypted Deriv account credentials.
- Current Deriv OTP-authenticated WebSocket workflow.
- Customer account identity verification before credentials are stored.
- Real-account execution fail-closed behind platform `DERIV_LIVE_ENABLED`, customer live entitlement, customer-live enablement, verified customer Deriv account and platform kill switch.
- Active-symbol verification before proposal/buy.
- Proposal -> buy -> contract ID workflow.
- UNKNOWN state returned on ambiguous order outcome; no blind retry.
- Contract status/portfolio methods available for reconciliation.
- No platform Deriv token fallback for customer live execution.

## External fact check
Deriv's current documentation describes OAuth/PAT authentication, account OTP to an authenticated WebSocket, and live trading through proposal/buy/proposal_open_contract/portfolio/sell. The implementation follows this contract rather than treating Deriv as a generic spot broker.

## Remaining environment limitation
A complete billing import cannot run in this audit container because `aiosqlite` is not installed. This is an environment limitation; the dependency remains declared by the application.
