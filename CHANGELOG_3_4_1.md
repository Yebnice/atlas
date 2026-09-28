# Atlas Trading OS — 3.4.1

## Admin Google Authenticator security
- Production admin API access now requires a Supabase Auth administrator session at AAL2 with verified TOTP (Google Authenticator compatible).
- Added an allow-list of Supabase Auth administrator user UUIDs via `ADMIN_SUPABASE_USER_IDS`.
- Added admin login, TOTP enrollment, challenge, status, and verification endpoints.
- Legacy `ADMIN_TOKEN` remains development-only compatibility and cannot bypass admin TOTP in production.
- Admin withdrawal approval, risk review, release, and reconciliation continue to require the existing separate approval/release controls.
- TOTP secrets remain managed by Supabase Auth rather than the trading database.
