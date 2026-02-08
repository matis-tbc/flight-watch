Architecture (v1)

Components
- Frontend (React)
- Backend API (FastAPI)
- Database (PostgreSQL)
- Scheduler (cron / Celery)
- Flight API client (Amadeus)
- Email service

High-level flow
- User searches a route on frontend
- Backend queries flight API
- Backend returns price + metadata
- User opts to track
- Scheduler runs periodic price checks
- Backend writes price history
- Drop logic runs per route
- Email notification sent on trigger

Data ownership
- Backend is source of truth for tracking and history
- Frontend is read/write via API only

Risks
- Flight API rate limits
- Data quality + price volatility
- Scheduler reliability
