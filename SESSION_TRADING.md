# Session-aware market analysis — 3.7.0

Atlas now evaluates trend and market structure in the context of major market sessions.

## Analysis stack
- EMA fast/slow trend
- Momentum
- Donchian-style breakout
- Mean reversion with trend filter
- ADX trend-strength filter
- RSI
- MACD histogram
- Session VWAP
- ATR volatility/risk scaling
- London opening-range breakout
- New York opening-range breakout
- Session/regime classification
- Multi-factor ensemble

## Entry logic
An entry is only a candidate when the strategy signal, trend/structure context and risk conditions agree. Signals are formed on completed bars and backtests execute on the next bar to avoid look-ahead bias.

For session setups the engine records whether price has broken the first-hour range around the London or New York open. This is a confirmation feature, not an automatic order instruction.

## Exit logic
Candidate exits are based on:
- ATR protective stop
- ATR take-profit target
- Opposite validated signal
- Market-structure invalidation
- Existing portfolio/risk gates

## UK and US opens
Session calculations use `Europe/London` and `America/New_York` timezone rules rather than fixed UTC times. This correctly handles daylight-saving changes.

The London opening window is 08:00–10:00 local London time. The New York opening window is 09:30–11:30 local New York time for U.S. equity-market context. The NYSE core session itself is 09:30–16:00 ET; the official exchange calendar should remain authoritative for holidays and special sessions.

For FX/crypto, these are research windows, not claims that every asset has an exchange opening auction at those times.

## Safety
Session analysis does not guarantee an entry or profitable outcome. It feeds the existing backtest, paper/shadow and production risk gates. Real-money execution remains disabled unless all existing production gates pass.
