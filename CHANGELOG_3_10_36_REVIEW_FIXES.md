# 3.10.36 review fixes

1. **Ledger idempotency** - `reserve_trading` keyed on a wall-clock timestamp (retries double-reserved cash); now takes a stable `reference_id`. `release_trading` now checks the journal before mutating balances, like every sibling function.
2. **HALTED lockout** - a customer halted by the drawdown/daily-loss breaker could not close the position that tripped it. Capped reduce-only exits are now allowed through both `execute_signal`'s early gate and `risk_gate`; all other HALTED orders remain blocked. Dead `existing` position query removed.
3. **Daily research observability** - production without `REDIS_URL` now logs `RESEARCH_DAILY_MISCONFIGURED` (was `RESEARCH_DAILY_COMPLETED`); benign concurrent skips log `RESEARCH_DAILY_SKIPPED`.
4. **OANDA history window** - candle count now uses bars-per-day for the bot's timeframe instead of a hard-coded hourly `days * 24`, so sub-hourly forex/commodity bots can reach `min_train` and train.
5. **Startup guard** - production now fails fast if `ADAPTIVE_BOT_CONTROLLER_ENABLED` (default true) and `REDIS_URL` is unset, instead of every bot silently sticking at `MODEL_LOCK_BUSY`.

**Deploy note:** production must set `REDIS_URL`, or set `ADAPTIVE_BOT_CONTROLLER_ENABLED=false`.
Not changed: arbitrage partial-leg recovery (`neutralize_partial_leg`) is still not wired to any endpoint.
