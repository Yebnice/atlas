# 3.3.4 — Backend Security Hardening

- Added application-layer authenticated encryption for sensitive customer, wallet, withdrawal, funding metadata, and audit fields.
- Added `APP_ENCRYPTION_KEY` configuration with production fail-closed startup/ready checks.
- Added migration `0008_encrypt_sensitive_data` and legacy plaintext encryption script.
- Added Supabase email/SMS OTP send and verify endpoints.
- Added short-lived signed withdrawal step-up tokens bound to the authenticated customer.
- Customer withdrawal requests now require fresh OTP step-up verification.
- Added stricter rate limits for authentication and OTP endpoints.
- Kept private keys/master seed/release secrets server-side; Android receives no private key material.
- Preserved dual-admin approval and separate payout release controls.
