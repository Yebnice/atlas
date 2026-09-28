#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_REGION:?Set GCP_REGION}"
: "${CLOUD_RUN_MIGRATION_JOB:?Set CLOUD_RUN_MIGRATION_JOB}"
: "${IMAGE:?Set IMAGE}"
: "${DATABASE_SECRET_REF:?Set DATABASE_SECRET_REF, e.g. atlas-database-url:3}"

gcloud config set project "$GCP_PROJECT_ID"
gcloud run jobs deploy "$CLOUD_RUN_MIGRATION_JOB" \
  --region "$GCP_REGION" \
  --image "$IMAGE" \
  --command alembic \
  --args upgrade,head \
  --set-env-vars "ENVIRONMENT=production" \
  --set-secrets "DATABASE_URL=$DATABASE_SECRET_REF"

gcloud run jobs execute "$CLOUD_RUN_MIGRATION_JOB" --region "$GCP_REGION" --wait
