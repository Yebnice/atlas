# Atlas Trading 3.10.24 — Release Hardening Audit

## Scope
Fresh extraction of the redesigned 3.10.23 release, followed by source patching and regression testing for security, authentication, custody, accounting, billing, web UI, Android, deployment, and migration integrity.

## Fixed findings
- PyJWT upgraded to 2.15.0 with explicit RS256/ES256 allowlist and JWK algorithm matching.
- python-multipart upgraded to 0.0.32.
- cryptography upgraded to 50.0.1.
- Funding webhook now supports safe PENDING -> CONFIRMED / FAILED and FAILED -> CONFIRMED transitions while preserving idempotency.
- Stripe webhook events now have a durable unique inbox and subscription event ordering protection; event recording and business processing commit atomically.
- Binance customer API-key provisioning requires `enableWithdrawals=false` and `universalTransfer=false`.
- Customer Binance execution rejects mappings with withdrawals enabled.
- Broker cache identity uses SHA-256 of the full API key instead of an 8-character prefix.
- Cloud Run deployment pins Secret Manager versions and restricts ingress to internal + Cloud Load Balancing traffic.
- Android WebView restricts in-app navigation to the Atlas backend/trusted customer host and Stripe Checkout; other HTTPS URLs open externally.
- Customer API tokens moved from localStorage to sessionStorage.
- API-controlled customer UI values were converted away from direct dynamic innerHTML in the hardened areas.
- Added centralized `auth`, `admin_claims`, and `approver_auth` helpers that were referenced by protected routes but missing from 3.10.23.
- Restored missing runtime imports/model request definitions for GridBot, WebhookEndpoint/WebhookEvent, ExchangeConnector, BinanceSubAccountProvisionRequest, and dataclasses.asdict.

## Verification
- Python compilation: PASS
- All app AST parsing: PASS
- Customer JavaScript `node --check`: PASS
- API method/path combinations: 106 / 106 unique
- Alembic revisions: 23, single head `0023_security_billing_hardening`
- Targeted security/custody suite: 50 passed
- Full non-billing regression suite: 194 passed, 1 skipped
- Skipped test: `tests/test_api.py` because the audit environment cannot install `aiosqlite==0.21.0` without package-index network access; dependency remains declared in requirements.

## External validation used
Current PyPI/GitHub security information was checked for PyJWT, python-multipart, and cryptography, and current Binance API restrictions documentation was checked for `enableWithdrawals` and transfer permissions.

## Remaining staging requirements
Before live customer-funds production, run against real/staging Supabase/PostgreSQL, Redis, Stripe test webhooks, Binance customer/sub-account environment, TRON mainnet/sandbox procedures, Google Cloud Load Balancer + Cloud Armor, and a physical Android device/APK build.
