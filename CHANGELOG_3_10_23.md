# Atlas Trading 3.10.23 — Security Hardening

- Customer webhook credentials are accepted only through `X-Atlas-Webhook-Token`; secrets are no longer accepted in URL query parameters.
- Binance customer-subaccount admin planning now uses the centralized Supabase/AAL2 admin authentication gate.
- Updated security regression tests and release metadata.
- No customer ledger, withdrawal, wallet, or trading API contract was intentionally changed by these fixes.
