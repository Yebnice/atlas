# 3.3.2 — Real USDT TRC-20 funding

- Added real USDT funding on TRON (TRC-20).
- Added deterministic per-customer TRON deposit-address provisioning from a platform master seed.
- Added confirmed on-chain TRC-20 transfer polling through TronGrid.
- Added official Tether TRON USDT contract pinning.
- Added idempotent on-chain funding credits.
- Added customer-facing USDT deposit address UI and explicit network warning.
- Added Google Secret Manager deployment wiring for the TRON master seed and TronGrid API key.
- Added migration `0006_real_usdt_tron_deposits`.
- Added deterministic TRON address and Keccak-256 regression tests.
- Live trading and crypto withdrawals remain fail-closed by default.
