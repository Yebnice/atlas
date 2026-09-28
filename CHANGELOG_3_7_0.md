# 3.7.0 — Session-aware trend and entry/exit research

- Added DST-aware London and New York session detection using IANA timezones.
- Added session opening windows and first-hour opening-range analysis.
- Expanded strategy analytics with ADX, RSI, MACD histogram and session VWAP.
- Added London/New York opening-range breakout context.
- Expanded live strategy signal output with explicit entry/exit rules and session context.
- Preserved next-bar execution assumptions in backtests to reduce look-ahead bias.
- Added tests for DST transitions, session windows and strategy entry/exit context.
- Real-money execution remains behind existing production risk controls.
