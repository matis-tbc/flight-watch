#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-us-central1}"
ARTIFACT_REPO="${ARTIFACT_REPO:-flightwatch}"
IMAGE_NAME="${IMAGE_NAME:-flightwatch-backend}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${IMAGE_NAME}:${IMAGE_TAG}"

API_SERVICE="${API_SERVICE:-flightwatch-api}"
SCHEDULER_SERVICE="${SCHEDULER_SERVICE:-flightwatch-scheduler}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"

GCS_BUCKET="${GCS_BUCKET:-}"
GCS_FILE_PATH="${GCS_FILE_PATH:-}"
INGEST_RAW_BUCKET="${INGEST_RAW_BUCKET:-}"
INGEST_RAW_PREFIX="${INGEST_RAW_PREFIX:-raw}"
INGEST_MAX_OFFERS="${INGEST_MAX_OFFERS:-20}"
INGEST_MAX_RETRIES="${INGEST_MAX_RETRIES:-3}"
FROM_EMAIL="${FROM_EMAIL:-}"
APP_BASE_URL="${APP_BASE_URL:-}"

AMADEUS_CLIENT_ID_SECRET="${AMADEUS_CLIENT_ID_SECRET:-}"
AMADEUS_CLIENT_SECRET_SECRET="${AMADEUS_CLIENT_SECRET_SECRET:-}"
SENDGRID_API_KEY_SECRET="${SENDGRID_API_KEY_SECRET:-}"
SCHEDULER_TOKEN_SECRET="${SCHEDULER_TOKEN_SECRET:-}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "PROJECT_ID is required."
  exit 1
fi

if [[ -z "${GCS_BUCKET}" || -z "${GCS_FILE_PATH}" ]]; then
  echo "GCS_BUCKET and GCS_FILE_PATH are required."
  exit 1
fi

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

append_arg() {
  local array_name="$1"
  local value="$2"
  eval "$array_name+=(\"\$value\")"
}

join_by_comma() {
  local first=1
  for item in "$@"; do
    if [[ -z "$item" ]]; then
      continue
    fi
    if [[ $first -eq 1 ]]; then
      printf "%s" "$item"
      first=0
    else
      printf ",%s" "$item"
    fi
  done
}

build_env_vars() {
  local service_mode="$1"
  join_by_comma \
    "SERVICE_MODE=${service_mode}" \
    "GCP_PROJECT_ID=${PROJECT_ID}" \
    "GCS_BUCKET=${GCS_BUCKET}" \
    "GCS_FILE_PATH=${GCS_FILE_PATH}" \
    "${INGEST_RAW_BUCKET:+INGEST_RAW_BUCKET=${INGEST_RAW_BUCKET}}" \
    "INGEST_RAW_PREFIX=${INGEST_RAW_PREFIX}" \
    "INGEST_MAX_OFFERS=${INGEST_MAX_OFFERS}" \
    "INGEST_MAX_RETRIES=${INGEST_MAX_RETRIES}" \
    "${FROM_EMAIL:+FROM_EMAIL=${FROM_EMAIL}}" \
    "${APP_BASE_URL:+APP_BASE_URL=${APP_BASE_URL}}"
}

build_secret_vars() {
  join_by_comma \
    "${AMADEUS_CLIENT_ID_SECRET:+AMADEUS_CLIENT_ID=${AMADEUS_CLIENT_ID_SECRET}:latest}" \
    "${AMADEUS_CLIENT_SECRET_SECRET:+AMADEUS_CLIENT_SECRET=${AMADEUS_CLIENT_SECRET_SECRET}:latest}" \
    "${SENDGRID_API_KEY_SECRET:+SENDGRID_API_KEY=${SENDGRID_API_KEY_SECRET}:latest}" \
    "${SCHEDULER_TOKEN_SECRET:+SCHEDULER_TOKEN=${SCHEDULER_TOKEN_SECRET}:latest}"
}

deploy_service() {
  local service_name="$1"
  local service_mode="$2"
  local -a args
  args=(
    run deploy "$service_name"
    --project "$PROJECT_ID"
    --region "$REGION"
    --image "$IMAGE_URI"
    --platform managed
    --allow-unauthenticated
    --set-env-vars "$(build_env_vars "$service_mode")"
  )

  if [[ -n "$SERVICE_ACCOUNT_EMAIL" ]]; then
    append_arg args --service-account
    append_arg args "$SERVICE_ACCOUNT_EMAIL"
  fi

  local secret_vars
  secret_vars="$(build_secret_vars)"
  if [[ -n "$secret_vars" ]]; then
    append_arg args --set-secrets
    append_arg args "$secret_vars"
  fi

  gcloud "${args[@]}"
}

require_command gcloud

echo "Building image ${IMAGE_URI}"
gcloud builds submit "$ROOT_DIR" --project "$PROJECT_ID" --tag "$IMAGE_URI"

echo "Deploying API service ${API_SERVICE}"
deploy_service "$API_SERVICE" api

echo "Deploying scheduler service ${SCHEDULER_SERVICE}"
deploy_service "$SCHEDULER_SERVICE" scheduler

echo "API URL:"
gcloud run services describe "$API_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format='value(status.url)'

echo "Scheduler URL:"
gcloud run services describe "$SCHEDULER_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format='value(status.url)'
