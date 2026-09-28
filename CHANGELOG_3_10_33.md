# Atlas Trading 3.10.33

- Replaced remaining customer-facing financial FLOAT columns with exact NUMERIC(38,18) storage through `FinancialNumeric`; authoritative ledger remains NUMERIC(38,6).
- Added PostgreSQL requirement for any live money-moving feature and fail-closed SQLite guard.
- Replaced hand-rolled TRON Keccak-256 with PyCryptodome Keccak-256 (`pycryptodomex==3.23.0`).
- New TRON customer wallets use standard BIP44 `m/44'/195'/0'/0/<address_index>`; existing legacy addresses are preserved and their legacy path is recorded for recovery.
- Withdrawal velocity checks now aggregate directly in SQL without a 100-row cap.
- Withdrawal approval digests now canonicalize amounts as fixed decimal strings.
- Production decryption now fails closed if a sensitive row is still plaintext.

- Replaced remaining hand-written TRON BIP32/Keccak/Base58 logic with bip-utils 2.12.2; new wallets use TRON standard BIP44 and existing legacy paths are preserved.
- Production and staging now fail closed on SQLite for non-development environments and on plaintext sensitive database rows.
