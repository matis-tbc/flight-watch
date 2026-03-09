# FlightWatch Backend

FastAPI backend serving real flight data from Google Cloud Storage.

## Quick Start
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app_simple_gcs.py
```

API runs at http://localhost:8000

## Setup for New Team Members

1. **Get GCP access** - Ask a teammate for the service account key file (`service-account-key.json`)
2. **Place the key** in the `backend/` directory
3. **Copy environment config**:
```bash
   cp .env.example .env
```
4. **Run the backend** (see Quick Start above)

## API Endpoints

- `GET /` - API info
- `GET /health` - Health check with GCS data status
- `GET /api/search?origin=JFK&destination=LAX` - Search flights
- `GET /api/airports` - List all available airports for autocomplete
- `GET /api/airports/suggest?q=JFK` - Airport suggestions
- `GET /api/gcs-info` - GCS data summary
- `GET /api/tracks` - List tracked flights
- `POST /api/tracks` - Add a flight to track
- `DELETE /api/tracks/{id}` - Remove a tracked flight
- `POST /internal/ingest` - Scheduler-only ingestion from Amadeus -> GCS raw archive + Firestore routes/history
- `POST /check-prices` - Scheduler-only price drop check → triggers emails if drop detected
- `GET /docs` - Interactive API documentation

## Data Source

Real flight data loaded from Google Cloud Storage:
- Bucket:`flight-batch-v1`
- File: `flight_data_batch.csv`
- Records: 52,529 flights
- Airports: 82 origins, 84 destinations

## Frontend Integration

The backend provides airport suggestions for autocomplete. Example frontend usage:
```javascript
// Get airport suggestions
fetch('http://localhost:8000/api/airports/suggest?q=JFK')
  .then(res => res.json())
  .then(data => console.log(data))

// Search flights
fetch('http://localhost:8000/api/search?origin=JFK&destination=LAX')
  .then(res => res.json())
  .then(data => console.log(data))
```

## Environment Variables (.env)
```env
GCP_PROJECT_ID=flightwatch-486618
GCS_BUCKET=flight-batch-v1
GCS_FILE_PATH=flight_data_batch.csv
GOOGLE_APPLICATION_CREDENTIALS=service-account-key.json
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
INGEST_RAW_BUCKET=...         # optional, fallback is GCS_BUCKET
INGEST_RAW_PREFIX=raw
INGEST_MAX_OFFERS=20
INGEST_MAX_RETRIES=3
SCHEDULER_TOKEN=...
SENDGRID_API_KEY=SG.xxxxxxxxx # from SendGrid dashboard → API Keys
FROM_EMAIL=you@example.com    # must be verified in SendGrid
APP_BASE_URL=https://yourapp.com
```

## Cloud Scheduler Setup (Ingestion)

Use Cloud Scheduler to call `POST /internal/ingest` on your deployed backend.
```bash
# set these for your environment
PROJECT_ID="flightwatch-486618"
REGION="us-central1"
JOB_NAME="flightwatch-ingest"
SERVICE_URL="https://YOUR_CLOUD_RUN_URL/internal/ingest"
SCHEDULER_TOKEN="replace-with-strong-random-token"
CRON_SCHEDULE="*/15 * * * *"
```

Create the job:
```bash
gcloud scheduler jobs create http "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="$CRON_SCHEDULE" \
  --time-zone="America/New_York" \
  --uri="$SERVICE_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Scheduler-Token=$SCHEDULER_TOKEN" \
  --message-body='{}'
```

Run immediately (manual test):
```bash
gcloud scheduler jobs run "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION"
```

Update existing schedule:
```bash
gcloud scheduler jobs update http "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 * * * *"
```

The backend checks `X-Scheduler-Token` against `SCHEDULER_TOKEN` from environment.

## SendGrid Email Setup (Price-Drop Alerts)

The `/check-prices` endpoint emails users when a tracked flight drops in price.
Emails are sent via SendGrid using `sendgrid_logic.py`.

### Prerequisites

1. Create a free account at [sendgrid.com](https://sendgrid.com)
2. Go to **Settings → API Keys → Create API Key** with **Mail Send** (Full Access)
3. Go to **Settings → Sender Authentication → Verify a Single Sender** and verify the email you'll send from
4. Add `SENDGRID_API_KEY`, `FROM_EMAIL`, and `APP_BASE_URL` to your `.env` (see Environment Variables above)

### Testing the Email Integration

Simulate a price drop locally without touching Firestore or GCS:
```bash
# Basic run (uses hardcoded test values in the script)
python sendgrid_logic.py

# Override prices via env to test different drop scenarios
TEST_OLD_PRICE=600 TEST_NEW_PRICE=199 python sendgrid_logic.py
```

Expected output on success:
```
API key loaded: True
FROM_EMAIL: your-verified-sender@gmail.com
Simulating drop: $450.00 → $320.00 on JFK -> CDG
INFO:sendgrid_logic:Email sent to shazbayl@gmail.com for JFK -> CDG on 2026-04-01
Email sent: True
```

### How It Works in Production

When Cloud Scheduler triggers `POST /check-prices`, the backend:

1. Reads all tracked flights from Firestore (`tracked_flights` collection)
2. Fetches the latest price from GCS for each route
3. Compares against `doc["latest_price"]` stored in Firestore
4. If a drop is detected → calls `send_price_drop_email()` → updates Firestore with the new price

### Cloud Scheduler Setup (Price-Drop Check)

Create a second scheduler job to run `/check-prices` every morning:
```bash
gcloud scheduler jobs create http "flightwatch-check-prices" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://YOUR_CLOUD_RUN_URL/check-prices" \
  --http-method=POST \
  --headers="Content-Type=application/json,X-Scheduler-Token=$SCHEDULER_TOKEN" \
  --message-body='{}'
```

> **Note:** Run `/internal/ingest` before `/check-prices` each morning so price comparisons use fresh data. Set ingest at `0 7 * * *` and check-prices at `0 8 * * *`.

## Troubleshooting

- **Port 8000 already in use**: `pkill -f "python3 app_simple_gcs.py"`
- **GCS permission errors**: Verify service account has `Storage Object Viewer` role
- **Python import errors**: Make sure virtual environment is activated
- **SendGrid 403 Forbidden**: Sender email not verified — complete Single Sender Verification in SendGrid dashboard
- **Emails land in spam**: Using a Gmail sender address — switch to a domain-based email and complete Domain Authentication in SendGrid

## Team Workflow

1. Pull latest changes: `git pull origin main`
2. Activate virtual environment: `source venv/bin/activate`
3. Install new dependencies if needed: `pip install -r requirements.txt`
4. Run backend: `python3 app_simple_gcs.py`
5. Test with: `curl http://localhost:8000/health`