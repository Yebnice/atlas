# Atlas Trading OS 3.9.5

## Product expansion
- Added customer-scoped Portfolio Command Center API.
- Added Smart Trade planning with multi-target take-profit, trailing-stop and breakeven parameters.
- Added customer-scoped DCA Bot configuration and start/stop lifecycle; paper-first by design.
- Added 15-minute market scanner using trend, momentum, breakout, RSI and volume features.
- Added customer alert records for price/trade/risk/system notifications.
- Added natural-language Strategy Builder drafts with mandatory backtest/walk-forward/paper validation gates.
- Added customer dashboard controls for portfolio, scanner, Smart Trade, DCA and strategy drafts.
- Added migration `0014_trading_product_features`.

## Safety
- New product features do not bypass existing Google Authenticator, customer account isolation, risk controls, exchange verification, withdrawal controls, or live-trading gates.
- Smart Trade and DCA creation default to PAPER mode.
- Strategy Builder outputs drafts only; it cannot authorize live execution.

## Commercial positioning
- Atlas pricing remains Free / $7.99 / $17.99 / $39.99 monthly.
- Referral commission remains 1%.
