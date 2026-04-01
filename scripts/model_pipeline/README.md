# Flight Information Fetcher

A Python script that pulls real-time flight information from the Amadeus API.

## Features

- Search for flights between airports
- Get real-time flight status
- Retrieve flight delay information
- Support for various search parameters
- JSON and human-readable output formats
- Batch flight data collection for analysis

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Get Amadeus API credentials:
   - Sign up at [Amadeus Developer Portal](https://developers.amadeus.com/)
   - Create a new application to get your `CLIENT_ID` and `CLIENT_SECRET`

3. Set up environment variables:
   - Copy `.env.example` to `.env`
   - Fill in your actual credentials

## Usage

### Search for flights:
```bash
python flight_fetcher.py --origin JFK --destination LAX --departure-date 2023-12-01 --passengers 2
```

### Check flight status:
```bash
python flight_fetcher.py --origin JFK --destination LAX --departure-date 2023-12-01 --flight-number 1234 --airline-code AA
```

### Output in human-readable format:
```bash
python flight_fetcher.py --origin JFK --destination LAX --departure-date 2023-12-01 --output-format human
```

### Batch Flight Data Collection:
```bash
python batch_flight_collector.py
```

This will collect flight data for the upcoming month and save it to `flight_data_batch.csv` for statistical analysis and testing.

## Parameters

- `--origin`: Origin airport code (required)
- `--destination`: Destination airport code (required)
- `--departure-date`: Departure date (YYYY-MM-DD) (required)
- `--return-date`: Return date (YYYY-MM-DD)
- `--passengers`: Number of passengers (default: 1)
- `--flight-number`: Specific flight number to check status
- `--airline-code`: Airline code for flight status
- `--output-format`: Output format (json or human) (default: json)

---

# Flight Price Prediction Pipeline

A daily data pipeline that collects flight fare data from the Amadeus API, enriches it with historical BTS (Bureau of Transportation Statistics) baselines, and stores it in BigQuery for downstream ML training.

## Overview

This pipeline is designed to collect 60-90 days of enriched fare snapshots. The dataset becomes the training data for a LightGBM quantile regression model that will predict median fares 1, 3, and 7 days out with confidence intervals.

### Data Budget

- Amadeus free tier: ~2000 calls/month
- Target routes: 20 routes x 3 departure dates = 60 calls/day = 1800/month
- Departure days: 1, 3, and 7 days before departure

## File Structure

| File | Purpose |
|------|---------|
| `config.py` | Configuration: ROUTES list, constants, env loading |
| `amadeus_client.py` | Amadeus API integration with OAuth2 |
| `transform.py` | Transform raw offers to BigQuery schema |
| `bts_client.py` | Download and cache BTS DB1B data |
| `baselines.py` | Compute baselines and buy signals |
| `storage.py` | S3 and BigQuery persistence |
| `pipeline.py` | Main orchestration script |
| `requirements.txt` | Python dependencies |

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Edit `.env` and add your credentials:

```bash
# Amadeus API
AMADEUS_CLIENT_ID=your_amadeus_client_id
AMADEUS_CLIENT_SECRET=your_amadeus_client_secret

# AWS (for S3 storage)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET=your-s3-bucket-name

# Google Cloud (for BigQuery)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
BQ_DATASET=flight_data
BQ_TABLE=fare_snapshots
```

### 3. Verify Setup

```bash
python -c "from config import load_env; print('OK')"
```

## Usage

### Dry Run (No Storage Writes)

```bash
python pipeline.py --dry-run
```

### Production Run (With Storage)

```bash
python pipeline.py --prod
```

### Force Baseline Refresh (for monthly updates)

```bash
python pipeline.py --prod --force-baseline-refresh
```

This is typically run on the 1st of each month to pick up new BTS quarters.

## Pipeline Flow

1. **Load or Bootstrap Baselines** - Load existing baselines from BigQuery or download from BTS
2. **Fetch Amadeus Offers** - For each route x departure day, fetch flight offers
3. **Store Raw JSON** - Save raw API response to S3
4. **Build Snapshot Row** - Extract fare statistics (median, min, max, carrier)
5. **Enrich with Buy Signal** - Compare to historical baseline, determine buy signal
6. **Batch Insert to BigQuery** - Write enriched rows to fare_snapshots table

## Buy Signal Logic

| Signal | Condition |
|--------|-----------|
| great_deal | >15% below historical median |
| good_price | 5-15% below historical median |
| typical | Within 10% of median |
| high | >10% above median |
| unknown | No baseline data for route/quarter |

## BTS Data Source

- Dataset: DB1B Market table from BTS TranStats
- URL: https://transtats.bts.gov/PREZIP/Origin_and_Destination_Survey_DB1BMarket_{year}_{quarter}.zip
- Cache location: `bts_cache/` directory
- Data filtering: Fares between $30-$2000 to remove outliers
