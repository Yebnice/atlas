# AtlasRisk 3.10.38 — Live-Money Hardening

## P0/P1/P2 hardening implemented
- Fresh PostgreSQL migration repair: widened `alembic_version.version_num` and repaired historical `local_signature` creation.
- Added live-money hardening migration `0033_live_money_hardening`.
- Explicit withdrawal-destination verification; withdrawal endpoint never auto-verifies a destination.
- Destination verification OTP purpose and destination fingerprint binding.
- External structured security-audit copy for Cloud Logging.
- Versioned application encryption keys with rotation helper.
- Layered IP + authenticated-token + device rate-limit identity.
- PostgreSQL statement/lock/idle-in-transaction timeouts and disabled asyncpg statement cache for transaction-pooler compatibility.
- Incident first-class records.
- Model drift ALERT blocks live entries.
- Model artifact SHA-256 integrity gate for live execution.
- Champion backup and risk-officer rollback endpoint.
- Strategy OOS promotion gate strengthened with fold count, positive-fold ratio, worst-fold and last-fold requirements.
- Monte Carlo robustness and parameter-plateau research checks.
- Customer OANDA/Deriv credential capability status; Deriv requires explicit `trade` scope.
- Correlation/concentration group exposure cap.
- External custody signer/MPC boundary; direct CCXT withdrawals are disabled when the external signer is required.
- Meta-labeling gate added as a secondary take/skip layer.
- Public derivatives risk context (funding/open-interest when supported) blocks severe stress and reduces size under elevated stress.
- Multi-timeframe confirmation is required for crypto 5m/15m automated live entries.

## Verification status
- Source compilation: PASS.
- Focused regression/security/research tests: PASS.
- Full pytest: requires the verification environment because this sandbox still lacks `aiosqlite`.
- PostgreSQL migration/Alembic/Bandit/pip-audit: must be executed in Google Compute/CI.
- GitHub push: NOT DONE.
