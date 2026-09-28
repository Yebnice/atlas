#!/usr/bin/env bash
set -euo pipefail
: "${PROJECT_ID:?Set PROJECT_ID}"
BUCKET_ID="${BUCKET_ID:-atlas-security-audit}"
LOCATION="${LOCATION:-global}"
SINK_NAME="${SINK_NAME:-atlas-security-audit-sink}"

echo "== Bucket =="
gcloud logging buckets describe "$BUCKET_ID" --project="$PROJECT_ID" --location="$LOCATION"
echo "== Sink =="
gcloud logging sinks describe "$SINK_NAME" --project="$PROJECT_ID"
echo "== Recent audit records (sample) =="
gcloud logging read 'jsonPayload.atlas_security_audit=true' --project="$PROJECT_ID" --limit=5 --format=json || true
echo
echo "Do not lock the bucket until retention and IAM have been reviewed. Cloud Logging bucket locking is irreversible."
