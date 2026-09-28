# Android deployment

Architecture: Android control app -> Cloud Run FastAPI -> Supabase PostgreSQL / Cloud Storage -> broker APIs.

The Android app is intentionally a control client, not the always-on trading worker. Android may suspend or terminate background work; Cloud Run remains authoritative for execution and reconciliation.

Build:
1. Open the `android/` folder in Android Studio.
2. Set `backend_url` to the deployed Cloud Run HTTPS URL.
3. Build > Generate App Bundle / APK > APK.
4. Install the signed APK on the device.

Security:
- HTTPS only; cleartext traffic is disabled.
- No broker or database secrets are embedded.
- Keep `LIVE_TRADING_ENABLED=false` until paper/demo acceptance is complete.
