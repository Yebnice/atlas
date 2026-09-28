# Real USDT funding — TRON / TRC-20

AtlasRisk derives new customer deposit addresses from a **public TRON account-level extended public key (xpub)**. The API runtime must never receive a TRON master seed or private derivation material.

The official Tether USDT contract on TRON is:

`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`

## Offline xpub generation

Run the supplied helper on a disconnected custody/admin machine:

```bash
python deploy/generate_tron_xpub.py --seed-out /secure/offline/atlas-tron-seed.hex
```

It generates a 32-byte random seed, derives the BIP44 TRON account at `m/44'/195'/0'`, and prints the account-level public extended key.

**Do not place the generated seed in Google Secret Manager for AtlasRisk API.** Store the seed/private recovery material in your separate offline custody procedure. Put only the printed `TRON_ACCOUNT_XPUB` value into the `atlas-usdt-tron-account-xpub` secret.

To derive from an already controlled offline seed instead:

```bash
python deploy/generate_tron_xpub.py --seed-hex '<64-hex-character-seed>'
```

## Before enabling mainnet deposits

1. Confirm `USDT_TRON_ACCOUNT_XPUB` validates as a public TRON account-level extended key.
2. Store the xpub in Google Secret Manager.
3. Store the TronGrid API key separately.
4. Run the migration job against PostgreSQL and validate all foreign keys before starting API/worker instances.
5. Run a controlled test deposit.
6. Verify the TRON transaction and confirm exactly one funding record and one ledger credit are created.
7. Confirm the deposit scanner advances independently for every customer wallet.

## Customer flow

The customer signs in, requests a deposit address, and receives a unique USDT TRC-20 address. The Android client cannot set or credit a balance.

The backend polls confirmed TRC-20 transfers from TronGrid, filters by the official USDT contract and destination address, and credits the customer ledger only once using an idempotent transaction reference.

## Custody boundary

The API and web tiers must never receive the TRON master seed/private keys. New deposit-address derivation is public-only. Legacy seed-derived wallets remain address-scannable from their stored public deposit address; any legacy private-key recovery is an offline custody operation.

This component does not automatically sweep or sign customer withdrawals. Sweeps/withdrawals use the separate custody-signing boundary and their approval/reconciliation controls.

## Network warning

Only send USDT over **TRON / TRC-20** to these deposit addresses. Do not send Ethereum, Solana, BNB Smart Chain or another network's USDT to a TRON deposit address.
