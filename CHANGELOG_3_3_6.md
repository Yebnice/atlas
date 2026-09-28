# 3.3.6 — Google Authenticator / TOTP MFA

- Added Supabase-native TOTP MFA for customer accounts.
- Google Authenticator-compatible enrollment with QR code and manual secret fallback.
- Customer login now requires AAL2 when TOTP is enrolled; new customer sessions are required to enroll TOTP before account access.
- Added `/api/auth/mfa/status`, `/api/auth/mfa/enroll`, `/api/auth/mfa/challenge`, and `/api/auth/mfa/verify` proxy endpoints.
- Withdrawals require both the existing fresh email/SMS withdrawal step-up token and an AAL2 TOTP-authenticated session.
- TOTP secrets are not stored in the Atlas trading database; Supabase Auth manages MFA factors.
- Existing dual-admin approval, separate payout release, reconciliation, encryption, and fail-closed controls remain in place.
- Full test suite: 40 passed, 1 skipped.

## Production notes

1. Enable App Authenticator/TOTP MFA in the Supabase Auth project settings.
2. Keep `CUSTOMER_TOTP_REQUIRED=true` in production.
3. Customers should register a backup authenticator factor/device where operationally appropriate; Supabase supports multiple TOTP factors.
4. If a customer loses all authenticator devices, use a documented identity-verification recovery process; do not bypass withdrawal approval controls.
