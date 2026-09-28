# Forex Broker Integration — OANDA v20

## Why OANDA is the first adapter

The original application already had an FX research/data path but no real FX execution adapter. This release adds OANDA v20 as the first concrete Forex broker integration instead of using CCXT as if it were a universal FX broker API.

## Official API environments

Practice: `https://api-fxpractice.oanda.com`

Production: `https://api-fxtrade.oanda.com`

The practice environment must be used for demo validation.

## Credentials

Create a v20-enabled OANDA account and personal API token through OANDA's account management process. Never put the token in source control.

## Supported application flow

1. Fetch account state.
2. Fetch current bid/ask.
3. Fetch completed candles.
4. Generate the AI signal.
5. Apply portfolio/risk gates.
6. Normalize Forex units.
7. Submit a market order with deterministic client ID.
8. Attach stop-loss/take-profit on fill when configured.
9. Record OANDA transaction IDs.
10. Reconcile account/position state.

## Failure semantics

A transport timeout is `UNKNOWN`, not `FAILED`. No automatic duplicate retry is performed until the broker state is reconciled.

## Live gate

The code defaults to practice mode and keeps `FOREX_LIVE_ENABLED=false`. Live mode requires an explicit production configuration and should be promoted only after practice acceptance testing.

## Practice/demo hardening (3.10.10)

- `/api/forex/demo/preflight` verifies practice account access, instrument tradeability, executable bid/ask, and quote freshness.
- `/api/forex/demo/price` is a read-only practice quote endpoint.
- Demo order quantity is capped by `OANDA_DEMO_MAX_UNITS` (default 100,000).
- Demo quote freshness is capped by `OANDA_DEMO_MAX_QUOTE_AGE_SECONDS` (default 3s).
- The demo path remains explicitly practice-only and never selects the production OANDA host.
- OANDA personal tokens remain server-side; do not place them in Android/browser code.
