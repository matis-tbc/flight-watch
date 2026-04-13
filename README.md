FlightWatch

Goal
- Track flight prices over time
- Detect lowest or meaningful drops
- Notify users when conditions hit

Scope (v1)
- Search a route
- Track one or more routes
- Store price history
- Scheduled price checks
- Email notifications

Out of scope (v1)
- Full user accounts (optional)
- Payments
- Mobile app!

Tech stack (current)
- Frontend: Vanilla HTML/JS (served statically by FastAPI)
- Backend: FastAPI (Python)
- Data Source: Google Cloud Storage (CSV batch data), Amadeus API (live flight data), Mock data
- DB: PostgreSQL + SQLAlchemy (Planned)
- Scheduler: cron, Celery + Redis (Planned)
- Email: SendGrid / SES / Gmail SMTP (Planned)

Repo map
- docs/          Product docs, decisions, meetings
- backend/       FastAPI app and scheduler code that runs in production
- frontend/      Static frontend assets currently served by FastAPI
- infra/         Cloud, env, deployment notes
- scripts/       Standalone data collection and pipeline utilities

Lanes
- A Backend/API: endpoints, validation, swagger
- B Database: schema, models, migrations
- C Flight API: client, parsing, reliability
- D Scheduler: cron, drops, email, dedupe
- E Frontend: search, track, chart, states
- F QA/DevOps: env, secrets, deploy, tests

## Local Setup (Quick Start)

1. **Get GCP access** - Ask a teammate for the service account key file (`service-account-key.json`).
2. **Place the key** in the `backend/` directory.
3. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   ```
4. **Activate the virtual environment**:
   Windows PowerShell:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   Windows Git Bash:
   ```bash
   source .venv/Scripts/activate
   ```
   macOS/Linux:
   ```bash
   source .venv/bin/activate
   ```
5. **Install Python dependencies from the repo root**:
   ```bash
   python -m pip install -e ".[backend,dev]"
   ```
6. **Copy environment config**:
   ```bash
   cd backend
   cp .env.example .env
   ```
7. **Update `.env`**: Make sure `GCS_BUCKET` and `GCS_FILE_PATH` are set correctly.
8. **Run the backend**:
   ```bash
   python -m flightwatch_backend.api
   ```
9. **Access the Application**:
   - API: http://localhost:8000
   - Frontend: http://localhost:8000/frontend/simple_search.html

Python workspace notes
- The repo is a small monorepo, not a single importable Python package.
- `pyproject.toml` now lives at the repo root because dependencies are shared across `backend/` and `scripts/`.
- The backend now follows a `src` layout at `backend/src/flightwatch_backend/`.
- `backend/` still contains deployment files, tests, and a few legacy entrypoints, but the packaged modules under `backend/src/` are the source of truth.

Next steps
- Create repo structure (done here)
- Lock tech stack with professor
- Validate flight API limits and costs
- Decide drop detection logic

Deployment
- Cloud Run deployment guide: `infra/README.md`

Open questions
- Drop logic: absolute, percent, or window low?
- Scheduler cadence: 6h vs 12h vs adaptive
- Auth: v1 off, v2 on
