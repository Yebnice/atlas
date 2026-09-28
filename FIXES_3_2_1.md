# AI Trading App 3.2.1 — Root Bug Fixes

## Fixed
1. Forex demo enablement is now persisted in `app_state` instead of returning a transient success.
2. UNKNOWN withdrawals can attempt provider-history recovery using the deterministic idempotency key.
3. OANDA orders can be fetched by provider order ID or recovered by client order ID; background reconciliation now includes OANDA when configured.
4. Strategy annualization and volatility targeting now use actual bar spacing instead of a hard-coded 252*24 assumption.
5. API request-rate limits were added, with tighter limits for training/backtest endpoints.
6. Metrics can require admin authentication (enabled by default).
7. Added Alembic migration `0004_safety_hardening` for persistent Forex demo state.

## Validation
- pytest: 22 passed, 1 skipped
- Python AST syntax validation: all project Python files passed

## Operational note
The rate limiter is per process. For multiple workers/replicas, enforce the same or stricter limits at an API gateway/WAF/ingress layer.


### 3.2.2 follow-up fixes
- Corrected a remaining Forex demo endpoint state check that could reject a successfully enabled demo session.
- Added OANDA emergency-stop order cancellation support.
