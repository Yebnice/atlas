# AtlasRisk 3.10.45 — Full Hardening Audit

## Scope

This release incorporates the second-pass architectural review findings for deployment packaging, rate limiting, trusted proxy handling, withdrawal OTP/step-up binding, Supabase JWT/MFA verification, TRON custody separation, customer ownership integrity, ledger immutability, model artifact integrity, API/worker secret separation, endpoint authorization, and frontend API reachability.

## Verified in this source environment

- Backend routes inventoried: 129
- Customer mutation routes missing explicit auth boundary: 0
- Admin mutation routes missing explicit auth boundary: 0
- Frontend literal `/api/...` references checked: 62
- Unmatched frontend API references: 0
- Migration files: 40
- Unique migration revisions: 40
- Alembic head: `0040_database_integrity_and_ledger_immutability`
- Compile check: PASS (`app`, `alembic`, offline TRON xpub helper)
- Deployment shell syntax: PASS (`cloud-run-deploy.sh`, `cloud-run-worker-deploy.sh`, `gcp-bootstrap.sh`, `cloud-run-migration-job.sh`)
- Release security/static test set: 69 passed, 1 intentionally deselected because it requires the unavailable async SQLite driver in this container
- Dedicated 3.10.45 security inventory tests: 12 passed
- Ed25519 model signature create/verify/wrong-digest rejection: PASS
- Production config validation: API fails closed when required Supabase/funding secrets are absent; worker does not require API-only Supabase/funding secrets
- Runtime references to `USDT_TRON_MASTER_SEED_HEX`: 0 in `app/` and `deploy/`
- Legacy `ADMIN_TOKEN` production deployment reference: removed

## Important fixes in this release

### Deployment

- Production image now contains `alembic/` and `alembic.ini`.
- Production image excludes the test suite and uses `.dockerignore` to keep development material out of the runtime context.
- API and worker deployments are separated.
- API model bucket is read-only.
- Worker owns model promotion writes and receives the model signing private key.
- Supabase anon and funding webhook secrets are granted to the API service account only.
- Comma-containing `FORWARDED_ALLOW_IPS` and `ADMIN_SUPABASE_USER_IDS` values use an explicit gcloud env delimiter.

### Rate limiting / proxy trust

- Client-controlled `X-Device-ID` cannot create a fresh quota bucket.
- IP and authenticated identity limits are independent dimensions.
- OTP, password-reset and administrator login receive additional contact/identity rate limits.
- Forwarded client IPs are parsed only when the immediate peer is in a configured trusted proxy network.
- `FORWARDED_ALLOW_IPS=*` is rejected.

### Authentication / OTP

- JWT verification is centralized around the Supabase verifier.
- Unknown JWT `kid` causes one forced JWKS refresh before rejection.
- JWKS outages return controlled authentication-service errors rather than raw failures.
- Customer MFA state is implemented and only verified TOTP factors count toward AAL2.
- Withdrawal OTP is an actual Supabase OTP verification flow.
- Local step-up tokens are bound to the exact destination fingerprint and proposal digest and are single-use.
- Withdrawal OTP contact is bound to the authenticated, verified account contact.

### Custody

- API runtime no longer accepts or derives from a TRON master seed.
- Deposit address derivation is account-xpub based.
- The offline helper is the designated location for seed-to-xpub creation.
- External custody signer remains mandatory for production live payouts.

### Database / ledger

- Customer-owned trading/bot/executor relationships use composite customer ownership foreign keys.
- Deferred foreign keys introduced by hardening migrations are validated at migration time.
- PostgreSQL ledger constraints enforce one-sided positive debit/credit lines and bounded scale.
- Deferred PostgreSQL journal validation requires balanced currency-consistent journals with at least two lines.
- Ledger journals/lines/entries are immutable at the database layer.

### Model integrity

- Production model verification uses a public Ed25519 key.
- Model promotion requires the worker process and the private signing key.
- API has no model-staging write mount.
- Model artifacts are cryptographically signed instead of relying only on a co-located mutable hash.

### API / function integrity

- Customer strategy-builder mutation route now has an explicit authentication boundary.
- Frontend API references all resolve to a registered backend route after normalizing path parameters/query strings.
- Raw provider/execution exception messages are no longer exposed through HTTPException responses in the audited paths.
- Obvious dead no-op function fragments were removed.
- OANDA remains practice/demo-only; Deriv live execution remains fail-closed; Binance arbitrage remains disabled until its multi-leg path is fully integrated into the unified execution/ledger recovery model.

## Full test-suite limitation

`pytest` itself is installed in this review container, but the full suite cannot complete because the container is missing these runtime/dev dependencies:

- `aiosqlite`
- `asyncpg`
- `bandit`
- `pip-audit`
- `bip-utils`

The first full-suite collection failure is `ModuleNotFoundError: No module named 'aiosqlite'` while importing the SQLAlchemy async engine.

Therefore this release does **not** claim a full-suite pass from this container.

## Infrastructure gates still requiring real staging/production verification

1. Empty PostgreSQL database: `alembic upgrade head`, then migration startup and FK validation.
2. PostgreSQL concurrency: simultaneous withdrawals/orders and ledger invariant tests.
3. Redis multi-worker failover/fencing under process termination.
4. Cloud Run trusted-proxy behavior with the actual load balancer path.
5. Cloud Run IAM/Secret Manager access for API versus worker service accounts.
6. Cloud Storage model artifact read/write permissions and signature verification using real buckets.
7. Exchange sandbox drills: timeout, unknown order, duplicate submission, partial fill, stop rejection, cancel race, and worker crash recovery.
8. Bandit and pip-audit execution in CI/staging.
9. TRON xpub derivation helper execution on an offline environment with `bip-utils` installed.

## Release decision

No known source-level authorization, route-reachability, deployment-packaging, TRON-master-seed, or ledger-immutability blocker remains in the reviewed 3.10.45 source tree.

Live customer money must remain fail-closed until the real PostgreSQL, Redis, Cloud Run, Secret Manager, Cloud Storage, dependency-scan, and exchange-sandbox gates above have actually passed in CI/staging.

GitHub was not modified during this work.
