# Atlas Trading OS 3.5.0 — Strategy Research Brain

- Added unified research engine that backtests trend, momentum, breakout, mean-reversion, ensemble, and AI walk-forward strategies.
- Uses lagged execution, transaction costs, slippage, volatility scaling, and drawdown metrics.
- Added research ordering for historical evidence; this is not a guarantee of future performance.
- Added regime snapshot and AI-assisted research review that explains historical results, current regime, volatility, drawdown warnings, and limitations.
- Added objective promotion gate for paper/shadow testing.
- Added live market signals for validated paper candidates with `PAPER_SHADOW_ONLY` mode; no real-money order is created by this feature.
- Added admin dashboard controls for the full workflow.
- Real-money execution remains behind the existing production risk and deployment gates.
