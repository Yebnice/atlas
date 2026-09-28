# Security model

The application is fail-closed for live trading. Paper trading is the default, and the runtime blocks live execution unless production flags, credentials, non-sandbox mode, authentication, single-worker execution, and explicit live confirmation are all satisfied.

Exchange API keys should be restricted to trading operations only, with withdrawals disabled and IP restrictions enabled where the venue supports them. Store secrets in a managed secret store in production; do not commit `.env` files.

The dashboard uses a session-only admin token in the browser. Put the application behind HTTPS and a trusted reverse proxy or identity layer before exposing it to the internet.

A CCXT network timeout on an order is treated as an UNKNOWN outcome rather than a failed order. Operators must reconcile the broker state before retrying.

## Application-layer database encryption (3.3.4)

The hardened backend encrypts sensitive database values with authenticated Fernet encryption before they are written to the database. The ORM transparently decrypts them when the application reads them. Covered fields include customer email/display name, TRON deposit address and token contract, withdrawal destination/tag/error/rejection/signature, funding metadata, and audit details.

Set `APP_ENCRYPTION_KEY` to a generated Fernet key and store it in Google Secret Manager (or an equivalent managed secret store). Do not commit the key or place it in Android code. Existing plaintext records must be converted with `scripts/encrypt_existing_data.py` after applying Alembic migration `0008_encrypt_sensitive_data`.

The encryption key is separate from the Supabase credentials, exchange keys, TRON master seed, and withdrawal release secrets. Rotate it using a controlled migration procedure; do not simply replace it on a running database because previously encrypted records would become unreadable.

## Customer OTP step-up

Customer withdrawals now require a fresh Supabase email/SMS OTP verification and a short-lived, signed backend step-up token. The token is bound to the authenticated Supabase user and expires according to `WITHDRAWAL_STEP_UP_MINUTES` (10 minutes by default). OTP values are never stored or logged by the application. OTP endpoints are rate-limited more aggressively than normal API routes.
