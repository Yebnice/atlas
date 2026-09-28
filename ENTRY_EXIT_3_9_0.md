# Atlas Trading OS 3.9.0 — Start Bot Entry/Exit Gate

## Customer behavior

When a customer clicks **Start Bot Analysis**:

1. Atlas retrieves the requested market history.
2. The deterministic strategy checks trend, momentum, ADX/RSI, and a prior-range breakout.
3. Atlas calculates an exact entry, structural/ATR stop-loss, and R-multiple take-profit.
4. The setup is rejected if the entry is not confirmed, risk is invalid, the reward/risk is below the configured minimum, data is unsafe, or the spread gate fails.
5. Gemini and Groq independently review the supplied plan as a **safety veto only**. They cannot alter the prices, side, size, or authorize execution.
6. If both AI reviews pass and all deterministic gates pass, Atlas sizes the position from account equity and configured risk-per-trade, then sends the plan to the existing execution/risk engine.
7. Paper trading remains the default. Real-money execution requires the existing platform-wide live-trading controls.

## Entry design

The default candidate uses a trend-following breakout structure:

- Direction: fast/slow EMA trend score.
- Confirmation: momentum + ADX + RSI.
- Trigger: close beyond the prior 20-bar high/low plus an ATR entry buffer.
- Execution: next bar, never the same bar that generated the signal.

## Exit design

Every trade must have both exits before execution:

- Stop: farther of the recent swing structure and the configured ATR risk distance.
- Target: 2.5R by default, with a minimum 2R reward/risk gate.
- Additional defense: validated opposite signal can close an open trade.
- Backtest handling: if stop and target are both touched in one bar, stop is assumed first to avoid optimistic intrabar assumptions.

## Research basis

This design uses established concepts rather than claiming a universal “best” indicator. Trend following/time-series momentum has extensive historical research; channel breakouts are a standard systematic trigger; professional risk-management guidance emphasizes defining the stop before sizing the position. Evidence on technical rules and ATR exits is conditional on market and frequency, so Atlas treats the strategy as a research candidate that must pass backtests and walk-forward validation rather than a guaranteed profitable system.

## Backtest API

`POST /api/strategy/backtest-gated`

Returns total return, maximum drawdown, trade count, hit rate, profit factor, trade Sharpe, and every trade's entry/stop/target/exit details.
