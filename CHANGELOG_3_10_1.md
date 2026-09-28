# Atlas Trading OS 3.10.1 — Adversarial Audit & Risk Hardening

- Fixed Strategy Builder model construction and list query dead ends.
- Fixed arbitrage paper evaluation so fee/slippage/safety costs are server-controlled.
- Added explicit base/quote assets and cycle continuity checks for triangular arbitrage.
- Added top-of-book depth checks and explainable no-trade reasons.
- Switched Atlas defaults to Binance Spot for the selected primary venue.
- Added research protections: drawdown halt, daily-loss halt, stop-loss clustering cooldown.
- Kept arbitrage and directional execution engines separate; arbitrage remains paper-only.
- Added regression tests for invalid prices, broken asset chains, insufficient depth and endpoint contracts.

## Validation
- 55 targeted/static/regression tests passed.
- Python compilation passed.
- 89 FastAPI routes inventoried.
- AST authorization audit: no missing admin authorization parameter on handlers calling `auth()`.
- Full pytest suite could not be collected in this environment because `aiosqlite` is unavailable and outbound package installation is blocked.


## 3.10.1 market intelligence hardening
- Added multi-source financial-news context using Federal Reserve and ECB public dissemination feeds plus optional Alpha Vantage news.
- Added 20-day return, moving-average trend, annualized volatility and peak drawdown snapshots for research symbols.
- Added headline risk themes for inflation, rates, geopolitical and financial-stress context.
- Added customer endpoint `/api/customer/market-intelligence`.
- Market intelligence is research-only and cannot authorize execution.
- Yahoo Finance remains reference market data; exchange feeds remain authoritative for orders.
- Added regression coverage for trend/risk scoring, source failure isolation and research-only guarantees.
