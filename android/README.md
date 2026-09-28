# Atlas Trading Android app

This is the Android control-center client for Atlas Trading 3.10.45. It loads the authenticated FastAPI dashboard from Cloud Run over HTTPS. It does **not** run the trading engine locally, so trading/reconciliation can continue when the phone is offline.

## Configure
1. Deploy the backend to Cloud Run first.
2. Put the Cloud Run HTTPS URL in `app/src/main/res/values/strings.xml` as `backend_url`.
3. Build with Android Studio using JDK 17+ and Android SDK 35.
4. Install the generated APK on an Android 8.0+ device.

The app never contains broker keys, Supabase service-role keys, or database credentials. The dashboard uses its existing admin-token session mechanism.


Customer accounts are served from the backend root: sign-up, login, password reset, wallet view, funding history, and sign-out. The Android client does not hold broker credentials.
