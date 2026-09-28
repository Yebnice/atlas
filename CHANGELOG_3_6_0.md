# Atlas Trading OS 3.6.0 — Autonomous Daily Market Intelligence & Research

## Added
- Daily UTC research scheduler with distributed Redis lock to prevent duplicate Cloud Run runs.
- Yahoo Finance historical market-data adapter through `yfinance` for configured research symbols.
- Alpha Vantage news/sentiment intelligence adapter when `ALPHA_VANTAGE_API_KEY` is configured.
- Daily collection of market history and external intelligence before strategy evaluation.
- Full strategy backtest on every configured research symbol:
  - trend
  - momentum
  - breakout
  - mean reversion
  - ensemble
  - AI walk-forward model
- AI-assisted research brief combining backtest evidence, regime classification, news sentiment, and source-health warnings.
- Automatic paper/shadow candidate gate after each research run.
- New admin endpoint: `POST /api/research/run-daily` for an on-demand daily cycle.
- Daily research audit events.
- Explicit `real_money_execution=false` in the autonomous research path.

## Safety boundaries
- Research data is not treated as an exchange-authoritative execution feed.
- Yahoo Finance freshness/usage depends on its applicable data terms and entitlement.
- Real-money trading is not enabled by daily research and remains behind existing production gates.
- A failed market-intelligence source is surfaced as a research warning rather than silently treated as valid data.

## Configuration
- `DAILY_RESEARCH_ENABLED=true`
- `DAILY_RESEARCH_HOUR_UTC=1`
- `DAILY_RESEARCH_MINUTE_UTC=30`
- `RESEARCH_SYMBOLS=SPY,QQQ,BTC-USD,ETH-USD,EURUSD=X,GC=F,CL=F`
- `RESEARCH_YAHOO_PERIOD=3y`
- `ALPHA_VANTAGE_API_KEY=`
- `AI_RESEARCH_API_URL=` (reserved for an optional external AI research provider)
- `AI_RESEARCH_API_KEY=` (stored in Secret Manager in production)

## Verification
- 51 tests passed, 1 skipped.
