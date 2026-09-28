# Atlas Trading OS 3.9.1 — Production Corrections

## Critical corrections
- Added customer-scoped TradingAccount with funded USDT equity and per-customer risk state.
- Added customer_id/trading_account_id to trades and positions; removed global symbol-only position uniqueness.
- Customer Start Bot now requires a funded USDT wallet and uses only that customer account equity for risk sizing.
- Customer withdrawals cannot consume allocated trading capital or proceed while customer positions are open.
- Customer live execution is fail-closed until an isolated exchange account/subaccount mapping is configured.
- Fixed admin routes that referenced an undefined Authorization header variable.
- Backtest entries now fill only when the next bar actually reaches the entry; gap-through fills use the next bar open.
- Backtest now uses risk-per-trade sizing, leverage/notional caps, explicit fees/slippage and a real ATR trailing stop after +1R.
- Start Bot now validates data freshness/quality and current bid/ask spread before final safety review.
- Customer signal/client-order IDs are tenant-scoped to prevent cross-customer idempotency collisions.

## Verification
- 66 pytest tests passed, 1 skipped in the local environment.
- Python compilation passed for application and migration modules.
- Security scanner binaries were not available locally; CI should run Bandit, pip-audit and Ruff.
