# 3.3.1 — Customer Accounts & Auto-Created Trading Wallets

- Added Supabase Auth customer signup/login/password-reset/logout flow.
- Added JWT validation against Supabase Auth JWKS.
- Added customer profiles with account status.
- Added customer-specific internal trading wallets by currency.
- Added signed funding webhook with idempotent provider references.
- Confirmed funding automatically creates/activates the customer's wallet and credits available balance.
- Pending/failed funding is not spendable.
- Added customer wallet and funding-history endpoints.
- Android portal now opens customer account experience at `/`.
- Admin console remains available at `/admin`.
- Added Alembic migration `0005_customers_wallets_funding`.
- Live trading remains fail-closed/paper-first.
