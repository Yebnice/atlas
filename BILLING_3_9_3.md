# Atlas Trading OS 3.9.3 — Commercial Layer

## Plans

These launch prices are intentionally below the current mainstream competitor entry/mid-tier prices while preserving paid features and metered AI usage.
- Free: $0 — market analysis, paper trading, basic backtesting.
- Starter: $7.99/month or $79.90/year.
- Pro: $17.99/month or $179.90/year; new customers receive a 7-day Pro trial.
- Elite: $39.99/month or $399.90/year.

Prices are product defaults and can be changed in `PLAN_DEFINITIONS` before launch.

## Subscriptions
- Persistent subscription ledger with provider and period state.
- Optional Stripe Checkout using price IDs stored in Secret Manager/environment.
- Signed Stripe webhook verification.
- Paid invoice revenue is recorded idempotently.
- Customer trading balances are never used as subscription revenue.

## Referrals
- Each customer can generate a unique Atlas referral code.
- A referred customer can claim one referral attribution.
- Default referred-customer discount policy: 5% (configure the corresponding Stripe promotion/coupon before enabling it in production).
- Default referral commission: 1% of paid subscription revenue.
- Commission eligibility is delayed 45 days by default to reduce refund/fraud exposure.
- Each paid invoice has its own commission record, preventing duplicate or missing recurring commissions.
- Minimum payout policy: $25.

## Margin
The admin margin endpoint calculates:
`contribution profit = subscription revenue - operating costs - referral commissions`

`contribution margin % = contribution profit / subscription revenue * 100`

Cost categories can include AI/API, exchange, cloud, data, blockchain, payment processing, support, fraud/chargebacks, and other operating expenses. Customer trading capital is not part of this margin calculation.

## Production requirements
1. Run Alembic migration `0013_billing_referrals_margin`.
2. Configure Stripe secret, webhook secret, and price IDs in Secret Manager.
3. Configure a Stripe referral promotion/coupon if the 20% referred-customer discount is offered.
4. Point Stripe webhook delivery to `/api/billing/stripe/webhook`.
5. Record actual operating costs through `/api/admin/billing/cost` or an internal cost-ingestion job.
6. Reconcile Stripe invoices against the revenue ledger.
7. Do not treat subscription revenue as customer wallet or trading-account funds.
