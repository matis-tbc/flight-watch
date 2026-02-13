#!/usr/bin/env python3
"""
Test script for Amadeus API integration
"""
import requests
import json
from datetime import datetime, timedelta
import re

# Configuration
AMADEUS_API_KEY = "0OxWE9KGp4X4A6hS14oS6P7AWFR9V9tD"
AMADEUS_API_SECRET = "DTUdW1a1UzmJDAzR"
BASE_URL = "https://test.api.amadeus.com"

def get_access_token():
    """Get access token from Amadeus API"""
    url = f"{BASE_URL}/v1/security/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET
    }

    response = requests.post(url, headers=headers, data=data)
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"Error getting token: {response.status_code} - {response.text}")
        return None

def search_flights(origin, destination, departure_date):
    """Search for flights between origin and destination"""
    token = get_access_token()
    if not token:
        return None

    url = f"{BASE_URL}/v2/shopping/flight-offers"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": 1,
        "max": 10
    }

    print(f"Searching flights from {origin} to {destination} on {departure_date}")
    print(f"URL: {url}")
    print(f"Parameters: {params}")

    response = requests.get(url, headers=headers, params=params)
    print(f"Response Status: {response.status_code}")

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

def main():
    # Use today's date or a date that's definitely in the future
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    test_cases = [
        ("ORD", "JFK", tomorrow),      # Tomorrow
        ("JFK", "LAX", next_week),      # Next week
        ("LHR", "JFK", next_week),      # Next week
    ]

    for i, (origin, destination, date) in enumerate(test_cases, 1):
        print(f"\n=== Test Case {i} ===")
        print(f"Searching from {origin} to {destination} on {date}")

        flights = search_flights(origin, destination, date)

        if flights and "data" in flights:
            print(f"✓ Found {len(flights['data'])} flights:")
            for flight in flights["data"][:3]:  # Show first 3 flights
                price = flight.get("price", {}).get("total", "N/A")
                print(f"  Price: ${price}")
        else:
            print("✗ No flights found or error occurred")

if __name__ == "__main__":
    main()