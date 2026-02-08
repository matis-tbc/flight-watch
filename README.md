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
- Mobile app

Tech stack (current)
- Frontend: React
- Backend: FastAPI (Python)
- DB: PostgreSQL + SQLAlchemy
- Scheduler: cron (or Celery + Redis)
- Flight API: Amadeus (fallbacks later)
- Email: SendGrid / SES / Gmail SMTP

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

Next steps
- Create repo structure (done here)
- Lock tech stack with professor
- Validate flight API limits and costs
- Decide drop detection logic

Open questions
- Drop logic: absolute, percent, or window low?
- Scheduler cadence: 6h vs 12h vs adaptive
- Auth: v1 off, v2 on
