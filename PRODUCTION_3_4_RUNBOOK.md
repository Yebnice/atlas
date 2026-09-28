# 3.4 Production / Staging Runbook

## Required production services
- PostgreSQL
- Redis
- Cloud Run / equivalent HTTPS service
- Supabase Auth with TOTP MFA enabled
- Admin Google Authenticator/TOTP enabled; only allow-listed Supabase admin user UUIDs may access admin APIs
- Secret Manager/KMS for application, database, exchange, TRON, payout and signing secrets

## Required controls
1. `REDIS_URL` configured and reachable.
2. `BACKUP_RECOVERY_URL` configured to the organization's actual backup/restore procedure or service.
3. `APP_ENCRYPTION_KEY` and `SECRET_KEY` stored outside source control.
4. Exchange keys restricted to trading; withdrawals disabled at the venue where supported.
5. `PAYOUT_LIVE_ENABLED=false` until staging/testnet acceptance passes.
6. Customer TOTP enabled; withdrawal AAL2 + fresh step-up OTP remains required.
7. Withdrawal destination allowlisting enabled.
8. Two distinct withdrawal approvers configured.
9. Separate payout release operator configured.
10. Proposal digest and reconciliation enabled.

## Staging/testnet acceptance
- Run database migrations to head.
- Confirm `/readyz` is ready.
- Confirm Redis rate limiting across at least two service instances.
- Exercise login -> TOTP AAL2 -> withdrawal OTP -> withdrawal reservation.
- Verify low-risk withdrawal enters approval workflow.
- Verify new/high-concentration/velocity-risk withdrawals receive REVIEW/BLOCK decisions according to configured thresholds.
- Verify high-risk withdrawal cannot be released before explicit risk review.
- Verify dual approval requires different admin identities.
- Verify release requires the separate release operator and destination whitelist.
- Submit a testnet/sandbox payout and reconcile it to a terminal provider state.
- Simulate provider timeout/UNKNOWN and confirm no automatic duplicate payout occurs.
- Restore the database from backup and document measured RTO/RPO.
- Confirm alerts for database failure, Redis failure, stale heartbeat, UNKNOWN payouts, and reconciliation failures.

## Controlled production canary
Keep customer-facing real-money withdrawals disabled until staging acceptance is signed off. Enable only a tightly bounded canary amount/customer cohort, monitor reconciliation and alerts, and keep rollback artifacts available.

## Important
This runbook is an engineering release gate, not legal/compliance advice. Customer-money operations also require applicable KYC/AML, custody, licensing, consumer-protection, tax, and jurisdictional review before launch.
