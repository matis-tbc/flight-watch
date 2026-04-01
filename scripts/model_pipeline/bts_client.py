#!/usr/bin/env python3
"""
BTS (Bureau of Transportation Statistics) client for flight price data.
Handles downloading and caching of DB1B Market data.
"""

import os
import zipfile
import io
import urllib.request
from pathlib import Path
from datetime import datetime

# Import config
from config import BTS_CACHE_DIR, HISTORICAL_YEARS, FARE_MIN, FARE_MAX


def download_db1b_market(year, quarter):
    """
    Download BTS DB1B Market data for a given year and quarter.

    Args:
        year: Year (e.g., 2024)
        quarter: Quarter (1-4)

    Returns:
        pandas DataFrame with the DB1B data, or None on failure.
    """
    try:
        import pandas as pd

        # Create cache directory if needed
        BTS_CACHE_DIR.mkdir(exist_ok=True)

        # Build URL
        quarter_str = f"Q{quarter}"
        filename = f"Origin_and_Destination_Survey_DB1BMarket_{year}_{quarter}.zip"
        url = f"https://transtats.bts.gov/PREZIP/{filename}"

        # Check cache
        cache_dir = BTS_CACHE_DIR / f"{year}_{quarter}"
        cache_dir.mkdir(exist_ok=True)
        csv_path = cache_dir / f"DB1BMarket_{year}_{quarter}.csv"

        if csv_path.exists():
            print(f"INFO: Loading cached BTS data for {year} {quarter_str}")
            df = pd.read_csv(csv_path)
            df.columns = df.columns.str.lower()
            return df

        print(f"INFO: Downloading BTS data for {year} {quarter_str}...")
        print(f"INFO: URL: {url}")

        # Download and extract
        try:
            with urllib.request.urlopen(url) as response:
                zip_data = response.read()

            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                # Find the CSV file in the zip
                csv_files = [f for f in zf.namelist() if f.endswith(".csv")]
                if csv_files:
                    with zf.open(csv_files[0]) as f:
                        df = pd.read_csv(f)
                        df.columns = df.columns.str.lower()
                else:
                    # Extract all and find CSV
                    zf.extractall(cache_dir)
                    csv_files = list(cache_dir.glob("*.csv"))
                    if csv_files:
                        df = pd.read_csv(csv_files[0])
                    else:
                        raise ValueError(f"No CSV file found in {filename}")

            # Cache the CSV for next time
            df.to_csv(csv_path, index=False)
            print(f"INFO: Downloaded and cached {len(df)} records")

            return df

        except urllib.error.HTTPError as e:
            print(f"ERROR: HTTP error downloading {filename}: {e}")
            return None
        except zipfile.BadZipFile as e:
            print(f"ERROR: Bad zip file for {year} Q{quarter}: {e}")
            return None

    except ImportError:
        print("ERROR: pandas not installed - cannot process BTS data")
        return None
    except Exception as e:
        print(f"ERROR: Failed to download BTS data for {year} Q{quarter}: {e}")
        return None


def build_route_baselines(years, routes, min_samples=10):
    """
    Build fare baselines for specified routes and years.
    More lenient version that accepts smaller sample sizes.

    Args:
        years: List of years (e.g., [2022, 2023, 2024])
        routes: List of route dicts with 'origin' and 'destination' keys
        min_samples: Minimum samples required for a baseline (default 10)

    Returns:
        pandas DataFrame with baseline statistics for each route/quarter.
    """
    try:
        import pandas as pd

        all_data = []

        # Download all years/quarters
        for year in years:
            for quarter in [1, 2, 3, 4]:
                df = download_db1b_market(year, quarter)
                if df is not None:
                    all_data.append(df)
                    print(f"INFO: Collected data for {year} Q{quarter}")

        if not all_data:
            print("ERROR: No BTS data collected")
            return None

        # Combine all data
        combined_df = pd.concat(all_data, ignore_index=True)
        print(f"INFO: Combined {len(combined_df)} total records")

        # Filter to relevant routes
        route_origins = [r["origin"] for r in routes]
        route_destinations = [r["destination"] for r in routes]

        filtered_df = combined_df[
            (combined_df["origin"].isin(route_origins)) &
            (combined_df["dest"].isin(route_destinations))
        ].copy()

        print(f"INFO: Filtered to {len(filtered_df)} records matching routes")

        # Filter fare range - use expanded range for leniency
        filtered_df = filtered_df[
            (filtered_df["mktfare"] >= FARE_MIN) &
            (filtered_df["mktfare"] <= FARE_MAX)
        ].copy()
        print(f"INFO: After fare filter (${FARE_MIN}-${FARE_MAX}): {len(filtered_df)} records")

        # Extract quarter from date (column is likely 'qrt' or 'date' in BTS data)
        # The BTS DB1B data has 'quarter' field or we need to derive from date
        # Check what column exists and use it
        date_col = None
        for col in filtered_df.columns:
            if 'date' in col.lower() or col.lower() == 'quarter':
                date_col = col
                break
        if date_col:
            filtered_df["quarter"] = pd.to_datetime(filtered_df[date_col]).dt.quarter
        else:
            print(f"WARNING: Could not find date column, columns: {list(filtered_df.columns)[:10]}")
            filtered_df["quarter"] = 1  # default

        # Group by route and quarter, compute statistics
        baselines = []

        for route in routes:
            origin = route["origin"]
            dest = route["destination"]

            route_data = filtered_df[
                (filtered_df["origin"] == origin) &
                (filtered_df["dest"] == dest)
            ]

            for quarter in [1, 2, 3, 4]:
                quarter_data = route_data[route_data["quarter"] == quarter]

                if len(quarter_data) >= min_samples:
                    fares = quarter_data["mktfare"]
                    baselines.append({
                        "origin": origin,
                        "destination": dest,
                        "quarter": f"Q{quarter}",
                        "baseline_median": fares.median(),
                        "baseline_mean": fares.mean(),
                        "baseline_std": fares.std(),
                        "baseline_p25": fares.quantile(0.25),
                        "baseline_p75": fares.quantile(0.75),
                        "sample_size": len(fares),
                        "years_included": ",".join(str(y) for y in years),
                    })
                elif len(quarter_data) > 0:
                    # Include baseline even with few samples, mark as lower quality
                    fares = quarter_data["mktfare"]
                    baselines.append({
                        "origin": origin,
                        "destination": dest,
                        "quarter": f"Q{quarter}",
                        "baseline_median": fares.median(),
                        "baseline_mean": fares.mean(),
                        "baseline_std": fares.std() if len(fares) > 1 else 0,
                        "baseline_p25": fares.quantile(0.25) if len(fares) >= 2 else fares.median(),
                        "baseline_p75": fares.quantile(0.75) if len(fares) >= 2 else fares.median(),
                        "sample_size": len(fares),
                        "years_included": ",".join(str(y) for y in years),
                    })
                    print(f"INFO: Created baseline with low samples ({len(fares)}) for {origin}-{dest} Q{quarter}")

        result_df = pd.DataFrame(baselines)
        print(f"INFO: Built baselines for {len(result_df)} route/quarter combinations")
        return result_df

    except Exception as e:
        print(f"ERROR: Failed to build route baselines: {e}")
        return None


def get_quarter_for_date(date_str):
    """
    Get the quarter string (e.g., 'Q1') for a given date string.

    Args:
        date_str: Date string in YYYY-MM-DD format

    Returns:
        Quarter string like 'Q1', 'Q2', etc.
    """
    from datetime import datetime
    date_obj = datetime.fromisoformat(date_str)
    quarter = (date_obj.month - 1) // 3 + 1
    return f"Q{quarter}"


if __name__ == "__main__":
    # Test downloading BTS data
    print("Testing BTS download...")
    df = download_db1b_market(2024, 1)

    if df is not None:
        print(f"Downloaded {len(df)} records")
        print(f"Columns: {list(df.columns)[:10]}...")

        # Test baseline building
        test_routes = [
            {"origin": "JFK", "destination": "LAX"},
            {"origin": "LAX", "destination": "JFK"},
        ]

        print("\nBuilding baselines for test routes...")
        baselines = build_route_baselines([2024], test_routes)

        if baselines is not None:
            print(f"Built {len(baselines)} baseline records")
            print(baselines.head())
    else:
        print("Failed to download BTS data")
