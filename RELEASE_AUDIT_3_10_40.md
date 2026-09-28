# AtlasRisk 3.10.40 Release Audit

## Scope
This release makes OANDA a hard **practice/demo-only** integration for learning, backtesting, paper trading and shadow workflows.

## Confirmed changes
- `OandaConfig(practice=False)` is rejected at adapter construction.
- Customer OANDA connection rejects `practice=false` and persists `practice=true`.
- Customer OANDA broker construction rejects non-practice accounts and always uses the practice API endpoint.
- `execute_signal()` cannot derive a live OANDA/Forex/commodity execution mode.
- Any non-demo Forex/commodity execution request is fail-closed.
- Production/staging startup rejects `FOREX_LIVE_ENABLED=true`.
- OANDA reconciliation is enabled only for configured practice/demo workflows.
- OANDA market-data helper is practice-only.
- Customer UI presents OANDA as Practice/Demo-only and removes the live/practice toggle.
- `.env.example` and `.env.production.example` document OANDA as demo/backtest/learning-only.

## Test evidence
Focused OANDA safety regression:

`28 passed in 0.16s`

Compilation:

`python -m compileall -q app tests` — passed.

The complete pytest suite is not claimed as passed in this sandbox because `aiosqlite` is unavailable during collection. The failure is environmental:

`ModuleNotFoundError: No module named 'aiosqlite'`

## Production interpretation
OANDA is not a live-money venue for AtlasRisk. No production workflow should depend on `FOREX_LIVE_ENABLED`; enabling it is rejected at startup.

The OANDA learning/backtesting connector can remain active independently of Binance/other approved live venues.
