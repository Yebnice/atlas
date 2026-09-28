# Atlas Trading 3.10.23 — Serious End-to-End Security & Regression Audit

## Scope
Exact redesigned release ZIP extracted and audited. Review covered customer authentication, customer isolation, USDT/TRON wallet provisioning, funding webhook and ledger crediting, trading reserves/execution/reconciliation, withdrawal reservation/approval/reconciliation, Stripe webhook handling, customer webhooks, Binance customer-subaccount administration, Android configuration, migrations, frontend JavaScript, security headers, and route uniqueness.

## Results
- Python compilation: PASS
- API route scan: 106 routes / 106 unique method+path combinations
- Alembic migration graph: 22 revisions, single head `0022_binance_customer_subaccounts`, no missing parents
- Targeted security/ledger/execution suite: 56 passed
- Full non-billing test suite: **182 passed, 1 skipped**
- Frontend JavaScript syntax: PASS
- Customer DOM reference check: 77 IDs / 67 referenced IDs / 0 missing
- Android source/config inspection: PASS
- Production security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy present
- Secret literal scan: no obvious hard-coded live API/private secrets found

## Genuine issues found and fixed
### 1. Customer webhook credential leaked through URL query parameter
**Severity: High**
The endpoint accepted `?token=...`, which can expose credentials through reverse-proxy/access logs, browser history, monitoring, and copied URLs.

**Fix:** credential is now accepted only through `X-Atlas-Webhook-Token`. Documentation and regression tests were updated.

### 2. Binance customer-subaccount admin route bypassed centralized admin authentication
**Severity: Critical**
The route compared `Authorization: Bearer <admin_token>` directly against the static admin token instead of invoking the centralized Supabase/AAL2 admin gate. In a production configuration with a static admin token present, this could bypass the intended Supabase identity/allowlist/TOTP controls for that endpoint.

**Fix:** route now calls the centralized `auth(None, authorization)` gate. A regression test ensures the static-token comparison cannot return.

## Important audit findings that are NOT product failures
### Billing test environment limitation
`tests/test_billing.py` cannot be collected in the supplied audit runtime because `aiosqlite==0.21.0` is declared in `requirements.txt` but is not installed, and this environment has no package-index network access. This is an audit-environment dependency problem, not evidence that the application dependency declaration is wrong.

### Legacy static tests
Several historical tests expected old version numbers and old wallet-balance mutation strings. Those tests were stale relative to the hardened ledger architecture. They were updated to assert the current authoritative-ledger behavior and current release version.

## Residual production validation required
This audit cannot honestly certify live production behavior without a staging environment containing:
- PostgreSQL/Supabase with the current migrations applied
- Supabase JWT/JWKS and real AAL2/TOTP flows
- Redis/distributed rate limiter
- Stripe test-mode webhook delivery
- TRON test/mainnet transaction confirmation and sweep behavior
- Real payout-provider sandbox/reconciliation behavior
- Binance isolated customer-subaccount sandbox/permission validation
- A real Android SDK/Gradle build and device/emulator test

No claim of production certification is made without those tests.
