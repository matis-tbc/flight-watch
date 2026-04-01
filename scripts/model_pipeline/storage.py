#!/usr/bin/env python3
"""
Storage module for Flight Price Prediction Pipeline.
Handles S3 and BigQuery persistence.
"""

import os
from datetime import date


def write_to_s3(bucket, key, data):
    """
    Write data to S3.

    Args:
        bucket: S3 bucket name
        key: S3 object key (path)
        data: String or JSON-serializable data to write

    Returns:
        S3 URI string (s3://bucket/key) or None on failure.
    """
    if not bucket:
        print("WARNING: S3_BUCKET not configured, skipping S3 write")
        return None

    try:
        import boto3
        import json

        s3_client = boto3.client("s3")

        # Serialize data if needed
        if isinstance(data, (dict, list)):
            data = json.dumps(data, default=str)

        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType="application/json"
        )

        s3_uri = f"s3://{bucket}/{key}"
        print(f"INFO: Wrote {len(data)} bytes to {s3_uri}")
        return s3_uri

    except ImportError:
        print("WARNING: boto3 not installed, skipping S3 write")
        return None
    except Exception as e:
        print(f"ERROR: Failed to write to S3: {e}")
        return None


def write_to_bigquery(dataset, table, rows, schema=None, write_disposition="WRITE_APPEND"):
    """
    Write rows to BigQuery table.

    Args:
        dataset: BigQuery dataset name
        table: BigQuery table name
        rows: List of dicts to insert
        schema: Optional list of {'name': str, 'type': str} dicts
        write_disposition: WRITE_APPEND or WRITE_TRUNCATE

    Returns:
        Dict with insert results: {'rows_inserted': int, 'errors': list}
    """
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("WARNING: GOOGLE_APPLICATION_CREDENTIALS not set, skipping BigQuery write")
        return {"rows_inserted": 0, "errors": ["Google credentials not configured"]}

    if not dataset:
        print("WARNING: BQ_DATASET not configured, skipping BigQuery write")
        return {"rows_inserted": 0, "errors": ["Dataset not configured"]}

    try:
        from google.cloud import bigquery

        client = bigquery.Client()

        # Build full table reference
        table_ref = client.dataset(dataset).table(table)

        # Define schema if not provided (default fare_snapshots schema)
        if schema is None:
            schema = [
                bigquery.SchemaField("snapshot_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("snapshot_date", "DATE", mode="REQUIRED"),
                bigquery.SchemaField("origin", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("destination", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("departure_date", "DATE", mode="REQUIRED"),
                bigquery.SchemaField("days_to_departure", "INTEGER", mode="REQUIRED"),
                bigquery.SchemaField("carrier", "STRING"),
                bigquery.SchemaField("median_fare", "FLOAT"),
                bigquery.SchemaField("min_fare", "FLOAT"),
                bigquery.SchemaField("max_fare", "FLOAT"),
                bigquery.SchemaField("avg_fare", "FLOAT"),
                bigquery.SchemaField("currency", "STRING"),
                bigquery.SchemaField("raw_s3_key", "STRING"),
                bigquery.SchemaField("buy_signal", "STRING"),
                bigquery.SchemaField("pct_vs_baseline", "FLOAT"),
                bigquery.SchemaField("historical_median", "FLOAT"),
                bigquery.SchemaField("num_offers", "INTEGER"),
                bigquery.SchemaField("data_quality_score", "FLOAT"),
            ]

        # Create table if it doesn't exist
        try:
            client.get_table(table_ref)
        except Exception:
            print(f"INFO: Creating BigQuery table {dataset}.{table}")
            table = bigquery.Table(table_ref, schema=schema)
            client.create_table(table)

        # Insert rows
        errors = client.insert_rows_json(
            table_ref,
            rows,
            row_ids=[row.get("snapshot_id", str(id(row))) for row in rows]
        )

        if errors:
            print(f"ERROR: BigQuery insert errors: {errors}")
            return {"rows_inserted": len(rows) - len(errors), "errors": errors}
        else:
            print(f"INFO: Successfully inserted {len(rows)} rows to {dataset}.{table}")
            return {"rows_inserted": len(rows), "errors": []}

    except ImportError:
        print("WARNING: google-cloud-bigquery not installed, skipping BigQuery write")
        return {"rows_inserted": 0, "errors": ["google-cloud-bigquery not installed"]}
    except Exception as e:
        print(f"ERROR: Failed to write to BigQuery: {e}")
        return {"rows_inserted": 0, "errors": [str(e)]}


def upsert_route_baselines(dataset, table, baselines_df):
    """
    Upsert route baselines into BigQuery.

    Args:
        dataset: BigQuery dataset name
        table: BigQuery table name (default: route_baselines)
        baselines_df: pandas DataFrame with baseline statistics

    Returns:
        Dict with insert results
    """
    if baselines_df.empty:
        print("WARNING: No baseline data to upsert")
        return {"rows_inserted": 0, "errors": ["Empty dataframe"]}

    try:
        from transform import build_baseline_row
        from google.cloud import bigquery

        # Convert DataFrame to list of dicts
        rows = []
        for _, row in baselines_df.iterrows():
            rows.append(build_baseline_row(row))

        # Define schema
        schema = [
            bigquery.SchemaField("origin", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("destination", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("quarter", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("baseline_median", "FLOAT"),
            bigquery.SchemaField("baseline_mean", "FLOAT"),
            bigquery.SchemaField("baseline_std", "FLOAT"),
            bigquery.SchemaField("baseline_p25", "FLOAT"),
            bigquery.SchemaField("baseline_p75", "FLOAT"),
            bigquery.SchemaField("sample_size", "INTEGER"),
            bigquery.SchemaField("years_included", "STRING"),
        ]

        # Delete existing baselines for these routes/quarters before upsert
        unique_combinations = baselines_df.groupby(["origin", "destination", "quarter"]).size().reset_index()
        delete_conditions = []
        for _, row in unique_combinations.iterrows():
            delete_conditions.append(
                f"(origin = '{row['origin']}' AND destination = '{row['destination']}' AND quarter = '{row['quarter']}')"
            )

        if delete_conditions:
            client = bigquery.Client()
            table_ref = client.dataset(dataset).table(table)
            delete_query = f"""
                DELETE `{dataset}.{table}`
                WHERE {' OR '.join(delete_conditions)}
            """
            print(f"INFO: Deleting {len(delete_conditions)} existing baseline records")
            client.query(delete_query).result()

        # Insert new baselines
        return write_to_bigquery(dataset, table, rows, schema=schema)

    except Exception as e:
        print(f"ERROR: Failed to upsert route baselines: {e}")
        return {"rows_inserted": 0, "errors": [str(e)]}


def load_existing_baselines(dataset, table="route_baselines"):
    """
    Load existing route baselines from BigQuery.

    Args:
        dataset: BigQuery dataset name
        table: Table name (default: route_baselines)

    Returns:
        pandas DataFrame with baseline data, or None on failure.
    """
    try:
        from google.cloud import bigquery
        import pandas as pd

        client = bigquery.Client()
        table_ref = client.dataset(dataset).table(table)

        query = f"""
            SELECT *
            FROM `{dataset}.{table}`
        """
        df = client.query(query).to_dataframe()
        print(f"INFO: Loaded {len(df)} baseline records from BigQuery")
        return df

    except ImportError:
        print("WARNING: google-cloud-bigquery or pandas not installed")
        return None
    except Exception as e:
        print(f"WARNING: Could not load existing baselines: {e}")
        return None


if __name__ == "__main__":
    # Test storage functions
    print("Testing write_to_s3...")
    result = write_to_s3(
        os.environ.get("S3_BUCKET"),
        "test/test_file.json",
        {"test": "data", "timestamp": str(date.today())}
    )
    print(f"S3 result: {result}")

    print("\nTesting write_to_bigquery...")
    result = write_to_bigquery(
        os.environ.get("BQ_DATASET", "flight_data"),
        os.environ.get("BQ_TABLE", "fare_snapshots"),
        [
            {
                "snapshot_id": "test-uuid-123",
                "snapshot_date": "2026-03-25",
                "origin": "JFK",
                "destination": "LAX",
                "departure_date": "2026-04-01",
                "days_to_departure": 7,
                "median_fare": 299.99,
                "min_fare": 250.00,
                "max_fare": 350.00,
                "currency": "USD",
                "num_offers": 10,
            }
        ]
    )
    print(f"BigQuery result: {result}")
