#!/usr/bin/env python3
"""
Pipeline orchestrator for Flight Price Prediction Pipeline.
Collects fares, enriches with baselines, and stores in BigQuery.
"""

import sys
from datetime import date

# Import local modules
from config import load_env, get_top_routes, DEPARTURE_DAYS_OUT, get_current_quarter, get_route_baselines_years
from amadeus_client import fetch_fares
from transform import build_snapshot_row
from bts_client import download_db1b_market, build_route_baselines
from baselines import enrich_snapshot_with_buy_signal
from storage import write_to_bigquery, load_existing_baselines, upsert_route_baselines


def log_step(step):
    """Print a standardized step log message."""
    print(f"\n{'='*60}")
    print(f"STEP: {step}")
    print(f"{'='*60}")


def load_or_bootstrap_baselines(config, force_rebuild=False, routes=None):
    """
    Load existing baselines from BigQuery or bootstrap from BTS.

    Args:
        config: Configuration dict
        force_rebuild: If True, rebuild baselines even if they exist
        routes: List of route dicts (uses config if not provided)

    Returns:
        pandas DataFrame with baseline data.
    """
    log_step("Load or Bootstrap Baselines")

    # Try to load from BigQuery first
    if not force_rebuild and config.get("bq_dataset"):
        print("INFO: Attempting to load existing baselines from BigQuery...")
        baselines = load_existing_baselines(
            config.get("bq_dataset"),
            config.get("bq_baseline_table", "route_baselines")
        )
        if baselines is not None and len(baselines) > 0:
            print(f"INFO: Loaded {len(baselines)} baseline records from BigQuery")
            return baselines

    # Bootstrap from BTS
    print("INFO: No existing baselines found, bootstrapping from BTS data...")
    years = get_route_baselines_years()

    # Get unique years
    unique_years = sorted(list(set(y for y, q in years)))
    print(f"INFO: Using years: {unique_years}")

    # Use routes from config if not provided
    if routes is None:
        routes = get_top_routes(limit=50)

    # Download and build baselines
    baselines_df = build_route_baselines(unique_years, routes)

    if baselines_df is not None and not baselines_df.empty:
        # Save to BigQuery if configured
        if config.get("bq_dataset"):
            print("INFO: Writing baselines to BigQuery...")
            result = upsert_route_baselines(
                config.get("bq_dataset"),
                config.get("bq_baseline_table", "route_baselines"),
                baselines_df
            )
            print(f"INFO: Baseline write result: {result}")

    print(f"INFO: Bootstrapped {len(baselines_df) if baselines_df is not None else 0} baseline records")
    return baselines_df


def collect_fare_snapshots(config, baselines_df, dry_run=False, routes=None):
    """
    Collect fare snapshots for all routes and departure days.

    Args:
        config: Configuration dict
        baselines_df: DataFrame with baseline statistics
        dry_run: If True, don't write to storage
        routes: List of route dicts (uses config if not provided)

    Returns:
        List of enriched snapshot rows.
    """
    log_step("Collect Fare Snapshots")

    # Use routes from config if not provided
    if routes is None:
        routes = get_top_routes(limit=50)

    snapshots = []
    total_calls = 0
    errors = []

    for route in routes:
        origin = route["origin"]
        dest = route["destination"]

        for days_out in DEPARTURE_DAYS_OUT:
            # Calculate departure date
            departure_date = date.today()
            from datetime import timedelta
            departure_date = departure_date + timedelta(days=days_out)

            # Fetch fares
            if not dry_run:
                raw_offers = fetch_fares(origin, dest, departure_date)
                total_calls += 1
            else:
                # Simulate for dry run
                raw_offers = None
                print(f"[DRY RUN] Would fetch fares for {origin}-{dest} {days_out} days out")

            if raw_offers is None:
                errors.append(f"{origin}-{dest} {days_out} days out: no response")
                continue

            # Build snapshot row
            snapshot = build_snapshot_row(raw_offers, origin, dest, departure_date, config)

            if snapshot is None:
                errors.append(f"{origin}-{dest} {days_out} days out: no valid offers")
                continue

            # Enrich with buy signal
            snapshot = enrich_snapshot_with_buy_signal(snapshot, baselines_df)

            # Log result
            buy_signal = snapshot.get("buy_signal", "unknown")
            pct = snapshot.get("pct_vs_baseline")
            if pct is not None:
                print(f"  {origin}-{dest} ({days_out}d): ${snapshot['median_fare']} ({buy_signal}, {pct:+.1f}%)")
            else:
                print(f"  {origin}-{dest} ({days_out}d): ${snapshot['median_fare']} ({buy_signal}, no baseline)")

            snapshots.append(snapshot)

    print(f"\nINFO: Collected {len(snapshots)} snapshots ({total_calls} API calls)")
    if errors:
        print(f"INFO: Errors: {len(errors)}")
        for err in errors[:5]:  # Show first 5 errors
            print(f"  - {err}")

    return snapshots


def write_snapshots_to_bigquery(config, snapshots, dry_run=False):
    """
    Write snapshots to BigQuery.

    Args:
        config: Configuration dict
        snapshots: List of snapshot rows
        dry_run: If True, don't write to storage

    Returns:
        Dict with write results.
    """
    log_step("Write Snapshots to BigQuery")

    if not snapshots:
        print("WARNING: No snapshots to write")
        return {"rows_inserted": 0, "errors": ["No snapshots"]}

    if not config.get("bq_dataset"):
        print("WARNING: BigQuery not configured, skipping write")
        return {"rows_inserted": 0, "errors": ["BigQuery not configured"]}

    if dry_run:
        print(f"[DRY RUN] Would write {len(snapshots)} rows to {config['bq_dataset']}.{config['bq_table']}")
        return {"rows_inserted": len(snapshots), "errors": []}

    # Write to BigQuery
    result = write_to_bigquery(
        config.get("bq_dataset"),
        config.get("bq_table", "fare_snapshots"),
        snapshots
    )

    return result


def check_monthly_baseline_refresh(config):
    """
    Check if we should refresh baselines this month.
    Runs on the 1st of each month.

    Args:
        config: Configuration dict

    Returns:
        True if baselines should be refreshed.
    """
    today = date.today()
    if today.day == 1:
        print(f"INFO: Day 1 of month - checking baseline refresh")
        return True
    return False


def main(dry_run=True, force_baseline_refresh=False):
    """
    Main pipeline entry point.

    Args:
        dry_run: If True, don't write to S3/BigQuery
        force_baseline_refresh: If True, rebuild baselines even if they exist

    Returns:
        True on success, False if any failures occurred.
    """
    print("="*60)
    print("FLIGHT PRICE PREDICTION PIPELINE")
    print("="*60)
    print(f"Started at: {date.today().isoformat()}")
    print(f"Dry run mode: {dry_run}")
    print(f"Force baseline refresh: {force_baseline_refresh}")

    # Load configuration
    try:
        config = load_env()
        # Get top routes dynamically
        routes = get_top_routes(limit=50)
        print(f"INFO: Configuration loaded successfully")
        print(f"  Routes: {len(routes)} origin-destination pairs (top routes)")
        print(f"  Departure days: {DEPARTURE_DAYS_OUT}")
    except ValueError as e:
        print(f"ERROR: Configuration error: {e}")
        return False

    # Step 1: Load or bootstrap baselines
    baselines_df = load_or_bootstrap_baselines(config, force_baseline_refresh, routes=routes)

    if baselines_df is None or baselines_df.empty:
        print("ERROR: Failed to load or create baselines")
        return False

    # Step 2-4: Collect fare snapshots
    snapshots = collect_fare_snapshots(config, baselines_df, dry_run, routes=routes)

    if not snapshots:
        print("WARNING: No snapshots collected")
        return False

    # Step 5: Write to BigQuery
    write_result = write_snapshots_to_bigquery(config, snapshots, dry_run)

    # Summary
    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)
    print(f"Snapshots collected: {len(snapshots)}")
    print(f"API calls made: ~{len(snapshots) * 1.5:.0f} (est.)")
    print(f"Rows inserted: {write_result.get('rows_inserted', 0)}")

    if write_result.get("errors"):
        print(f"Errors: {write_result['errors']}")

    # Monthly baseline refresh
    if check_monthly_baseline_refresh(config) and not force_baseline_refresh:
        print("\n" + "="*60)
        print("NOTE: This is the 1st of the month - consider running")
        print("      with --force-baseline-refresh to update baselines")
        print("="*60)

    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Flight Price Prediction Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to S3/BigQuery")
    parser.add_argument("--prod", action="store_true", help="Run in production mode (write to storage)")
    parser.add_argument("--force-baseline-refresh", action="store_true", help="Force rebuild of baselines from BTS")

    args = parser.parse_args()

    success = main(
        dry_run=not args.prod,
        force_baseline_refresh=args.force_baseline_refresh
    )

    sys.exit(0 if success else 1)
