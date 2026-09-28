# Atlas Trading 3.10.35 deployment

Recommended production topology:

Android app -> Google Cloud Run -> Supabase PostgreSQL
                               -> Google Cloud Storage (models)
                               -> OANDA / crypto broker APIs

Vercel is intentionally not used.

## Order of operations
1. Create Supabase project and PostgreSQL connection string.
2. Run `alembic upgrade head` from a trusted deployment environment.
3. Create Google Cloud project, Artifact Registry, service account, Secret Manager secrets, and model bucket.
4. Run `deploy/cloud-run-deploy.sh`.
5. Verify `/healthz` and `/readyz`.
6. Configure Android `backend_url` with the Cloud Run HTTPS URL.
7. Build/install the Android APK.
8. Run the acceptance tests in `DEPLOYMENT_ACCEPTANCE.md`.
9. Keep paper/sandbox mode until broker demo tests and failure/recovery tests pass.

## Customer accounts and funding

Release 3.3.1 adds Supabase Auth customer accounts and an internal trading wallet ledger. Apply Alembic migration `0005_customers_wallets_funding`. Configure `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `FUNDING_WEBHOOK_SECRET` through Secret Manager. Use the signed funding webhook for confirmed deposits; never let the Android client directly credit a wallet.
