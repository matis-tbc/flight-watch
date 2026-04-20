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
- backend/       FastAPI service outline
- frontend/      React app outline
- infra/         Cloud, env, deployment notes
- scripts/       Helpers (seed, migrations, jobs)

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
3. **Copy environment config**:
   ```bash
   cd backend
   cp .env.example .env
   ```
4. **Update `.env`**: Make sure `GCS_BUCKET` and `GCS_FILE_PATH` are set correctly.
5. **Run the backend**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python3 app_simple_gcs.py
   ```
6. **Access the Application**: 
   - API: http://localhost:8000
   - Frontend: http://localhost:8000/frontend/simple_search.html

Next steps
- Create repo structure (done here)
- Lock tech stack with professor
- Validate flight API limits and costs
- Decide drop detection logic

Deployment
- Cloud Run deployment guide: [infra/README.md](/Users/sharonbayela/Documents/GitHub/flight-watch/infra/README.md)

Live Deployment
- Frontend: https://flightwatch-api-lsqbnpoonq-uc.a.run.app/frontend/simple_search.html
- API: https://flightwatch-api-lsqbnpoonq-uc.a.run.app
- API Docs: https://flightwatch-api-lsqbnpoonq-uc.a.run.app/docs
- Scheduler: https://flightwatch-scheduler-lsqbnpoonq-uc.a.run.app
- Note: These URLs point to the current production Cloud Run services for project `flightwatch-486618`.

Open questions
- Drop logic: absolute, percent, or window low?
- Scheduler cadence: 6h vs 12h vs adaptive
- Auth: v1 off, v2 on
