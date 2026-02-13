import os
import argparse
import json
import logging
from amadeus import Client, ResponseError
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Setup logging
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('flight_fetcher.log'),
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
            'adults': passengers
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

def get_flight_status(amadeus_client, flight_number, date, airline_code):
    """Get real-time flight status"""
    try:
        # Prepare the parameters
        params = {
            'flightNumber': flight_number,
            'date': date,
            'airlineCode': airline_code
        }

        # Make the API call
        response = amadeus_client.flight_status.get(**params)

        logger.info(f"Successfully retrieved flight status for {airline_code} {flight_number}")
        return response.data

    except ResponseError as e:
        logger.error(f"Amadeus API error retrieving flight status: {e}")
        raise
    except Exception as e:
        logger.error(f"Error retrieving flight status: {e}")
        raise

def get_flight_delays(amadeus_client, flight_number, date, airline_code):
    """Get flight delay information"""
    try:
        # Prepare the parameters
        params = {
            'flightNumber': flight_number,
            'date': date,
            'airlineCode': airline_code
        }

        # Make the API call
        response = amadeus_client.flight_delays.get(**params)

        logger.info(f"Successfully retrieved flight delay information for {airline_code} {flight_number}")
        return response.data

    except ResponseError as e:
        logger.error(f"Amadeus API error retrieving flight delays: {e}")
        raise
    except Exception as e:
        logger.error(f"Error retrieving flight delays: {e}")
        raise

def format_flight_data(flight_data):
    """Format flight data for output"""
    if not flight_data:
        return "No flight data available"

    formatted_data = []

    # Handle different data structures
    if isinstance(flight_data, list):
        for flight in flight_data:
            formatted_flight = {
                'id': flight.get('id'),
                'itineraries': flight.get('itineraries', []),
                'price': flight.get('price', {}),
                'validatingAirlineCodes': flight.get('validatingAirlineCodes', [])
            }
            formatted_data.append(formatted_flight)
    else:
        formatted_data = flight_data

    return formatted_data

def main():
    """Main function to parse arguments and orchestrate the script"""
    parser = argparse.ArgumentParser(description='Fetch real-time flight information from Amadeus API')
    parser.add_argument('--origin', required=True, help='Origin airport code (e.g., JFK)')
    parser.add_argument('--destination', required=True, help='Destination airport code (e.g., LAX)')
    parser.add_argument('--departure-date', required=True, help='Departure date (YYYY-MM-DD)')
    parser.add_argument('--return-date', help='Return date (YYYY-MM-DD)')
    parser.add_argument('--passengers', type=int, default=1, help='Number of passengers')
    parser.add_argument('--flight-number', help='Specific flight number to check status')
    parser.add_argument('--airline-code', help='Airline code for flight status')
    parser.add_argument('--output-format', choices=['json', 'human'], default='json', help='Output format')

    args = parser.parse_args()

    try:
        # Authenticate with Amadeus
        amadeus = authenticate_amadeus()

        # If flight number is provided, get flight status and delays
        if args.flight_number and args.airline_code:
            logger.info(f"Checking status for flight {args.airline_code} {args.flight_number}")

            # Get flight status
            status_data = get_flight_status(amadeus, args.flight_number, args.departure_date, args.airline_code)

            # Get flight delays
            delay_data = get_flight_delays(amadeus, args.flight_number, args.departure_date, args.airline_code)

            # Format and output the data
            if args.output_format == 'json':
                output_data = {
                    'status': status_data,
                    'delays': delay_data
                }
                print(json.dumps(output_data, indent=2, default=str))
            else:
                print(f"Flight Status for {args.airline_code} {args.flight_number}:")
                print(json.dumps(status_data, indent=2, default=str))
                print("\nFlight Delays:")
                print(json.dumps(delay_data, indent=2, default=str))

        else:
            # Search for flights
            logger.info(f"Searching flights from {args.origin} to {args.destination}")

            flight_data = search_flights(
                amadeus,
                args.origin,
                args.destination,
                args.departure_date,
                args.return_date,
                args.passengers
            )

            # Format and output the data
            formatted_data = format_flight_data(flight_data)

            if args.output_format == 'json':
                print(json.dumps(formatted_data, indent=2, default=str))
            else:
                print("Flight Search Results:")
                for flight in formatted_data:
                    print(f"Flight ID: {flight.get('id')}")
                    print(f"Price: {flight.get('price', {}).get('total', 'N/A')}")
                    print("---")

    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise

if __name__ == "__main__":
    main()