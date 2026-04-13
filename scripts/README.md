Scripts

- `flight_fetch/` contains Amadeus-based local fetchers and batch collection scripts.
- `flight_fetch_serpapi/` contains the SerpApi-based collector that can upload CSV data to GCS.
- `model_pipeline/` contains the fare snapshot and baseline pipeline for analytics and ML prep.

Structure note
- This folder is intentionally top-level because these are standalone utilities, not runtime modules imported by the deployed FastAPI app.
- Install script dependencies from the repo root with `python -m pip install -e ".[scripts]"`.
