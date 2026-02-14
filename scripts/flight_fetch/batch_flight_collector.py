#!/usr/bin/env python3
"""
Batch flight data collector for Amadeus API
This script collects flight data for the upcoming month and saves it to a CSV file
"""

import os
import csv
import argparse
import logging
from datetime import datetime, timedelta
from amadeus import Client, ResponseError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('batch_flight_collector.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def authenticate_amadeus():
    """Initialize Amadeus client with credentials from environment variables"""
    try:
        # Get credentials from environment variables
        client_id = os.environ.get('AMADEUS_CLIENT_ID')
        client_secret = os.environ.get('AMADEUS_CLIENT_SECRET')

        if not client_id or not client_secret:
            raise ValueError("AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET environment variables must be set")

        # Initialize the Amadeus client
        amadeus = Client(
            client_id=client_id,
            client_secret=client_secret
        )

        logger.info("Successfully authenticated with Amadeus API")
        return amadeus

    except Exception as e:
        logger.error(f"Failed to authenticate with Amadeus API: {e}")
        raise

def search_flights(amadeus_client, origin, destination, departure_date, return_date=None, passengers=1):
    """Search for flights using Amadeus API"""
    try:
        # Prepare the search parameters
        params = {
            'originLocationCode': origin,
            'destinationLocationCode': destination,
            'departureDate': departure_date,
            'adults': passengers,
            'currencyCode':'USD'
        }

        if return_date:
            params['returnDate'] = return_date

        # Make the API call
        response = amadeus_client.shopping.flight_offers_search.get(**params)

        logger.info(f"Successfully retrieved flight offers for {origin} to {destination}")
        return response.data

    except ResponseError as e:
        logger.error(f"Amadeus API error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error searching flights: {e}")
        raise

def get_upcoming_month_dates():
    """Generate a list of dates for the upcoming month"""
    today = datetime.now()
    # Start from the first day of next month
    if today.month == 12:
        start_date = datetime(today.year + 1, 1, 1)
    else:
        start_date = datetime(today.year, today.month + 1, 1)

    # Generate dates for the entire month
    dates = []
    current_date = start_date

    # Add dates until we reach the end of the month
    while current_date.month == start_date.month:
        dates.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)

    return dates

def get_common_airport_pairs():
    """Define common origin-destination pairs for testing"""
    return [
        ("JFK", "LAX"),
        ("LAX", "JFK"),
        ("ORD", "LAX"),
        ("LAX", "ORD"),
        ("JFK", "LHR"),
        ("LHR", "JFK"),
        ("ORD", "JFK"),
        ("JFK", "ORD"),
        ("LAX", "LHR"),
        ("LHR", "LAX"),
        ("ATL", "DFW"),
        ("DFW", "ATL"),
        ("SFO", "LAX"),
        ("LAX", "SFO"),
    ]

def flatten_flight_data(flight_data):
    """Flatten the flight data structure for CSV export"""
    if not flight_data:
        return []

    flattened_data = []

    for flight in flight_data:
        # Get basic flight information
        flight_id = flight.get('id', '')
        price = flight.get('price', {})
        total_price = price.get('total', '')
        currency = price.get('currency', '')

        # Process itineraries
        itineraries = flight.get('itineraries', [])

        for itinerary in itineraries:
            duration = itinerary.get('duration', '')
            segments = itinerary.get('segments', [])

            for segment in segments:
                # Extract segment information
                departure = segment.get('departure', {})
                arrival = segment.get('arrival', {})

                flight_info = {
                    'flight_id': flight_id,
                    'origin': departure.get('iataCode', ''),
                    'destination': arrival.get('iataCode', ''),
                    'departure_datetime': departure.get('at', ''),
                    'arrival_datetime': arrival.get('at', ''),
                    'airline_code': segment.get('carrierCode', ''),
                    'flight_number': segment.get('number', ''),
                    'duration': duration,
                    'total_price': total_price,
                    'currency': currency,
                    'aircraft': segment.get('aircraft', {}).get('code', ''),
                    'departure_terminal': departure.get('terminal', ''),
                    'arrival_terminal': arrival.get('terminal', ''),
                }

                flattened_data.append(flight_info)

    return flattened_data

def collect_batch_flight_data():
    """Collect flight data for the upcoming month and save to CSV"""
    try:
        # Authenticate with Amadeus
        amadeus = authenticate_amadeus()

        # Get dates for upcoming month
        dates = get_upcoming_month_dates()
        logger.info(f"Collecting flight data for {len(dates)} days")

        # Get common airport pairs
        airport_pairs = get_common_airport_pairs()
        logger.info(f"Using {len(airport_pairs)} airport pairs")

        # Prepare CSV file
        output_file = 'flight_data_batch.csv'

        # Collect all flight data
        all_flight_data = []

        for date in dates:
            logger.info(f"Processing date: {date}")
            for origin, destination in airport_pairs:
                try:
                    logger.info(f"Searching flights from {origin} to {destination} on {date}")

                    # Search for flights
                    flight_data = search_flights(
                        amadeus,
                        origin,
                        destination,
                        date
                    )

                    # Flatten the data for CSV
                    flattened_data = flatten_flight_data(flight_data)

                    # Add to all data
                    all_flight_data.extend(flattened_data)

                    # Add a small delay to avoid rate limiting
                    import time
                    time.sleep(0.1)

                except Exception as e:
                    logger.error(f"Error processing {origin} to {destination} on {date}: {e}")
                    # Continue with other combinations instead of stopping
                    continue

        # Write to CSV
        if all_flight_data:
            fieldnames = all_flight_data[0].keys()

            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_flight_data)

            logger.info(f"Successfully wrote {len(all_flight_data)} flight records to {output_file}")
        else:
            logger.warning("No flight data collected")
            logger.info("Created empty CSV file")
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                if fieldnames:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()

        return all_flight_data

    except Exception as e:
        logger.error(f"Batch collection failed: {e}")
        raise

def main():
    """Main function to run the batch flight collector"""
    parser = argparse.ArgumentParser(description='Batch flight data collector for Amadeus API')
    parser.add_argument('--output-file', default='flight_data_batch.csv', help='Output CSV file name')
    parser.add_argument('--days-ahead', type=int, default=30, help='Number of days ahead to collect data (default: 30)')

    args = parser.parse_args()

    logger.info("Starting batch flight data collection")

    try:
        flight_data = collect_batch_flight_data()
        logger.info(f"Batch collection completed. Collected {len(flight_data)} flight records.")
    except Exception as e:
        logger.error(f"Batch collection failed: {e}")
        raise

if __name__ == "__main__":
    main()
