# Atlas 3.10.21 Review — Binance Customer Isolation

## Fact check
Verified against current Binance Developer documentation:
- Broker sub-accounts can be created through the Broker API.
- Sub-account API keys can be created with spot trade permission and separate margin/futures permissions.
- Universal Transfer is a separate permission and is deliberately disabled by Atlas.
- Binance documents KYC/eligibility restrictions for broker sub-accounts and API-key operations.
- API secrets are sensitive and must not be persisted in application DB; Atlas stores only a Secret Manager reference.

## Implemented
- `customer_binance_accounts` migration/model.
- Customer-to-subaccount uniqueness constraints.
- Least-privilege provisioning plan endpoint.
- Explicit rejection of universal-transfer permission.
- Secret Manager reference field; no secret-key database field.
- Binance provisioning response validation.
- Regression tests and stale version assertion update.
- Existing live/funding flags preserved unchanged.

## Verification
- Python compilation: PASS.
- Focused cross-system regression: 60 passed.
- Full pytest: collection blocked by missing `aiosqlite` in this execution environment; 1 skipped.
