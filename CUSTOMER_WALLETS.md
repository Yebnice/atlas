# Customer Accounts & Auto-Created Trading Wallets — 3.3.1

## Customer lifecycle

- Supabase Auth is the authoritative identity provider.
- Customers can create an account, sign in, request password reset, and sign out.
- Cloud Run validates Supabase JWTs before customer data access.
- Customer/admin permissions are separate.
- Customers cannot credit their own balance.

## Wallet behavior

A wallet is an **internal trading ledger wallet**, not a blockchain private-key wallet.

When a trusted funding provider sends a **CONFIRMED** funding webhook:

1. The backend verifies the HMAC signature.
2. The customer is resolved by Supabase Auth user ID.
3. A wallet for that customer/currency is created automatically if it does not exist.
4. The funding transaction is recorded with an idempotent provider reference.
5. The confirmed amount is credited to `available_balance`.
6. Replayed provider events do not credit the account twice.

Pending funding does not become spendable balance.

## Important custody boundary

This release does **not** generate or hold blockchain private keys and does not pretend that an internal ledger wallet is an on-chain deposit address. If customers will deposit cryptocurrency directly to blockchain addresses, integrate a regulated custody/deposit-address provider and make its confirmed webhooks the source of truth.

## Funding webhook

`POST /api/internal/funding/webhook`

Required header:

`X-Funding-Signature: sha256=<hex HMAC-SHA256>`

Signed body fields:

- `customer_auth_user_id`
- `provider`
- `provider_reference`
- `amount`
- `currency`
- `status` (`PENDING`, `CONFIRMED`, or `FAILED`)
- optional `metadata`

Set `FUNDING_WEBHOOK_SECRET` in Cloud Run Secret Manager. Never expose it to the Android app.
