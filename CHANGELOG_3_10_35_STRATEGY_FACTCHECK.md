# Strategy Fact-Check Upgrade

- Replaced the hidden Strategy Lab keyword parser with the same real AI Strategy Intelligence pipeline used by the main strategy-builder endpoint.
- Added evidence classifications for trend, time-series momentum, breakout, mean reversion and ensemble components.
- Corrected opening-range construction to prevent pre-close look-ahead leakage and to respect London/New York daylight-saving time.
- Corrected higher-timeframe mapping to apply a conservative source-bar lag.
- Corrected RSI edge handling for zero-loss/zero-gain sequences.
- Normalized MACD histogram by ATR instead of an arbitrary price-scale multiplier.
- Removed fabricated unit-volume VWAP when volume is missing and removed VWAP from default ensemble alpha weighting.
- Fixed research turnover alignment with next-bar execution timing.
- Added per-strategy OOS results and OOS-aware paper-candidate gating.
- Renamed the misleading stop-loss guard metric to a generic loss-event guard.
- Made regime volatility annualization asset-class aware.
- Added `STRATEGY_FACT_CHECK_3_10_35.md` with established references and explicit limitations.
