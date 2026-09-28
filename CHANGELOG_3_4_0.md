# Atlas Trading OS — 3.4.0

## Production-grade distributed security
- Added Redis-backed distributed API/auth/OTP rate limiting.
- Production startup fails closed when distributed rate limiting or backup/recovery configuration is missing.
- Added per-instance service heartbeats for operational visibility.
- Added production guard preventing multi-worker live trading until a distributed execution lock is configured.

## Withdrawal risk engine
- Added explainable transaction risk scoring using destination novelty, wallet-balance concentration, 24h/7d velocity, recent UNKNOWN payouts, amount proximity to configured maximum, and asset/network mismatch.
- BLOCK decisions prevent reservation/release for transactions above the configured risk threshold.
- REVIEW decisions remain auditable and require an explicit, separately authenticated admin risk review before payout release.
- Existing AAL2 + fresh withdrawal OTP + dual approval + separate payout release + whitelist + proposal digest remain intact.

## Monitoring and recovery
- Added runtime heartbeat records.
- Added recovery-due worker for UNKNOWN/SUBMITTED payouts. Recovery is status/reconciliation oriented and never performs a blind duplicate payout.
- Readiness now checks database, distributed rate limiter, and production recovery configuration.

## Staging/testnet gate
- Production defaults remain paper/sandbox and payout-live disabled.
- Real-money withdrawals are not enabled by this release. Testnet/staging acceptance must pass before any controlled production canary.


## 3.10.16 — Omnibus Treasury + Customer Ledger
- Central TRON treasury address configured for controlled sweeps; customer deposits remain attributed through unique virtual deposit addresses.
- Added authoritative customer USDT ledger with idempotent deposit credits.
- Added server-side cash-only trading reservation so a customer cannot spend another customer's funds or double-spend their own available balance.
- Shared TRC-20 address mode explicitly fails closed to manual review instead of guessing ownership from amount.
- Added ledger-backed dashboard balances and reconciliation hooks.
