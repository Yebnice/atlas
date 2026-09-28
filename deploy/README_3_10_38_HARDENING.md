# 3.10.38 Hardening Operations

## PostgreSQL foreign-key validation
After orphan cleanup:

```bash
DATABASE_URL='postgresql+asyncpg://...' python deploy/validate-postgres-constraints.py
```

## External security audit retention
Cloud Run/GCE stdout emits `jsonPayload.atlas_security_audit=true` records. Create a dedicated Cloud Logging bucket and sink with:

```bash
PROJECT_ID='your-project' ./deploy/gcp-security-audit-retention.sh
```

Review the bucket and IAM writer identity before the final irreversible lock:

```bash
gcloud logging buckets update atlas-security-audit --location=global --project=YOUR_PROJECT --locked
```

Cloud Logging supports user-defined buckets, custom retention, sinks and irreversible bucket locking. See the Google Cloud Logging bucket documentation.
