# AtlasRisk 3.10.39 — Production Safety Verification

## What changed
- Versioned application encryption keyring is the authoritative readiness/startup check; legacy `APP_ENCRYPTION_KEY` remains only as v1 migration compatibility.
- `/readyz` verifies database connectivity, Alembic head, encryption, Redis/distributed limiters, recovery configuration, custody signer configuration, payout boundary, and external audit configuration.
- Direct CCXT withdrawals are blocked outside development. Live payout must use the external signer custody boundary or a deliberately configured bank adapter.
- Meta-labeling predicts the current unlabeled market bar from models trained only on completed labels.
- OOS promotion can require Sharpe, drawdown, and minimum trade-count stability in addition to fold-return rules.
- Monte Carlo robustness uses a block bootstrap.
- External security audit records are recursively redacted for likely secrets/tokens before they are copied to stdout/Cloud Logging.

## PostgreSQL runtime verification
Use a disposable/staging PostgreSQL 17 database. PostgreSQL 17 documents row locking and transaction-level advisory locks for application-defined synchronization. The Atlas financial paths use transactional row locking and idempotency; the packaged concurrency drill verifies that PostgreSQL serializes concurrent updates correctly.

```bash
DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/DB' \
  ./deploy/verify-live-money-runtime.sh
```

The script performs: Alembic upgrade/check, NOT VALID FK validation, concurrent PostgreSQL increment testing, focused live-money regression tests, Bandit when installed, and pip-audit when installed. It never enables live trading.

## Cloud Logging security audit
First create the dedicated sink/bucket:

```bash
PROJECT_ID='your-project' ./deploy/gcp-security-audit-retention.sh
```

Then verify it:

```bash
PROJECT_ID='your-project' ./deploy/verify-cloud-audit.sh
```

Google Cloud documents user-defined log buckets, custom retention and irreversible bucket locking. Review IAM and retention before using `--locked`.

## Production preconditions that remain intentionally operational
- Configure and test the external custody signer/MPC service.
- Configure `EXTERNAL_CUSTODY_SIGNER_REQUIRED=true` and only then enable live payouts.
- Use exchange API credentials without withdrawal permission wherever the exchange supports granular permissions.
- Run the worker-crash/restart drill and exchange unknown-result reconciliation drill against a real sandbox/test account.
- Run a fresh PostgreSQL migration and orphan/constraint validation on the actual deployment database.
