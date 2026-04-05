#!/usr/bin/env python3
"""
Transform module for Flight Price Prediction Pipeline.
Handles conversion of raw Amadeus offers to BigQuery-ready rows.
"""

import json
import uuid
from datetime import date
from amadeus_client import parse_fare_response
from storage import write_to_s3


def build_snapshot_row(raw_offers, origin, dest, departure_date, config):
    """
    Build a BigQuery-ready snapshot row from raw Amadeus fare data.

    Args:
        raw_offers: Raw API response dict from fetch_fares()
        origin: Origin airport code
        dest: Destination airport code
        departure_date: Departure date (date object or string)
        config: Configuration dict from config.load_env()

    Returns:
        Dict with BigQuery schema fields, or None if no valid offers.
    """
    # Parse the raw offers
    parsed_fares = parse_fare_response(raw_offers)

    if not parsed_fares:
        print(f"WARNING: No valid offers for {origin}-{dest} on {departure_date}")
        return None

    # Calculate days to departure
    if isinstance(departure_date, date):
        departure_date_str = departure_date.isoformat()
        days_to_departure = (departure_date - date.today()).days
    else:
        departure_date_str = departure_date
        from datetime import datetime
        days_to_departure = (datetime.fromisoformat(departure_date).date() - date.today()).days

    # Extract fare statistics
    prices = [fare["total_price"] for fare in parsed_fares if fare["total_price"] > 0]

    if not prices:
        print(f"WARNING: No valid prices for {origin}-{dest} on {departure_date}")
        return None

    prices_sorted = sorted(prices)
    median_fare = prices_sorted[len(prices_sorted) // 2]
    min_fare = min(prices)
    max_fare = max(prices)
    avg_fare = sum(prices) / len(prices)
    currency = parsed_fares[0]["currency"]

    # Get carriers (most common ones)
    carriers = list(set(carrier for fare in parsed_fares for carrier in fare["carriers"]))
    top_carriers = carriers[:3]  # Top 3 carriers

    # Generate snapshot ID
    snapshot_id = str(uuid.uuid4())

    # Write raw JSON to S3
    raw_data_key = f"{config.get('raw_s3_prefix', 'raw/amadeus')}/{date.today().isoformat()}/{origin}_{dest}_{departure_date_str}.json"
    raw_json = json.dumps(raw_offers, default=str)
    s3_key = write_to_s3(
        config.get("s3_bucket"),
        raw_data_key,
        raw_json
    )

    # Build the snapshot row (without buy signal - filled in pipeline.py)
    snapshot_row = {
        "snapshot_id": snapshot_id,
        "snapshot_date": date.today().isoformat(),
        "origin": origin,
        "destination": dest,
        "departure_date": departure_date_str,
        "days_to_departure": days_to_departure,
        "carrier": ",".join(top_carriers) if top_carriers else "N/A",
        "median_fare": round(median_fare, 2),
        "min_fare": round(min_fare, 2),
        "max_fare": round(max_fare, 2),
        "avg_fare": round(avg_fare, 2),
        "currency": currency,
        "raw_s3_key": s3_key,
        "buy_signal": "pending",  # Will be filled by pipeline.py
        "pct_vs_baseline": None,  # Will be filled by pipeline.py
        "historical_median": None,  # Will be filled by pipeline.py
        "num_offers": len(parsed_fares),
        "data_quality_score": 1.0 if len(parsed_fares) >= 5 else 0.5,
    }

    print(f"INFO: Built snapshot row for {origin}-{dest} (median: ${median_fare}, offers: {len(parsed_fares)})")
    return snapshot_row


def build_baseline_row(df_row):
    """
    Build a BigQuery-ready baseline row from BTS statistics.

    Args:
        df_row: pandas Series with route/quarter statistics

    Returns:
        Dict with BigQuery schema for route_baselines table.
    """
    return {
        "origin": df_row["origin"],
        "destination": df_row["destination"],
        "quarter": df_row["quarter"],
        "baseline_median": round(df_row["baseline_median"], 2),
        "baseline_mean": round(df_row["baseline_mean"], 2),
        "baseline_std": round(df_row["baseline_std"], 2),
        "baseline_p25": round(df_row["baseline_p25"], 2),
        "baseline_p75": round(df_row["baseline_p75"], 2),
        "sample_size": int(df_row["sample_size"]),
        "years_included": df_row["years_included"],
    }


if __name__ == "__main__":
    # Test with sample data
    sample_offers = {
        "data": [
            {
                "id": "1",
                "price": {"total": "299.99", "currency": "USD", "base": "250.00", "taxes": "49.99"},
                "validatingAirlineCodes": ["AA"],
                "itineraries": [{
                    "duration": "PT5H30M",
                    "segments": [{
                        "carrierCode": "AA",
                        "number": "100",
                        "departure": {"iataCode": "JFK"},
                        "arrival": {"iataCode": "LAX"},
                        "cabin": "ECONOMY"
                    }]
                }]
            },
            {
                "id": "2",
                "price": {"total": "325.00", "currency": "USD", "base": "275.00", "taxes": "50.00"},
                "validatingAirlineCodes": ["UA"],
                "itineraries": [{
                    "duration": "PT5H15M",
                    "segments": [{
                        "carrierCode": "UA",
                        "number": "200",
                        "departure": {"iataCode": "JFK"},
                        "arrival": {"iataCode": "LAX"},
                        "cabin": "ECONOMY"
                    }]
                }]
            }
        ]
    }

    print("Testing build_snapshot_row...")
    from config import load_env
    config = load_env()
    row = build_snapshot_row(sample_offers, "JFK", "LAX", "2026-04-01", config)
    if row:
        print(f"Snapshot row created: {row['snapshot_id']}")
        print(f"  Median fare: ${row['median_fare']}")
        print(f"  Raw S3 key: {row['raw_s3_key']}")
    else:
        print("Failed to build snapshot row")
