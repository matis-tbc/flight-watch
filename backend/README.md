Backend (FastAPI) outline

Purpose
- Serve API for search, tracking, history, notifications
- Integrate flight API providers
- Apply drop logic

Planned layout
- app/
  - main.py (app entry)
  - api/ (routers, versioned)
  - schemas/ (Pydantic models)
  - models/ (SQLAlchemy models)
  - db/ (session, migrations)
  - services/ (flight provider, tracking, notifications)
  - tasks/ (scheduled jobs)
  - core/ (settings, logging)
  - utils/ (shared helpers)
- tests/

Notes
- Keep API contract aligned with docs/api-contract.md
- Keep models aligned with docs/database.md
