# Atlas Trading 3.10.35 — Hardening & Release Fixes

## Security
- Disabled the legacy `ADMIN_TOKEN` authentication path outside development; production/staging privileged APIs require the allow-listed Supabase admin identity and configured AAL2/TOTP.
- Production security headers now derive directly from the configured environment rather than an unset application-state flag.
- Production/staging startup now fails closed when the database is not at the Alembic migration head.

## Deployment
- Cloud Run deployment now requires and injects Supabase admin configuration, Redis, application encryption key, and backup/recovery configuration.
- GCP bootstrap provisions the additional production secrets.

## UI
- Implemented referral-code creation and claiming controls.
- Replaced non-functional market tabs with working Watchlist/Bullish/Bearish filters.
- Made global market search functional.
- Renamed the rule-based natural-language strategy parser to Strategy Draft Builder and clarified its capabilities.

## Release consistency
- Application, Python package, Android client, and current release documentation are aligned to 3.10.35.
- Added focused regression coverage for the fixes above.

## Validation
- Python compilation: PASS
- Customer JavaScript syntax: PASS
- Focused hardening/regression tests: PASS
- Broader runnable static suite: 83 passed, 2 skipped; the review container could not execute tests requiring `aiosqlite` because that dependency is unavailable in the offline review environment. `requirements.txt` already pins `aiosqlite==0.21.0`.

## Strategy Intelligence upgrade
- Replaced the deterministic keyword strategy parser with a real LLM-backed Strategy Intelligence pipeline.
- Gemini is the primary strategy-generation provider; Groq is an optional fallback.
- Added strict Pydantic schema validation, supported-timeframe/asset validation, and platform risk caps.
- AI output is permanently marked `PAPER_SHADOW_ONLY` and has no execution authority.
- Provider/model metadata and fallback errors are returned for auditability.
- Added regression tests covering provider requirements, schema validation, risk capping, and removal of the keyword parser.

## Strategy fact-check correction
- The earlier Strategy Lab keyword implementation has now been removed as part of the 3.10.35 hardening follow-up. Strategy Lab candidates use the real AI Strategy Intelligence pipeline and bind to an Atlas-supported strategy family before validation.


### Risk management & trading discipline hardening
- Added deterministic per-trade stop-distance risk budgeting.
- Added configurable daily entry cap and entry cooldown for new exposure.
- Applied the same entry-frequency and risk-budget discipline to execution-aware backtests.
- Preserved daily-loss, peak-drawdown, leverage, portfolio-exposure, stale-signal, spread and protective-stop gates.
- Added `RISK_MANAGEMENT_DISCIPLINE_3_10_35.md` with established risk-management methodology references and explicit limitations.
