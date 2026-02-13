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
