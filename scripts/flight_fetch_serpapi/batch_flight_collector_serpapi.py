#!/usr/bin/env python3
"""
Batch flight data collector using SerpApi (Google Flights)
Collects flight price data for the upcoming month and uploads to Google Cloud Storage.

Usage:
    python batch_flight_collector_serpapi.py                        # collect + upload to GCS
    python batch_flight_collector_serpapi.py --no-upload            # collect locally only
    python batch_flight_collector_serpapi.py --output-file my.csv   # custom output filename
"""

import os
import csv
import time
import argparse
import logging
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('batch_flight_collector_serpapi.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ── Config ────────────────────────────────────────────────────────────────────

SERPAPI_KEY    = os.environ.get('SERPAPI_KEY')
GCS_BUCKET     = os.environ.get('GCS_BUCKET', 'flight-batch-v1')
GCS_FILE_PATH  = os.environ.get('GCS_FILE_PATH', 'flight_data_batch.csv')
GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'flightwatch-486618')

SERPAPI_ENDPOINT = 'https://serpapi.com/search'

# Airport pairs to collect

#TEST MODE: 2 routes only
AIRPORT_PAIRS = [
    ("JFK", "LAX"),
    ("LAX", "JFK")
]
'''
AIRPORT_PAIRS = [
    ("JFK", "LAX"), ("LAX", "JFK"),
    ("ORD", "LAX"), ("LAX", "ORD"),
    ("JFK", "LHR"), ("LHR", "JFK"),
    ("ORD", "JFK"), ("JFK", "ORD"),
    ("LAX", "LHR"), ("LHR", "LAX"),
    ("ATL", "DFW"), ("DFW", "ATL"),
    ("SFO", "LAX"), ("LAX", "SFO"),
]
'''
# ── Date helpers ──────────────────────────────────────────────────────────────

def get_upcoming_month_dates():
    """Return every date in the next calendar month as YYYY-MM-DD strings."""
    today = datetime.now()
    year  = today.year + 1 if today.month == 12 else today.year
    month = 1             if today.month == 12 else today.month + 1

    start = datetime(year, month, 1)
    dates, current = [], start
    while current.month == start.month:
        dates.append(current.strftime('%Y-%m-%d'))
        current += timedelta(days=1)
    return dates[:3] #TEST MODE: 3 dates only, remove [:3] for full month

# ── SerpApi fetcher ───────────────────────────────────────────────────────────

def fetch_flights(origin: str, destination: str, departure_date: str) -> list[dict]:
    """
    Call the SerpApi Google Flights endpoint and return a flat list of
    row-dicts ready for CSV export.
    """
    params = {
        'engine':         'google_flights',
        'departure_id':   origin,
        'arrival_id':     destination,
        'outbound_date':  departure_date,
        'type':           '2',          # one-way
        'currency':       'USD',
        'hl':             'en',
        'api_key':        SERPAPI_KEY,
    }

    response = requests.get(SERPAPI_ENDPOINT, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if 'error' in data:
        raise ValueError(f"SerpApi error: {data['error']}")

    rows = []

    # price_insights is route-level — attach to every flight row
    price_insights     = data.get('price_insights', {})
    lowest_price       = price_insights.get('lowest_price', '')
    price_level        = price_insights.get('price_level', '')
    typical_price_low  = price_insights.get('typical_price_range', [None, None])[0]
    typical_price_high = price_insights.get('typical_price_range', [None, None])[1]

    # best_flights and other_flights have the same structure
    all_offers = data.get('best_flights', []) + data.get('other_flights', [])

    for offer in all_offers:
        total_duration = offer.get('total_duration', '')   # minutes
        total_price    = offer.get('price', '')

        for flight in offer.get('flights', []):
            dep = flight.get('departure_airport', {})
            arr = flight.get('arrival_airport', {})

            rows.append({
                # Core route info
                'origin':              dep.get('id', origin),
                'destination':         arr.get('id', destination),
                'departure_datetime':  dep.get('time', ''),
                'arrival_datetime':    arr.get('time', ''),
                'search_date':         departure_date,

                # Flight details
                'airline':             flight.get('airline', ''),
                'airline_code':        flight.get('airline', '')[:2] if flight.get('airline') else '',
                'flight_number':       flight.get('flight_number', ''),
                'airplane':            flight.get('airplane', ''),
                'travel_class':        flight.get('travel_class', ''),
                'legroom':             flight.get('legroom', ''),
                'duration_mins':       flight.get('duration', ''),
                'total_duration_mins': total_duration,

                # Pricing
                'total_price':         total_price,
                'currency':            'USD',

                # Price insights (useful features for predictive modelling)
                'lowest_price':        lowest_price,
                'price_level':         price_level,       # e.g. "low", "typical", "high"
                'typical_price_low':   typical_price_low,
                'typical_price_high':  typical_price_high,

                # Carbon
                'carbon_emissions_kg': flight.get('carbon_emissions', {}).get('this_flight', ''),
            })

    return rows

# ── GCS upload ────────────────────────────────────────────────────────────────

def upload_to_gcs(local_file: str, bucket_name: str, destination_blob: str):
    """Upload a local file to a GCS bucket."""
    try:
        from google.cloud import storage
    except ImportError:
        logger.error("google-cloud-storage not installed. Run: pip install -r requirements.txt")
        raise

    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(destination_blob)

    blob.upload_from_filename(local_file)
    logger.info(f"✅ Uploaded {local_file} → gs://{bucket_name}/{destination_blob}")

# ── Main collection loop ──────────────────────────────────────────────────────

def collect_batch_flight_data(output_file: str) -> list[dict]:
    """Collect flight data for all pairs × all dates in the upcoming month."""
    if not SERPAPI_KEY:
        raise ValueError(
            "SERPAPI_KEY not found. "
            "Make sure your .env file exists in this folder and contains SERPAPI_KEY."
        )

    dates         = get_upcoming_month_dates()
    airport_pairs = AIRPORT_PAIRS

    logger.info(f"Collecting data for {len(dates)} dates × {len(airport_pairs)} routes "
                f"= up to {len(dates) * len(airport_pairs)} requests")

    for date in dates:
        for origin, destination in airport_pairs:
            try:
                logger.info(f"  Fetching {origin} → {destination} on {date}")
                rows = fetch_flights(origin, destination, date)
                logger.info(f"    Got {len(rows)} offers")

                # Save to CSV immediately after each fetch
                fieldnames = list(rows[0].keys()) if rows else []
                file_exists = os.path.exists(output_file)
                with open(output_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerows(rows)

                time.sleep(0.5)

            except Exception as e:
                logger.error(f"  ✗ Failed {origin} → {destination} on {date}: {e}")
                continue   # keep going with remaining pairs

    logger.info(f"✅ Collection complete — rows saved to {output_file}")



# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Batch flight collector — SerpApi → GCS')
    parser.add_argument('--output-file', default='flight_data_batch_serpapi.csv',
                        help='Local CSV output filename (default: flight_data_batch_serpapi.csv)')
    parser.add_argument('--no-upload', action='store_true',
                        help='Skip GCS upload and keep the file locally only')
    args = parser.parse_args()

    logger.info("=== Starting batch flight data collection (SerpApi) ===")

    # 1. Collect
    collect_batch_flight_data(args.output_file)

    # 2. Upload to GCS (unless --no-upload)
    if not args.no_upload:
        if not os.path.exists(args.output_file):
            logger.error("Output file not found — nothing to upload.")
            return

        logger.info(f"Uploading to gs://{GCS_BUCKET}/{GCS_FILE_PATH} ...")
        upload_to_gcs(args.output_file, GCS_BUCKET, GCS_FILE_PATH)
    else:
        logger.info("Skipping GCS upload (--no-upload flag set).")

    logger.info("=== Done ===")


if __name__ == '__main__':
    main()