# FlightWatch

## Stack
- Backend: FastAPI (Python 3.13), Firestore, GCS, SendGrid
- Frontend: Vanilla HTML/CSS/JS with Leaflet.js (single file: frontend/simple_search.html)
- Scheduler: Flask microservice (scheduler.py) triggered by Cloud Scheduler
- Deployment: Docker on Google Cloud Run
- GCP Project: flightwatch-486618

## Running locally
```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
python3 app_simple_gcs.py          # FastAPI on http://localhost:8000
```
Frontend: http://localhost:8000/frontend/simple_search.html

## Testing
```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```
Always run tests before committing backend changes.

## Workflow
- Run /review before creating PRs
- Use /ship for PR creation when possible
- Use /qa or /browse after frontend changes to verify visually
- Run pytest before committing backend changes
- Always ask before git pushing
- Never auto-merge without asking

## Code style
- No Co-Authored-By lines in commits
- Keep commit messages concise, all signal
- No em dashes in any output or deliverables
- Use project-local venv, never system pip

## Key files
- backend/app_simple_gcs.py: FastAPI routes (search, tracks, explore, predict)
- backend/gcs_data_service_simple.py: GCS CSV data access layer
- backend/firestore_logic.py: Firestore CRUD + notification dedup
- backend/scheduler.py: Flask price-check + ingest jobs
- backend/sendgrid_logic.py: Email notifications
- frontend/simple_search.html: Entire frontend (search, map, advisor, budget explorer)
- backend/tests/test_api.py: pytest suite

## Known issues
- Firestore service account needs Cloud Datastore User role (pending IAM change from project owner)
- Scheduler endpoints require SCHEDULER_TOKEN env var (denied by default when unset)
- Frontend is a single 2000+ line HTML file (React migration planned but not urgent)
