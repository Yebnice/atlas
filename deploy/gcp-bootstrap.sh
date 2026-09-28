#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_REGION:?Set GCP_REGION, e.g. europe-west1}"
: "${AR_REPOSITORY:?Set AR_REPOSITORY, e.g. trading}"
: "${MODEL_BUCKET:?Set MODEL_BUCKET, globally unique, e.g. ${GCP_PROJECT_ID}-atlas-models}"
: "${MODEL_STAGING_BUCKET:?Set MODEL_STAGING_BUCKET, globally unique, e.g. ${GCP_PROJECT_ID}-atlas-model-staging}"
: "${SERVICE_ACCOUNT:?Set SERVICE_ACCOUNT, e.g. atlas-trading-api}"
: "${WORKER_SERVICE_ACCOUNT:?Set WORKER_SERVICE_ACCOUNT, e.g. atlas-trading-worker}"
: "${DATABASE_URL:?Set DATABASE_URL to your Supabase PostgreSQL URL}"
: "${USDT_TRON_ACCOUNT_XPUB:?Set USDT_TRON_ACCOUNT_XPUB to the public TRON account-level extended public key}"
: "${TRONGRID_API_KEY:?Set TRONGRID_API_KEY}"
: "${APP_ENCRYPTION_KEY:?Set APP_ENCRYPTION_KEY to a Fernet key}"
: "${REDIS_URL:?Set REDIS_URL}"
: "${SUPABASE_URL:?Set SUPABASE_URL}"
: "${SUPABASE_ANON_KEY:?Set SUPABASE_ANON_KEY}"
: "${FUNDING_WEBHOOK_SECRET:?Set FUNDING_WEBHOOK_SECRET}"
: "${ADMIN_SUPABASE_USER_IDS:?Set ADMIN_SUPABASE_USER_IDS}"
: "${BACKUP_RECOVERY_URL:?Set BACKUP_RECOVERY_URL}"
: "${GEMINI_API_KEY:?Set GEMINI_API_KEY for Atlas Strategy Intelligence}"
: "${FORWARDED_ALLOW_IPS:?Set FORWARDED_ALLOW_IPS to trusted proxy IP/CIDR; never *}"
: "${MODEL_SIGNING_PUBLIC_KEY:?Set MODEL_SIGNING_PUBLIC_KEY to the Ed25519 public PEM}"
: "${MODEL_SIGNING_PRIVATE_KEY:?Set MODEL_SIGNING_PRIVATE_KEY to the Ed25519 private PEM (worker only)}"
GROQ_API_KEY="${GROQ_API_KEY:-}"
SECRET_KEY="${SECRET_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(48))')}"

PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')

gcloud config set project "$GCP_PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com

gcloud artifacts repositories describe "$AR_REPOSITORY" --location="$GCP_REGION" >/dev/null 2>&1 || \
gcloud artifacts repositories create "$AR_REPOSITORY" --repository-format=docker --location="$GCP_REGION" --description="Atlas Trading containers"

gcloud iam service-accounts describe "${SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$SERVICE_ACCOUNT" --display-name="Atlas Trading API"

gcloud iam service-accounts describe "${WORKER_SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$WORKER_SERVICE_ACCOUNT" --display-name="Atlas Trading Worker"

if ! gcloud storage buckets describe "gs://$MODEL_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$MODEL_BUCKET" --location="$GCP_REGION" --uniform-bucket-level-access
fi
if ! gcloud storage buckets describe "gs://$MODEL_STAGING_BUCKET" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$MODEL_STAGING_BUCKET" --location="$GCP_REGION" --uniform-bucket-level-access
fi
# Production serves only signed champion artifacts from MODEL_BUCKET. The API service account can
# read/list champions but cannot replace or delete them. Training/promotion uses MODEL_STAGING_BUCKET.
gcloud storage buckets add-iam-policy-binding "gs://$MODEL_BUCKET" \
  --member="serviceAccount:${SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/storage.objectViewer >/dev/null

gcloud storage buckets add-iam-policy-binding "gs://$MODEL_BUCKET" \
  --member="serviceAccount:${WORKER_SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/storage.objectUser >/dev/null

gcloud storage buckets add-iam-policy-binding "gs://$MODEL_STAGING_BUCKET" \
  --member="serviceAccount:${WORKER_SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/storage.objectUser >/dev/null

create_secret() {
  local name="$1" value="$2"
  if ! gcloud secrets describe "$name" >/dev/null 2>&1; then
    gcloud secrets create "$name" --replication-policy=automatic >/dev/null
  fi
  printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- >/dev/null
}

grant_secret_access() {
  local name="$1" account="$2"
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:${account}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}

create_secret atlas-database-url "$DATABASE_URL"
create_secret atlas-secret-key "$SECRET_KEY"
create_secret atlas-app-encryption-key "$APP_ENCRYPTION_KEY"
create_secret atlas-redis-url "$REDIS_URL"
create_secret atlas-usdt-tron-account-xpub "$USDT_TRON_ACCOUNT_XPUB"
create_secret atlas-model-signing-public-key "$MODEL_SIGNING_PUBLIC_KEY"
create_secret atlas-model-signing-private-key "$MODEL_SIGNING_PRIVATE_KEY"
create_secret atlas-trongrid-api-key "$TRONGRID_API_KEY"
create_secret atlas-supabase-anon-key "$SUPABASE_ANON_KEY"
create_secret atlas-funding-webhook-secret "$FUNDING_WEBHOOK_SECRET"
create_secret atlas-gemini-api-key "$GEMINI_API_KEY"
if [[ -n "$GROQ_API_KEY" ]]; then create_secret atlas-groq-api-key "$GROQ_API_KEY"; fi

# Least-privilege split: both API and worker need runtime/database/market-data secrets,
# but only the API needs Supabase and funding-webhook credentials.
for secret in atlas-database-url atlas-secret-key atlas-app-encryption-key atlas-redis-url atlas-usdt-tron-account-xpub atlas-trongrid-api-key atlas-gemini-api-key; do
  grant_secret_access "$secret" "$SERVICE_ACCOUNT"
  grant_secret_access "$secret" "$WORKER_SERVICE_ACCOUNT"
done
grant_secret_access atlas-supabase-anon-key "$SERVICE_ACCOUNT"
grant_secret_access atlas-funding-webhook-secret "$SERVICE_ACCOUNT"
grant_secret_access atlas-model-signing-public-key "$SERVICE_ACCOUNT"
grant_secret_access atlas-model-signing-public-key "$WORKER_SERVICE_ACCOUNT"
grant_secret_access atlas-model-signing-private-key "$WORKER_SERVICE_ACCOUNT"
if [[ -n "$GROQ_API_KEY" ]]; then grant_secret_access atlas-groq-api-key "$SERVICE_ACCOUNT"; grant_secret_access atlas-groq-api-key "$WORKER_SERVICE_ACCOUNT"; fi

# Cloud Run service agent needs permission to use the service identity.
gcloud iam service-accounts add-iam-policy-binding \
  "${SERVICE_ACCOUNT}@${GCP_PROJECT_ID}.iam.gserviceaccount.com" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role=roles/iam.serviceAccountUser >/dev/null || true

echo "Bootstrap complete. Next run deploy/cloud-run-deploy.sh with the same project variables."
