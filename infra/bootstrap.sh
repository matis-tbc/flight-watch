#!/usr/bin/env bash
# One-time GCP setup for flight-watch. Safe to re-run, operations are idempotent.
# Requires: gcloud authenticated as a user with Owner or Editor on the project.
#
# Usage:
#   set -a && source infra/.env.deploy && set +a
#   ./infra/bootstrap.sh
set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID required}"
: "${REGION:?REGION required}"
: "${ARTIFACT_REPO:?ARTIFACT_REPO required}"
: "${SERVICE_ACCOUNT_EMAIL:?SERVICE_ACCOUNT_EMAIL required}"
: "${SCHEDULER_INVOKER_SA:?SCHEDULER_INVOKER_SA required}"

RUNTIME_SA_NAME="${SERVICE_ACCOUNT_EMAIL%%@*}"
INVOKER_SA_NAME="${SCHEDULER_INVOKER_SA%%@*}"

echo "==> Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  --project "$PROJECT_ID"

echo "==> Artifact Registry repo"
gcloud artifacts repositories describe "$ARTIFACT_REPO" \
  --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$ARTIFACT_REPO" \
       --project "$PROJECT_ID" --location "$REGION" \
       --repository-format=docker

echo "==> Runtime service account: $SERVICE_ACCOUNT_EMAIL"
gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" \
  --project "$PROJECT_ID" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
       --project "$PROJECT_ID" --display-name="FlightWatch Runtime"

echo "==> Scheduler invoker service account: $SCHEDULER_INVOKER_SA"
gcloud iam service-accounts describe "$SCHEDULER_INVOKER_SA" \
  --project "$PROJECT_ID" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$INVOKER_SA_NAME" \
       --project "$PROJECT_ID" --display-name="FlightWatch Scheduler Invoker"

echo "==> Granting runtime SA project-level roles"
for role in roles/datastore.user roles/storage.objectViewer roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role="$role" --condition=None >/dev/null
done

echo "==> Creating empty secrets (you'll add versions next)"
for secret in amadeus-client-id amadeus-client-secret sendgrid-api-key scheduler-token admin-token serpapi-key; do
  gcloud secrets describe "$secret" --project "$PROJECT_ID" >/dev/null 2>&1 \
    || gcloud secrets create "$secret" --project "$PROJECT_ID" --replication-policy=automatic
done

echo
echo "Done. Next steps:"
echo "1. Add secret values (for each):"
echo "     printf '%s' 'VALUE' | gcloud secrets versions add SECRET_NAME --project $PROJECT_ID --data-file=-"
echo "2. Create Firestore database (once, pick region):"
echo "     gcloud firestore databases create --project $PROJECT_ID --location=$REGION"
echo "3. Run: ./infra/deploy_cloud_run.sh"
