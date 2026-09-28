# Atlas 3.10.25 — Adaptive AI Bot Upgrade

- Added automatic LightGBM retraining for customer bot models when the configured model expires.
- Added champion/challenger promotion: a challenger must pass out-of-sample walk-forward gates before replacing the champion.
- Added explicit model integrity metadata and atomic promotion handling.
- Fixed AI walk-forward evaluation so predictions are never forward-filled across non-test/training windows.
- Customer bot now requires agreement between deterministic entry/exit logic and the learned model before execution.
- Customer bot UI now exposes learning state and OOS validation metrics.
- Added regression coverage for adaptive learning and WFO prediction-gap handling.
- External LLMs remain advisory/safety-veto only; they do not set price, size, stop, target, or execution authority.

- Added established-market liquidity gate for crypto: recent quote volume must meet the configured threshold before adaptive trading is eligible.
- Added Sortino, Calmar, profit factor and active-bar return diagnostics to AI walk-forward reports.
