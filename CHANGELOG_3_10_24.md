# Atlas Trading 3.10.24 — Security & Financial Integrity Hardening

- Upgraded PyJWT, python-multipart and cryptography to current security-fixed releases.
- Enforced explicit JWT algorithm allowlisting and JWK algorithm matching.
- Fixed funding webhook state transitions, including PENDING → CONFIRMED/FAILED.
- Added durable Stripe event idempotency and stale-event protection.
- Required Binance customer API keys to have withdrawals disabled and universal transfer disabled.
- Hardened customer broker cache identity using a full credential hash.
- Pinned Cloud Run Secret Manager versions and restricted ingress to load-balancer traffic.
- Restricted Android WebView navigation to trusted Atlas/Stripe hosts.
- Added centralized admin bearer authentication/AAL2 helpers and restored missing approver authentication helpers used by protected admin routes.
- Restored missing runtime imports/request model definitions for GridBot, customer webhooks/connectors, and Binance sub-account planning.
- Customer bearer tokens are now session-scoped rather than persistent localStorage tokens.
- Added regression checks for the newly discovered runtime-name and authorization defects.
