## GCP Deployment

FlightWatch now deploys cleanly to Cloud Run from the repo root with one image and two services:

- `flightwatch-api`
  Serves the FastAPI app and static frontend.
- `flightwatch-scheduler`
  Serves `/internal/ingest` and `/check-prices` for Cloud Scheduler.

### Why two services

The app has two runtime modes:

- `SERVICE_MODE=api` starts `app_simple_gcs.py`
- `SERVICE_MODE=scheduler` starts `scheduler.py`

Both modes use the same container image through [start.sh](/Users/sharonbayela/Documents/GitHub/flight-watch/backend/start.sh).

### Required GCP resources

Before deploying, create or confirm:

- A GCP project
- An Artifact Registry Docker repo
- Two Cloud Run services
- A Cloud Run service account with access to:
  `Storage Object Viewer`, `Storage Object Admin` if ingest uploads raw payloads, and Firestore access for tracked flights/history
- Secret Manager secrets for:
  `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET`, `SENDGRID_API_KEY`, `SCHEDULER_TOKEN`, `ADMIN_TOKEN`

### Required environment values

Plain env vars:

- `PROJECT_ID`
- `REGION`
- `GCS_BUCKET`
- `GCS_FILE_PATH`
- `INGEST_RAW_BUCKET` optional
- `INGEST_RAW_PREFIX` optional, defaults to `raw`
- `INGEST_MAX_OFFERS` optional
- `INGEST_MAX_RETRIES` optional
- `FROM_EMAIL`
- `APP_BASE_URL`
- `SERVICE_ACCOUNT_EMAIL`

Secret names:

- `AMADEUS_CLIENT_ID_SECRET`
- `AMADEUS_CLIENT_SECRET_SECRET`
- `SENDGRID_API_KEY_SECRET`
- `SCHEDULER_TOKEN_SECRET`
- `ADMIN_TOKEN_SECRET`

### Deploy

From the repo root:

```bash
export PROJECT_ID="flightwatch-486618"
export REGION="us-central1"
export ARTIFACT_REPO="flightwatch"
export API_SERVICE="flightwatch-api"
export SCHEDULER_SERVICE="flightwatch-scheduler"
export SERVICE_ACCOUNT_EMAIL="flightwatch-runner@${PROJECT_ID}.iam.gserviceaccount.com"

export GCS_BUCKET="flight-batch-v1"
export GCS_FILE_PATH="flight_data_batch.csv"
export INGEST_RAW_BUCKET="flight-batch-v1"
export FROM_EMAIL="alerts@example.com"
export APP_BASE_URL="https://flightwatch.example.com"

export AMADEUS_CLIENT_ID_SECRET="amadeus-client-id"
export AMADEUS_CLIENT_SECRET_SECRET="amadeus-client-secret"
export SENDGRID_API_KEY_SECRET="sendgrid-api-key"
export SCHEDULER_TOKEN_SECRET="scheduler-token"
export ADMIN_TOKEN_SECRET="admin-token"

bash infra/deploy_cloud_run.sh
```

The script will:

1. Build the image with Cloud Build using the root [Dockerfile](/Users/sharonbayela/Documents/GitHub/flight-watch/Dockerfile)
2. Deploy the API service with `SERVICE_MODE=api`
3. Deploy the scheduler service with `SERVICE_MODE=scheduler`
4. Print both Cloud Run URLs

To create the admin password secret in Secret Manager:

```bash
echo -n "flightwatchers!" | gcloud secrets create "admin-token" \
  --project="$PROJECT_ID" \
  --data-file=-
```

If the secret already exists, add a new version instead:

```bash
echo -n "flightwatchers!" | gcloud secrets versions add "admin-token" \
  --project="$PROJECT_ID" \
  --data-file=-
```

### Cloud Scheduler jobs

After deployment, create jobs that call the scheduler service URL with the shared token header:

```bash
SCHEDULER_URL="$(gcloud run services describe "$SCHEDULER_SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --format='value(status.url)')"

gcloud scheduler jobs create http "flightwatch-ingest" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="*/15 * * * *" \
  --uri="${SCHEDULER_URL}/internal/ingest" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Scheduler-Token=$(gcloud secrets versions access latest --secret=$SCHEDULER_TOKEN_SECRET --project=$PROJECT_ID)" \
  --message-body='{}'

gcloud scheduler jobs create http "flightwatch-check-prices" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 8 * * *" \
  --uri="${SCHEDULER_URL}/check-prices" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Scheduler-Token=$(gcloud secrets versions access latest --secret=$SCHEDULER_TOKEN_SECRET --project=$PROJECT_ID)" \
  --message-body='{}'
```

### Notes

- Cloud Run should use its attached service account in production. Do not set `GOOGLE_APPLICATION_CREDENTIALS` there.
- Local JSON key files are intentionally excluded from Docker and gcloud upload contexts by [.dockerignore](/Users/sharonbayela/Documents/GitHub/flight-watch/.dockerignore) and [.gcloudignore](/Users/sharonbayela/Documents/GitHub/flight-watch/.gcloudignore).
- The API container now includes the frontend and `scripts/flight_fetch`, so deployed behavior matches local behavior more closely.
