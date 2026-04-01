#!/usr/bin/env python3
"""
Amadeus API client for flight fare fetching.
Handles OAuth2 authentication and fare search queries.
"""

import os
import time
import requests
from datetime import date
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Global token cache
_access_token = None
_token_expiry = 0


def get_access_token():
    """
    Get OAuth2 access token from Amadeus API.
    Caches the token and refreshes when expired.
    Returns the access token string or None on failure.
    """
    global _access_token, _token_expiry

    current_time = time.time()

    # Return cached token if still valid (refresh with 60s buffer)
    if _access_token and current_time < _token_expiry - 60:
        return _access_token

    # Get credentials
    client_id = os.environ.get("AMADEUS_CLIENT_ID")
    client_secret = os.environ.get("AMADEUS_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set")
        return None

    # Request token
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()

        token_data = response.json()
        _access_token = token_data["access_token"]
        # Set expiry to 80% of the stated expiry time
        expires_in = token_data.get("expires_in", 1740)  # Default 29 minutes
        _token_expiry = current_time + expires_in * 0.8

        print(f"INFO: Successfully obtained Amadeus access token (expires in {expires_in}s)")
        return _access_token

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to get Amadeus access token: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"ERROR: Response: {e.response.text}")
        return None


def fetch_fares(origin, dest, departure_date):
    """
    Fetch flight fares from Amadeus API for a given route and date.

    Args:
        origin: Origin airport code (e.g., 'JFK')
        dest: Destination airport code (e.g., 'LAX')
        departure_date: Departure date as date object or string (YYYY-MM-DD)

    Returns:
        Raw API response dict with 'data' and 'meta' keys, or None on failure.
    """
    # Convert date to string if needed
    if isinstance(departure_date, date):
        departure_date_str = departure_date.isoformat()
    else:
        departure_date_str = departure_date

    # Get access token
    token = get_access_token()
    if not token:
        print(f"ERROR: Failed to fetch fares for {origin}-{dest} on {departure_date_str}")
        return None

    # Build API request
    base_url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": departure_date_str,
        "adults": 1,
        "currencyCode": "USD",
        "max": 50,  # Get up to 50 offers per request
    }

    try:
        print(f"INFO: Fetching fares for {origin} -> {dest} on {departure_date_str}")
        response = requests.get(base_url, headers=headers, params=params)

        if response.status_code == 200:
            try:
                json_data = response.json()
                offer_count = len(json_data.get("data", []))
                print(f"INFO: Successfully fetched {offer_count} flight offers")
                return json_data
            except ValueError as e:
                print(f"ERROR: Failed to parse JSON response: {e}")
                return None
        elif response.status_code == 429:
            print(f"ERROR: Rate limit exceeded for {origin}-{dest}. Waiting and retrying...")
            time.sleep(60)  # Wait 60 seconds before retry
            return fetch_fares(origin, dest, departure_date_str)
        else:
            print(f"ERROR: Amadeus API returned status {response.status_code}")
            print(f"ERROR: Response: {response.text}")
            return None

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Request failed for {origin}-{dest}: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"ERROR: Response status: {e.response.status_code}")
            print(f"ERROR: Response body: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error fetching fares: {e}")
        return None


def parse_fare_response(raw_response):
    """
    Parse raw Amadeus fare response and extract relevant information.

    Args:
        raw_response: Raw API response dict from fetch_fares()

    Returns:
        List of parsed fare dictionaries with carrier, price, and cabin info.
    """
    if not raw_response or "data" not in raw_response:
        return []

    offers = raw_response.get("data", [])
    parsed_fares = []

    for offer in offers:
        try:
            price_info = offer.get("price", {})
            fare = {
                "offer_id": offer.get("id"),
                "total_price": float(price_info.get("total", 0)),
                "currency": price_info.get("currency", "USD"),
                "base_price": float(price_info.get("base", 0)),
                "taxes": float(price_info.get("taxes", 0)),
                "validating_airlines": offer.get("validatingAirlineCodes", []),
                "carriers": [],
                "cabin_class": None,
                "duration_minutes": 0,
                "segments": [],
            }

            # Extract carrier info from itineraries
            itineraries = offer.get("itineraries", [])
            for itinerary in itineraries:
                fare["duration_minutes"] = itinerary.get("duration", "PT0M")
                segments = itinerary.get("segments", [])
                for segment in segments:
                    carrier = segment.get("carrierCode", "")
                    if carrier not in fare["carriers"]:
                        fare["carriers"].append(carrier)
                    fare["segments"].append({
                        "carrier": carrier,
                        "flight_number": segment.get("number"),
                        "departure": segment.get("departure", {}).get("iataCode"),
                        "arrival": segment.get("arrival", {}).get("iataCode"),
                    })

                # Get cabin class from segments
                for segment in segments:
                    cabin = segment.get("cabin", "")
                    if cabin:
                        fare["cabin_class"] = cabin
                        break

            parsed_fares.append(fare)

        except Exception as e:
            print(f"WARNING: Failed to parse offer {offer.get('id')}: {e}")
            continue

    return parsed_fares


if __name__ == "__main__":
    # Test the client
    test_routes = [
        ("JFK", "LAX", "2026-04-01"),
        ("LAX", "JFK", "2026-04-05"),
    ]

    for origin, dest, date_str in test_routes:
        print(f"\n{'='*50}")
        print(f"Testing: {origin} -> {dest} on {date_str}")
        result = fetch_fares(origin, dest, date_str)
        if result:
            offers = result.get("data", [])
            print(f"Found {len(offers)} offers")
            if offers:
                price = offers[0].get("price", {})
                print(f"First offer: {price.get('total')} {price.get('currency')}")
        else:
            print("Failed to fetch fares")
