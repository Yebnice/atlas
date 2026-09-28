## 3.9.4 — competitive pricing + referral economics
- Reduced referral commission from 20% to 1%.
- Reduced referral discount from 20% to 5%.
- Launch pricing: Starter $7.99/mo, Pro $17.99/mo, Elite $39.99/mo; annual $79.90/$179.90/$399.90.

## 3.9.1 — Production Corrections
- Customer-scoped trading accounts, positions and trades.
- Correct entry-fill/risk-sized backtesting and real ATR trailing.
- Real market-data freshness/spread gates.
- Fixed undefined admin Authorization parameters.
- Customer live trading remains fail-closed until isolated exchange account mapping exists.

# 3.3.4 — Backend Security Hardening

See `CHANGELOG_3_3_4.md` for encryption, OTP step-up, rate limiting, and migration details.

# 3.2.1

- Fixed persistent Forex demo state.
- Added OANDA order lookup and reconciliation, including client-order recovery.
- Added withdrawal idempotency/provider-history recovery for ambiguous outcomes.
- Made strategy annualization timeframe-aware.
- Added API rate limiting and protected metrics by default.

## 3.2.0 — multi-strategy engine
- Added trend/momentum/breakout/regime-filtered mean-reversion ensemble.
- Added volatility-targeted leverage and ATR protective levels.
- Added `/api/strategy/signal` and `/api/strategy/backtest` endpoints.
- Added strategy regression tests.

# Changelog

## 3.0.1 — 2026-09-26

### Fixed
- Persisted withdrawal destination, destination tag, network, and provider fields when creating a withdrawal. This restores the proposal → approval → release data path.
- Required an executable destination and current whitelist validation before withdrawal approval.
- Regenerated and stored the canonical withdrawal proposal digest during approval and required it during release, preventing execution of an undigested proposal.
- Added all withdrawal runtime states used by the dashboard (`SUBMITTING`, `SUBMITTED`, `UNKNOWN`, `FAILED`) to the list API filter allow-list.
- Corrected `/api/state` drawdown and daily-loss signs so they report positive loss percentages consistently with the risk gate.
- Hardened model artifact filenames against path traversal and ambiguous user-controlled path components.
- Escaped untrusted withdrawal and trade values before dashboard HTML rendering to prevent stored XSS through the admin console.
- Ensured CCXT market-data clients are closed on both success and exception paths.
- Initialized the persisted daily risk date from UTC rather than the host's local calendar date.

### Security
- Dual-approval development mode no longer falls back to the master admin token when dual approval is enabled.
- Release execution now fails closed when the proposal digest is missing or does not match the stored withdrawal payload.

### Validation
- Python compileall: passed.
- Regression/static test suite: 17 passed, 1 skipped.
- The skipped API integration suite requires `aiosqlite`, which could not be installed because outbound package downloads are unavailable in the execution environment.

### Upgrade note
This is a backward-compatible patch release. The recommended deployment target is `3.0.1`, with PostgreSQL for production and the existing Alembic migration process for schema changes.


## 3.2.2 — Core execution hardening
- Fixed Forex demo execution to honor the persisted `AppState.forex_demo_enabled` state.
- Added OANDA pending-order listing and cancellation primitives for emergency-stop handling.
- Emergency stop now cancels pending OANDA orders when credentials are configured.
- Re-ran regression suite: 22 passed, 1 skipped.

## 3.8.0 — Multi-timeframe market structure
- Added 4H/1H regime, 15M setup, and 5M entry confirmation engine.
- Added ATR-based candidate entry, stop, and target levels.
- Added structure invalidation and higher-timeframe direction-flip exit rules.
- Preserved paper/shadow-only execution for new MTF signals.

## 3.9.0 — Start Bot safety gate + explicit entry/exit engine
- Added deterministic Start Bot gate: `TRADE` only when data, safety review, setup, spread, and risk/reward gates pass.
- Every trade plan requires an exact entry, stop-loss, and take-profit before order eligibility.
- Added trend + breakout trigger with ADX/RSI/momentum confirmation.
- Added structure/ATR protective stop and configurable R-multiple target.
- Added conservative bar-by-bar backtest with next-bar execution and stop-first handling when stop and target are both touched in one bar.
- AI remains advisory/safety-veto only; it cannot create price levels or authorize execution.

- Added `/api/strategy/backtest-gated` for the explicit entry/stop/target engine.

## 3.10.4
- Added derivatives stress research layer for funding/carry, OI, basis, liquidation pressure and order-flow stress.

## 3.10.17 — Institutional Double-Entry Customer Ledger
- Added immutable balanced ledger journals/lines, idempotent postings, customer P&L/fee settlement, and customer ledger statement API.
- Added migration 0019. Existing live/funding flags preserved unchanged.
