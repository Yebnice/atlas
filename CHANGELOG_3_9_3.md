# Atlas Trading OS 3.9.3

## Commercial system
- Added Free / Starter / Pro / Elite plan catalog.
- Added 7-day Pro trial for new customers.
- Added persistent subscription state and billing periods.
- Added optional Stripe Checkout and signed webhook processing.
- Added idempotent subscription revenue ledger.
- Added referral-code creation and one-time customer attribution.
- Added 20% referral-discount policy with optional Stripe coupon integration.
- Added 20% recurring referral commission ledger with a 45-day default eligibility delay.
- Added invoice-scoped commission idempotency so recurring payments are not collapsed into one commission.
- Added operating-cost ledger for AI/API, cloud, exchange, payment, data, blockchain, support and other categories.
- Added admin contribution-margin reporting: revenue minus operating costs minus referral commissions.
- Added customer billing/referral UI and admin commercial dashboard.

## Security / accounting boundaries
- Subscription revenue is never mixed with customer USDT or trading-account balances.
- Stripe credentials and price/coupon identifiers are configuration secrets and should be stored in Secret Manager in production.
- Stripe webhook requests require a signed timestamped payload and a 5-minute replay window.
- Referral commissions remain separate from customer trading funds.

## Validation
- Python AST/compile checks passed for modified application and migration files.
- Billing static regression checks passed.
- Full runtime pytest suite was not run in this build environment because `aiosqlite` is unavailable and outbound package installation is blocked.
- Production deployment must run the Alembic migration `0013_billing_referrals_margin` and the full CI/integration suite in an environment with project dependencies installed.
