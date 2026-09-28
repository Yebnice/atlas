# Atlas 3.10.15 — Binance Arbitrage Reconciliation Hardened

- Added Binance authenticated user-data order-update normalization with support for current and legacy event shapes.
- Added signed user-data subscription request builder; signing remains injected and credentials stay server-side.
- Added partial-leg exposure calculation and bounded IOC neutralization helper.
- Added strict pre-order Binance price/quantity/notional filter validation.
- Corrected tick-size and step-size validation to use price % tickSize and quantity % stepSize.
- Added recovery tests for partial fills, terminal updates, malformed events, and signed subscription shape.
- Real-money arbitrage remains disabled by default and non-atomic; unresolved legs must be reconciled before continuing.
