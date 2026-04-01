#!/usr/bin/env python3
"""
Configuration module for Flight Price Prediction Pipeline.
Centralizes all constants, routes, and environment variable loading.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==============================================================================
# Routes - Top 50 origin-destination pairs for fare collection
# Dynamically loaded from BTS data or hardcoded fallback
# ==============================================================================
# Default routes (used when BTS data is unavailable)
DEFAULT_ROUTES = [
    {"origin": "JFK", "destination": "LAX"},
    {"origin": "LAX", "destination": "JFK"},
    {"origin": "ORD", "destination": "LAX"},
    {"origin": "LAX", "destination": "ORD"},
    {"origin": "JFK", "destination": "LHR"},
    {"origin": "LHR", "destination": "JFK"},
    {"origin": "ORD", "destination": "JFK"},
    {"origin": "JFK", "destination": "ORD"},
    {"origin": "LAX", "destination": "LHR"},
    {"origin": "LHR", "destination": "LAX"},
    {"origin": "ATL", "destination": "DFW"},
    {"origin": "DFW", "destination": "ATL"},
    {"origin": "SFO", "destination": "LAX"},
    {"origin": "LAX", "destination": "SFO"},
    {"origin": "MIA", "destination": "ORD"},
    {"origin": "ORD", "destination": "MIA"},
    {"origin": "SEA", "destination": "SFO"},
    {"origin": "SFO", "destination": "SEA"},
    {"origin": "BOS", "destination": "LAX"},
    {"origin": "LAX", "destination": "BOS"},
]


def get_top_routes(limit=50):
    """
    Get the top N most popular routes based on BTS data.
    Falls back to DEFAULT_ROUTES if BTS data is unavailable.

    Args:
        limit: Number of routes to return (default 50)

    Returns:
        List of route dicts with 'origin' and 'destination' keys
    """
    try:
        import pandas as pd
        from bts_client import download_db1b_market

        # Download recent BTS data to find most popular routes
        df = download_db1b_market(2024, 1)
        if df is not None and not df.empty:
            # Count routes by frequency
            route_counts = df.groupby(["origin", "dest"]).size().reset_index(name="count")
            route_counts = route_counts.sort_values("count", ascending=False)

            # Get top N routes - normalize key from 'dest' to 'destination'
            top_routes = []
            for _, row in route_counts.head(limit).iterrows():
                top_routes.append({
                    "origin": row["origin"],
                    "destination": row["dest"]
                })

            # Ensure we have the default routes included (they're known good routes)
            default_origins = {(r["origin"], r["destination"]) for r in DEFAULT_ROUTES}
            for route in DEFAULT_ROUTES:
                route_key = (route["origin"], route["destination"])
                if route_key not in default_origins:
                    if len(top_routes) < limit:
                        top_routes.append(route)
                        default_origins.add(route_key)

            print(f"INFO: Loaded {len(top_routes)} top routes from BTS data")
            return top_routes
    except Exception as e:
        print(f"WARNING: Could not load top routes from BTS: {e}")

    # Fallback to defaults
    print(f"INFO: Using {len(DEFAULT_ROUTES)} default routes (BTS fallback)")
    return DEFAULT_ROUTES[:limit]

# ==============================================================================
# Pipeline constants
# ==============================================================================
DEPARTURE_DAYS_OUT = [1, 3, 7]  # Days before departure to fetch fares

# BTS data years for baseline computation
HISTORICAL_YEARS = [2022, 2023, 2024]

# Quarter mapping
QUARTER_MAPPING = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}

# BTS data cache directory
BTS_CACHE_DIR = Path("bts_cache")

# S3 paths
RAW_S3_PREFIX = "raw/amadeus"
ENRICHED_BQ_TABLE = "fare_snapshots"
BASELINES_BQ_TABLE = "route_baselines"

# Buy signal thresholds (percentage below/above historical median)
BUY_SIGNAL_THRESHOLDS = {
    "great_deal": -15.0,  # >15% below median
    "good_price": -5.0,   # 5-15% below median
    "typical": 10.0,      # within 10% of median
    "high": 10.0,         # >10% above median
}

# Fare filtering for BTS data (remove outliers) - expanded for leniency
FARE_MIN = 20   # Was 30 - more lenient
FARE_MAX = 3000  # Was 2000 - more lenient

# Minimum sample size for baseline computation
MIN_BASELINE_SAMPLES = 10  # Allow baselines with as few as 10 samples

# ==============================================================================
# Environment variable loading
# ==============================================================================
REQUIRED_ENV_VARS = {
    "AMADEUS_CLIENT_ID": "Your Amadeus client ID",
    "AMADEUS_CLIENT_SECRET": "Your Amadeus client secret",
}

AWS_ENV_VARS = {
    "AWS_ACCESS_KEY_ID": "AWS access key ID",
    "AWS_SECRET_ACCESS_KEY": "AWS secret access key",
    "AWS_DEFAULT_REGION": "AWS region (default: us-east-1)",
    "S3_BUCKET": "S3 bucket name for raw data storage",
}

BQ_ENV_VARS = {
    "GOOGLE_APPLICATION_CREDENTIALS": "Absolute path to BigQuery service account JSON",
    "BQ_DATASET": "BigQuery dataset name",
    "BQ_TABLE": "BigQuery table name for fare snapshots (default: fare_snapshots)",
}


def load_env():
    """
    Load and validate environment variables.
    Returns a dict with validated config, raises ValueError if missing required vars.
    """
    config = {}

    # Check Amadeus credentials
    missing_amadeus = [k for k in REQUIRED_ENV_VARS if not os.environ.get(k)]
    if missing_amadeus:
        raise ValueError(
            f"Missing required Amadeus environment variables: {', '.join(missing_amadeus)}"
        )

    config["amadeus_client_id"] = os.environ["AMADEUS_CLIENT_ID"]
    config["amadeus_client_secret"] = os.environ["AMADEUS_CLIENT_SECRET"]

    # Check AWS credentials (optional for testing)
    config["aws_access_key_id"] = os.environ.get("AWS_ACCESS_KEY_ID")
    config["aws_secret_access_key"] = os.environ.get("AWS_SECRET_ACCESS_KEY")
    config["aws_default_region"] = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    config["s3_bucket"] = os.environ.get("S3_BUCKET")

    # Check BigQuery credentials (optional for testing)
    config["gcp_credentials_path"] = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    config["bq_dataset"] = os.environ.get("BQ_DATASET", "flight_data")
    config["bq_table"] = os.environ.get("BQ_TABLE", "fare_snapshots")
    config["bq_baseline_table"] = "route_baselines"

    # Create cache directory if needed
    BTS_CACHE_DIR.mkdir(exist_ok=True)

    return config


def get_current_quarter(date=None):
    """Get the quarter string (e.g., 'Q1') for a given date."""
    import datetime
    if date is None:
        date = datetime.date.today()
    quarter = (date.month - 1) // 3 + 1
    return QUARTER_MAPPING[quarter]


def get_days_to_departure(departure_date):
    """Calculate days from today to departure date."""
    import datetime
    if isinstance(departure_date, str):
        departure_date = datetime.date.fromisoformat(departure_date)
    today = datetime.date.today()
    return (departure_date - today).days


def get_route_baselines_years():
    """Generate list of (year, quarter) tuples for BTS baseline computation."""
    years_quarters = []
    for year in HISTORICAL_YEARS:
        for quarter in [1, 2, 3, 4]:
            years_quarters.append((year, quarter))
    return years_quarters


# For backwards compatibility - expose ROUTES as the default routes
ROUTES = DEFAULT_ROUTES
