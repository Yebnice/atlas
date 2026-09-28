# Atlas Trading 3.10.27

## Adaptive AI execution hardening

- Added owner-token Redis locks so an expired worker cannot delete a newer worker's lock.
- Added a final runtime gate immediately before autonomous execution to re-check bot status, customer status, subscription entitlements, account status, platform kill switch, and live-trading eligibility.
- Fixed autonomous bot persistence to record LIVE mode when live trading is actually enabled and authorized; paper mode remains the default otherwise.
- Added automatic stop after three consecutive controller failures.
- Serialized shared adaptive-model training/promotion per market artifact.
- Added persistent consecutive error tracking to adaptive bots.
- Kept adaptive learning, walk-forward validation, OOS promotion gates, liquidity/established-market controls, and customer-specific execution.

## Validation

The packaged release is required to pass the targeted adaptive-bot, security, strategy, and production regression suites. The audit environment may still skip/raise the billing suite when its declared `aiosqlite` dependency is unavailable.
