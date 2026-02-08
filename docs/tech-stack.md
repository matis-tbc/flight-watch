Tech stack (current leaning)

Frontend
- React
- Client-side routing
- Fetch wrapper for API

Backend
- FastAPI (Python)
- Pydantic schemas
- SQLAlchemy ORM

Database
- PostgreSQL
- Migrations via Alembic

Scheduler
- Cron for MVP
- Celery + Redis if needed

Flight API
- Amadeus (recommended)
- Alternatives: Skyscanner, Kiwi

Notifications
- Email: SendGrid or SES
- Gmail SMTP for MVP fallback

Cloud
- AWS or GCP
- Compute: EC2 / Elastic Beanstalk
- DB: RDS Postgres
- Storage: S3 for logs/backups
