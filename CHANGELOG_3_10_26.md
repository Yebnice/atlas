# Atlas Trading 3.10.26

## Adaptive AI Controller Upgrade
- Added persistent customer Adaptive AI Bot controller with scheduled autonomous cycles.
- Added distributed per-bot execution locks for multi-instance safety.
- Adaptive learning now runs independently of trade opportunities.
- Added established/liquid crypto universe allowlist: BTC, ETH, BNB, SOL, XRP, ADA, DOGE USDT markets.
- Expanded ML features with trend slope, ATR regime, drawdown, volume trend and range regime.
- Model freshness now requires the current feature schema.
- Added persistent bot status, last decision, model version, scheduling and error telemetry to the customer UI.
- Added migration 0024_adaptive_bot_controller.
- Live execution remains fail-closed; bots start in PAPER mode.

## Validation
- Full non-billing regression: 199 passed, 1 skipped.
- Python AST/compile: PASS.
- Fresh package verification required before production deployment.
