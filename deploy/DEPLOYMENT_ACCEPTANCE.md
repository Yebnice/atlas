# Deployment acceptance checklist

- [ ] Supabase project created and encrypted PostgreSQL connection configured.
- [ ] Google Cloud APIs enabled and Artifact Registry repository created.
- [ ] Dedicated Cloud Run service account created.
- [ ] Dedicated model bucket created with least-privilege object access.
- [ ] Secret Manager contains database/admin secrets.
- [ ] Cloud Run deployed with `min=1`, `max=1`, `concurrency=1`.
- [ ] Alembic migrations completed successfully.
- [ ] Cloud Run `/healthz` returns 200.
- [ ] Cloud Run `/readyz` returns 200 and reports database readiness.
- [ ] Android app loads the Cloud Run dashboard over HTTPS.
- [ ] Android dashboard API calls reach Cloud Run and authenticate with the admin token.
- [ ] Admin token is required outside development.
- [ ] Paper trading remains enabled.
- [ ] Live trading remains disabled.
- [ ] OANDA demo/sandbox connectivity tested.
- [ ] Crypto sandbox/testnet connectivity tested if enabled.
- [ ] Model train → signal flow survives a Cloud Run revision restart.
- [ ] Reconciliation tested after simulated timeout/restart.
- [ ] Kill switch tested.
- [ ] Backup and restore procedure tested.
- [ ] Logs/alerts configured.
- [ ] Only after all checks pass: evaluate a restricted live pilot.

## 3.10.24 security deployment requirements
- Cloud Run must be reachable through an external HTTPS Load Balancer with Cloud Armor; deployment uses `internal-and-cloud-load-balancing` ingress and does not rely on direct public `run.app` ingress.
- Set the five `SECRET_*_VERSION` deployment variables to explicit Secret Manager versions before running `cloud-run-deploy.sh`.
- Customer Binance API keys must report withdrawals disabled and universal transfer disabled before an account is marked VERIFIED.
- Apply Alembic migration `0023_security_billing_hardening` before starting the application.
