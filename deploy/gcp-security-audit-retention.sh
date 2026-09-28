#!/usr/bin/env bash
set -euo pipefail
PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
BUCKET_ID="${BUCKET_ID:-atlas-security-audit}"
LOCATION="${LOCATION:-global}"
RETENTION_DAYS="${RETENTION_DAYS:-3650}"
SINK_NAME="${SINK_NAME:-atlas-security-audit-sink}"

gcloud logging buckets create "$BUCKET_ID" --project="$PROJECT_ID" --location="$LOCATION" --description="Atlas security audit events" --retention-days="$RETENTION_DAYS" 2>/dev/null || true
gcloud logging buckets update "$BUCKET_ID" --project="$PROJECT_ID" --location="$LOCATION" --retention-days="$RETENTION_DAYS"

DEST="logging.googleapis.com/projects/${PROJECT_ID}/locations/${LOCATION}/buckets/${BUCKET_ID}"
FILTER='jsonPayload.atlas_security_audit=true'
if ! gcloud logging sinks describe "$SINK_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud logging sinks create "$SINK_NAME" "$DEST" --project="$PROJECT_ID" --log-filter="$FILTER" --description="Route Atlas security audit events to locked retention bucket"
fi

echo "Verify the sink and IAM writer identity, then lock the bucket ONLY after retention and access policy review:"
echo "gcloud logging sinks describe $SINK_NAME --project=$PROJECT_ID"
echo "gcloud logging buckets describe $BUCKET_ID --location=$LOCATION --project=$PROJECT_ID"
echo "gcloud logging buckets update $BUCKET_ID --location=$LOCATION --project=$PROJECT_ID --locked"
