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
- `GET /docs` - Interactive API documentation

## Data Source

Real flight data loaded from Google Cloud Storage:
- Bucket: `flight-batch-v1`
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
```

## Troubleshooting

- **Port 8000 already in use**: `pkill -f "python3 app_simple_gcs.py"`
- **GCS permission errors**: Verify service account has `Storage Object Viewer` role
- **Python import errors**: Make sure virtual environment is activated

## Team Workflow

1. Pull latest changes: `git pull origin main`
2. Activate virtual environment: `source venv/bin/activate`
3. Install new dependencies if needed: `pip install -r requirements.txt`
4. Run backend: `python3 app_simple_gcs.py`
5. Test with: `curl http://localhost:8000/health`
