# AtlasRisk 3.10.40 — OANDA Demo-Only Boundary

## Fixed
- OANDA is now explicitly and permanently restricted to practice/demo, paper, shadow, learning and backtesting workflows.
- Customer OANDA connections reject `practice=false` and are stored as practice-only.
- Customer OANDA broker construction rejects non-practice accounts and always uses the practice endpoint.
- The dormant customer live OANDA branch in the main execution engine is removed; Forex/commodity execution can only enter the explicit demo path.
- Application startup fails closed if the legacy `FOREX_LIVE_ENABLED=true` setting is supplied.
- OANDA reconciliation runs only for the practice/demo workflow.
- OANDA market-data helpers refuse to operate when practice mode is disabled.
- Customer UI no longer exposes a live/practice toggle and labels OANDA as demo-only for learning/backtesting.
- Production environment template documents `FOREX_LIVE_ENABLED` as unsupported.

## Deliberate boundary
OANDA remains a learning/backtesting/demo tool and is not a customer live-money venue. Binance/other approved live venues remain separate.
