#!/usr/bin/env python3
"""
Baselines module for Flight Price Prediction Pipeline.
Computes and applies buy signals based on BTS historical data.
"""

from config import BUY_SIGNAL_THRESHOLDS


def compute_route_baselines(df):
    """
    Compute baseline statistics for each route and quarter.

    Args:
        df: pandas DataFrame with BTS data containing:
            - ORIGIN, DEST columns for route
            - fare column for price
            - _quarter or similar for quarter info

    Returns:
        DataFrame with baseline statistics per route/quarter.
    """
    try:
        import pandas as pd

        # Ensure quarter column exists
        if "_quarter" not in df.columns:
            df = df.copy()
            df["_quarter"] = pd.DatetimeIndex(df["FL_DATE"]).quarter

        # Group by route and quarter
        grouped = df.groupby(["ORIGIN", "DEST", "_quarter"])["fare"]

        # Compute statistics
        stats = grouped.agg(
            baseline_median="median",
            baseline_mean="mean",
            baseline_std="std",
            baseline_p25=lambda x: x.quantile(0.25),
            baseline_p75=lambda x: x.quantile(0.75),
            sample_size="count"
        ).reset_index()

        # Map quarter number to string
        quarter_mapping = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}
        stats["_quarter"] = stats["_quarter"].map(quarter_mapping)
        stats.rename(columns={"_quarter": "quarter"}, inplace=True)

        print(f"INFO: Computed baselines for {len(stats)} route/quarter combinations")
        return stats

    except Exception as e:
        print(f"ERROR: Failed to compute route baselines: {e}")
        return None


def fare_vs_baseline(fare, origin, dest, quarter, baselines_df):
    """
    Compare a current fare to historical baseline and determine buy signal.

    Args:
        fare: Current fare value (float)
        origin: Origin airport code
        dest: Destination airport code
        quarter: Quarter string (e.g., 'Q1')
        baselines_df: DataFrame with baseline statistics

    Returns:
        Dict with:
            - buy_signal: 'great_deal', 'good_price', 'typical', 'high', or 'unknown'
            - pct_vs_baseline: percentage difference from baseline median
            - historical_median: the baseline median fare
    """
    result = {
        "buy_signal": "unknown",
        "pct_vs_baseline": None,
        "historical_median": None,
    }

    # Find matching baseline
    baseline = baselines_df[
        (baselines_df["origin"] == origin) &
        (baselines_df["destination"] == dest) &
        (baselines_df["quarter"] == quarter)
    ]

    if baseline.empty:
        result["buy_signal"] = "unknown"
        return result

    # Get baseline stats
    median_fare = baseline.iloc[0]["baseline_median"]
    result["historical_median"] = round(median_fare, 2)

    # Calculate percentage difference
    if median_fare > 0:
        pct_diff = ((fare - median_fare) / median_fare) * 100
        result["pct_vs_baseline"] = round(pct_diff, 2)

        # Determine buy signal based on thresholds
        if pct_diff < BUY_SIGNAL_THRESHOLDS["great_deal"]:
            result["buy_signal"] = "great_deal"
        elif pct_diff < BUY_SIGNAL_THRESHOLDS["good_price"]:
            result["buy_signal"] = "good_price"
        elif pct_diff <= BUY_SIGNAL_THRESHOLDS["typical"]:
            result["buy_signal"] = "typical"
        else:
            result["buy_signal"] = "high"
    else:
        result["buy_signal"] = "unknown"

    return result


def enrich_snapshot_with_buy_signal(snapshot_row, baselines_df):
    """
    Enrich a snapshot row with buy signal information.

    Args:
        snapshot_row: Dict with fare snapshot data
        baselines_df: DataFrame with baseline statistics

    Returns:
        Enriched snapshot row dict.
    """
    if baselines_df is None or baselines_df.empty:
        snapshot_row["buy_signal"] = "unknown"
        snapshot_row["pct_vs_baseline"] = None
        snapshot_row["historical_median"] = None
        return snapshot_row

    fare = snapshot_row.get("median_fare")
    origin = snapshot_row.get("origin")
    dest = snapshot_row.get("destination")
    quarter = snapshot_row.get("departure_date", "")[:7]  # Extract YYYY-MM
    # Convert to quarter string
    month = int(quarter.split("-")[1])
    quarter_str = f"Q{(month - 1) // 3 + 1}"

    baseline_info = fare_vs_baseline(fare, origin, dest, quarter_str, baselines_df)

    snapshot_row["buy_signal"] = baseline_info["buy_signal"]
    snapshot_row["pct_vs_baseline"] = baseline_info["pct_vs_baseline"]
    snapshot_row["historical_median"] = baseline_info["historical_median"]

    return snapshot_row


def format_buy_signal_description(buy_signal):
    """
    Get a human-readable description of a buy signal.

    Args:
        buy_signal: Signal string from fare_vs_baseline

    Returns:
        Description string.
    """
    descriptions = {
        "great_deal": "Excellent value - significantly below historical average",
        "good_price": "Good value - below historical average",
        "typical": "Average - within normal range",
        "high": "Elevated - above historical average",
        "unknown": "Insufficient historical data",
    }
    return descriptions.get(buy_signal, "Unknown signal")


if __name__ == "__main__":
    # Test the baseline functions
    import pandas as pd

    # Create sample baselines
    sample_baselines = pd.DataFrame([
        {"origin": "JFK", "destination": "LAX", "quarter": "Q2", "baseline_median": 300.0, "baseline_mean": 320.0},
        {"origin": "LAX", "destination": "JFK", "quarter": "Q2", "baseline_median": 280.0, "baseline_mean": 300.0},
    ])

    # Test fare comparisons
    test_cases = [
        (250, "JFK", "LAX", "Q2"),   # Below median - good_deal
        (290, "JFK", "LAX", "Q2"),   # Slightly below - good_price
        (300, "JFK", "LAX", "Q2"),   # At median - typical
        (350, "JFK", "LAX", "Q2"),   # Above median - high
        (300, "SFO", "LAX", "Q2"),   # No baseline - unknown
    ]

    print("Testing fare_vs_baseline:")
    for fare, origin, dest, quarter in test_cases:
        result = fare_vs_baseline(fare, origin, dest, quarter, sample_baselines)
        print(f"  ${fare} {origin}-{dest} {quarter}: {result['buy_signal']} ({result['pct_vs_baseline']}%), median=${result['historical_median']}")

    # Test enrichment
    snapshot = {
        "snapshot_id": "test-123",
        "origin": "JFK",
        "destination": "LAX",
        "departure_date": "2026-04-15",  # Q2
        "median_fare": 275.0,
    }

    print("\nTesting enrich_snapshot_with_buy_signal:")
    enriched = enrich_snapshot_with_buy_signal(snapshot, sample_baselines)
    print(f"  Enriched: {enriched['buy_signal']} at {enriched['pct_vs_baseline']}% vs baseline")
