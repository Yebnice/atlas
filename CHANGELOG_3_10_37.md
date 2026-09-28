# Atlas 3.10.37 — Platform Hardening

This release is a hardening upgrade built from the 3.10.36 codebase. It intentionally does not change the strategy direction or grant AI execution authority.

## Implemented

- TRON deposit cursor changed to BIGINT for millisecond block timestamps.
- TRON sweep `amount_raw` changed to BIGINT.
- TRON cursor overlap is now converted from configured seconds to milliseconds.
- TRON scans are isolated per wallet; one failing wallet cannot abort the rest of the cycle.
- Per-wallet Redis scan locks prevent duplicate workers from scanning the same wallet concurrently.
- API and background processing are separated by `PROCESS_ROLE=api|worker|job`.
- Added Cloud Run worker-pool deployment script and a dedicated migration job script.
- Added server-side administrator RBAC with READ_ONLY, OPERATIONS, RISK_OFFICER, TREASURY, COMPLIANCE and ADMINISTRATOR roles.
- Added maker/checker-oriented role enforcement to custody, withdrawal and live-risk operations.
- Added customer withdrawal destination fingerprints with cooling-off and explicit verification state. Rejected destinations never become trusted automatically.
- Added tamper-evident audit hash chaining with actor IDs.
- Added database checks for non-negative customer reserves and one-sided ledger journal lines.
- Added PostgreSQL foreign keys as NOT VALID constraints so legacy orphan cleanup can be performed before validation.
- Added a CCXT exchange adapter boundary with capability discovery and unified order-state lookup.
- Removed legacy `original_trader.py` from the production image/archive.
- Removed the stray `USDT_TRON.md.tmp` artifact.
- Updated security-sensitive dependency floors: pydantic-settings 2.14.2, pyarrow 23.0.1, pytest 9.0.3.

## Deliberate limitations

- No private signing key is added to Atlas. TRON sweep signing remains outside the application boundary.
- CCXT is an adapter layer, not a replacement for exchange-specific capabilities.
- Full PostgreSQL migration execution and the complete pytest suite require the declared dependency environment; the review environment lacked network access to install missing packages.
