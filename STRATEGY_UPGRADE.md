# Strategy Upgrade — 3.2.0

## Included
- Trend-following regime signal
- Time-series momentum signal
- Breakout confirmation
- Regime-filtered mean reversion
- Weighted ensemble signal
- Volatility-targeted position sizing
- Maximum leverage cap
- ATR-based stop-loss and take-profit levels
- One-bar signal/return lag in strategy backtests
- Transaction-cost modeling
- `/api/strategy/signal`
- `/api/strategy/backtest`
- Dashboard controls for strategy signals and backtests

## Research basis
The architecture emphasizes time-series momentum/trend following and explicit risk scaling. These are documented research areas across multiple asset classes, but historical evidence does not establish a universally best strategy or future profitability.

## Safe deployment
The application remains paper-first by default. Validate on the target exchange, asset, timeframe and execution costs before enabling live trading.
