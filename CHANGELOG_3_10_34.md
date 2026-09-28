# Atlas Trading 3.10.34

## Security and custody hardening
- Replaced all hand-written TRON BIP32/Keccak/Base58 address derivation and decoding with bip-utils 2.12.2.
- New TRON wallets use the TRON-documented BIP44 path m/44'/195'/0'/0/<address-index>; legacy Atlas addresses retain their recorded legacy path.
- Production and staging fail closed on SQLite to preserve row-locking guarantees.
- Sensitive plaintext database values fail closed outside development.
- Withdrawal velocity uses SQL aggregation without a capped row set.
- Withdrawal approval digests use canonical fixed-point decimal strings.
- Financial money columns are stored as NUMERIC(38,18) instead of FLOAT.
- TRON receipt decoding now uses bip-utils Base58Check helpers.

## Verification
- Fresh non-billing regression suite: 225 passed, 3 skipped (2 optional bip-utils tests unavailable in audit runtime + billing environment dependency).
- Python compilation and AST parsing: PASS.
- No hand-written TRON BIP32/Keccak/Base58 helpers remain in application code.
