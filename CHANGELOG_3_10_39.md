# AtlasRisk 3.10.39 — Production Safety & Verification

## Fixed
- Production encryption readiness now validates the versioned keyring/active key instead of requiring only the legacy APP_ENCRYPTION_KEY variable.
- `/readyz` now checks migration head, encryption, payout boundary, custody signer configuration, and external audit configuration.
- Direct CCXT withdrawals are disabled outside development. Production payout release requires the external signer boundary or a configured bank provider.
- Meta-labeling now predicts the current unlabeled bar using models trained only on completed labels; it no longer scores a stale horizon-shifted training row as the live probability.
- Meta-label walk-forward threshold is configurable instead of hard-coded.
- OOS strategy promotion now supports Sharpe, drawdown, and minimum-trade gates.
- Monte Carlo robustness uses a block bootstrap to preserve short-range return dependence.
- Strategy candidate validation uses the strengthened OOS gates.
- Production template defaults customer withdrawals to disabled until an external signer is configured.

## Verification boundary
The release remains honest about external infrastructure requirements. Fresh PostgreSQL, migration/constraint validation, concurrent ledger tests, exchange/withdrawal failure drills, Cloud Logging retention configuration, and package-security scans still require a real runtime.
