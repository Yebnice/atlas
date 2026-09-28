# Atlas 3.10.21 — Binance Customer Account Isolation

## Fact-checked against current Binance Developer Docs
- Binance Broker APIs support creation of broker sub-accounts and sub-account API keys.
- Spot trade permission can be enabled independently; margin/futures are separately controlled.
- Universal Transfer is a separate permission and remains disabled by Atlas.
- Binance currently documents KYC/eligibility restrictions for broker sub-accounts/API keys.

## Implemented
- Customer-to-Binance sub-account mapping schema.
- Least-privilege provisioning plan.
- Secret-manager reference instead of database storage for the API secret.
- Explicit rejection of universal-transfer permission.
- Admin provisioning-plan endpoint.
- Regression tests for permission boundaries and malformed Binance responses.

## Important
This release does not fabricate Binance eligibility or automatically create accounts without an authorized Binance Broker integration. It prepares the exact least-privilege provisioning contract and records customer isolation metadata.
