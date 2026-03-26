#!/usr/bin/env python3
"""flightwatch api - gcs support, no pandas, python 3.13"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import os
import sys
from typing import Optional, List, Dict, Any
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))

credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if credentials_path:
    normalized_credentials_path = credentials_path.strip()
    if not os.path.isabs(normalized_credentials_path):
        normalized_credentials_path = os.path.join(BASE_DIR, normalized_credentials_path)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(normalized_credentials_path)

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'flight_fetch'))

try:
    from gcs_data_service_simple import gcs_data_service_simple
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("gcs service not available - pip install google-cloud-storage")

app = FastAPI(
    title="flightwatch api",
    description="flight price tracking with gcs data",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/frontend", StaticFiles(directory="../frontend", html=True), name="frontend")

from firestore_logic import get_tracked_flights, delete_tracked_flight

def check_amadeus_configured() -> bool:
    """check amadeus api config"""
    return (
        os.environ.get('AMADEUS_CLIENT_ID') is not None and
        os.environ.get('AMADEUS_CLIENT_SECRET') is not None
    )

def check_gcs_configured() -> bool:
    """check gcs config"""
    return GCS_AVAILABLE and gcs_data_service_simple.is_configured()

@app.get("/")
async def root():
    """api info"""
    gcs_configured = check_gcs_configured()
    amadeus_configured = check_amadeus_configured()
    
    data_sources = []
    if gcs_configured:
        data_sources.append("GCS (team's stored flight data)")
    if amadeus_configured:
        data_sources.append("Amadeus API (live flight data)")
    if not data_sources:
        data_sources.append("Mock data (development only)")
    
    return {
        "message": "FlightWatch API",
        "version": "1.0.0",
        "status": "running",
        "python_version": sys.version.split()[0],
        "data_sources": data_sources,
        "project": "flightwatch-486618",
        "note": "Using pandas-free GCS reader for Python 3.13 compatibility",
        "endpoints": {
            "health": "/health",
            "search": "/api/search",
            "tracks": "/api/tracks",
            "gcs_info": "/api/gcs-info",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health():
    """health check"""
    gcs_configured = check_gcs_configured()
    amadeus_configured = check_amadeus_configured()
    
    health_info = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "FlightWatch API",
        "project": "flightwatch-486618",
        "python_version": sys.version.split()[0],
        "data_sources": {
            "gcs": {
                "configured": gcs_configured,
                "status": "READY" if gcs_configured else "NOT CONFIGURED",
                "note": "Team's stored flight data (CSV)" if gcs_configured else "Add GCS_BUCKET and GCS_FILE_PATH to .env"
            },
            "amadeus_api": {
                "configured": amadeus_configured,
                "status": "READY" if amadeus_configured else "NOT CONFIGURED",
                "note": "Live Amadeus API data" if amadeus_configured else "Add AMADEUS_CLIENT_ID/SECRET to .env"
            },
            "mock_data": {
                "available": True,
                "status": "FALLBACK",
                "note": "Used when no real data sources configured"
            }
        },
        "primary_data_source": "GCS" if gcs_configured else "Amadeus" if amadeus_configured else "Mock",
        "endpoints_working": True,
        "docs_url": "/docs"
    }
    
    # Add GCS data summary if available
    if gcs_configured and GCS_AVAILABLE:
        try:
            summary = gcs_data_service_simple.get_data_summary()
            health_info["data_sources"]["gcs"]["data_summary"] = summary
        except Exception as e:
            health_info["data_sources"]["gcs"]["error"] = str(e)
    
    return health_info

@app.get("/api/gcs-info")
async def gcs_info():
    """Get information about GCS data"""
    if not GCS_AVAILABLE:
        raise HTTPException(status_code=501, detail="GCS service not available. Install: pip install google-cloud-storage")
    
    if not gcs_data_service_simple.is_configured():
        return {
            "status": "not_configured",
            "message": "GCS not configured",
            "required": {
                "GCS_BUCKET": "Bucket name with flight data",
                "GCS_FILE_PATH": "Path to CSV file in bucket",
                "GOOGLE_APPLICATION_CREDENTIALS": "Path to service account key"
            },
            "project": "flightwatch-486618",
            "note": "Ask your team for bucket name and file path"
        }
    
    summary = gcs_data_service_simple.get_data_summary()
    origins = gcs_data_service_simple.get_available_origins()[:10]
    destinations = gcs_data_service_simple.get_available_destinations()[:10]
    
    return {
        "status": "configured",
        "project": "flightwatch-486618",
        "data_summary": summary,
        "available_origins_sample": origins,
        "available_destinations_sample": destinations,
        "total_origins": len(gcs_data_service_simple.get_available_origins()),
        "total_destinations": len(gcs_data_service_simple.get_available_destinations()),
        "sample_search": "/api/search?origin=JFK&destination=LAX&departure_date=2024-12-25"
    }

@app.get("/api/airports")
async def get_airports():
    """Get all available airports from GCS data"""
    if not GCS_AVAILABLE or not gcs_data_service_simple.is_configured():
        raise HTTPException(status_code=503, detail="GCS not configured or available")
    
    origins = gcs_data_service_simple.get_available_origins()
    destinations = gcs_data_service_simple.get_available_destinations()
    
    # Combine and deduplicate
    all_airports = sorted(set(origins + destinations))
    
    return {
        "airports": all_airports,
        "count": len(all_airports),
        "origins_count": len(origins),
        "destinations_count": len(destinations),
        "sample_origins": origins[:10],
        "sample_destinations": destinations[:10]
    }

@app.get("/api/airports/suggest")
async def suggest_airports(q: str = "", limit: int = 10):
    """Suggest airports based on query (case-insensitive partial match)"""
    if not GCS_AVAILABLE or not gcs_data_service_simple.is_configured():
        raise HTTPException(status_code=503, detail="GCS not configured or available")
    
    origins = gcs_data_service_simple.get_available_origins()
    destinations = gcs_data_service_simple.get_available_destinations()
    all_airports = sorted(set(origins + destinations))
    
    if not q:
        return {"suggestions": all_airports[:limit], "count": len(all_airports[:limit])}
    
    q_lower = q.upper()
    suggestions = [airport for airport in all_airports if q_lower in airport.upper()]
    
    return {
        "query": q,
        "suggestions": suggestions[:limit],
        "count": len(suggestions[:limit]),
        "total_matches": len(suggestions)
    }

@app.get("/api/search")
async def search_flights(
    origin: str,
    destination: str,
    departure_date: Optional[str] = Query(None),
    return_date: Optional[str] = Query(None),
    passengers: int = 1,
    limit: int = 50
):
    """search flights - gcs first, then amadeus, then mock"""
    actual_departure_date = departure_date
    if not actual_departure_date:
        from datetime import datetime
        actual_departure_date = datetime.now().strftime("%Y-%m-%d")
    
    if check_gcs_configured():
        try:
            flights = gcs_data_service_simple.search_flights(
                origin=origin,
                destination=destination,
                departure_date=actual_departure_date,
                limit=limit
            )
            
            if flights:
                return {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": actual_departure_date,
                    "return_date": return_date,
                    "passengers": passengers,
                    "flights": flights[:limit],
                    "source": "gcs",
                    "count": len(flights),
                    "status": "success: gcs flight data",
                    "note": f"found {len(flights)} flights from gcs"
                }
        except Exception as e:
            print(f"gcs search error: {e}")
    
    # Try Amadeus API
    if check_amadeus_configured():
        try:
            from flight_fetcher import search_flights as amadeus_search, authenticate_amadeus
            
            amadeus_client = authenticate_amadeus()
            flight_data = amadeus_search(
                amadeus_client,
                origin,
                destination,
                actual_departure_date,
                return_date,
                passengers
            )
            
            flight_count = len(flight_data) if flight_data else 0
            
            return {
                "origin": origin,
                "destination": destination,
                "departure_date": actual_departure_date,
                "return_date": return_date,
                "passengers": passengers,
                "flights": format_flight_data(flight_data)[:limit],
                "source": "amadeus",
                "count": flight_count,
                "status": "SUCCESS: Live Amadeus API data",
                "note": f"Found {flight_count} live flights from Amadeus API"
            }
        except Exception as e:
            print(f"Amadeus search error: {e}")
            # Fall through to mock data
    
    # Fallback to mock data
    return {
        "origin": origin,
        "destination": destination,
        "departure_date": actual_departure_date,
        "return_date": return_date,
        "passengers": passengers,
        "flights": get_mock_flights(origin, destination, actual_departure_date)[:limit],
        "source": "mock",
        "status": "WARNING: Using mock data",
        "note": "⚠️ Configure GCS or Amadeus for real flight data"
    }

@app.post("/api/tracks")
async def create_track(
    origin: str,
    destination: str,
    departure_date: str,
    user_email: str,                      # required — scheduler needs this to send emails
    return_date: Optional[str] = None,
    max_price: Optional[float] = None,
):
    """
    Track a flight — saves to Firestore so the scheduler can monitor it.
    The current price from GCS is fetched and stored as the baseline.
    When the scheduler runs and detects a lower price, it emails user_email.
    """
    from firestore_logic import create_tracked_flight

    if not user_email:
        raise HTTPException(status_code=400, detail="user_email is required to receive price drop alerts.")

    # Fetch current price from GCS to use as the baseline for future comparisons
    flights = gcs_data_service_simple.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        limit=1,
    )

    latest_price = None
    if flights:
        raw = flights[0].get("price")
        if isinstance(raw, dict):
            raw = raw.get("total")
        try:
            latest_price = float(str(raw).replace(",", "").strip()) if raw else None
        except (TypeError, ValueError):
            latest_price = None

    doc_id = create_tracked_flight(
        user_email=user_email,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        latest_price=latest_price,
        return_date=return_date,
    )

    return {
        "message": "Flight is now being tracked. You'll be emailed if the price drops.",
        "doc_id": doc_id,
        "user_email": user_email,
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date,
        "return_date": return_date,
        "baseline_price": latest_price,
    }

@app.get("/api/tracks")
async def list_tracks():
    """List all flight tracks from Firestore"""
    tracks = []
    for doc in get_tracked_flights():
        track_data = doc.to_dict()
        track_data["id"] = doc.id
        tracks.append(track_data)
    return {
        "count": len(tracks),
        "tracks": tracks
    }

@app.get("/api/tracks/{track_id}")
async def get_track(track_id: str):
    """Get a specific track by Firestore doc ID"""
    from firestore_logic import db
    doc = db.collection("tracked_flights").document(track_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")
    track_data = doc.to_dict()
    track_data["id"] = doc.id
    return track_data

@app.delete("/api/tracks/{track_id}")
async def delete_track(track_id: str):
    """Delete a track from Firestore"""
    from firestore_logic import db
    doc = db.collection("tracked_flights").document(track_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")
    delete_tracked_flight(track_id)
    return {"message": f"Track {track_id} deleted"}

@app.post("/api/predict")
async def predict_price(payload: dict):
    """
    Purchase guidance heuristic. Returns a recommendation (BUY NOW / WAIT / WATCH CLOSELY)
    based on current prices, spread, volatility, and days until departure.
    Will be replaced with a trained model later.
    """
    best = float(payload.get("current_best_price") or 0)
    avg = float(payload.get("current_avg_price") or best)
    spread = float(payload.get("current_price_spread") or 0)
    volatility = float(payload.get("volatility_score") or 0)
    days = int(payload.get("days_until_departure") or 0)

    if best <= 0:
        return {
            "recommendation": "NO DATA",
            "confidence": 0,
            "predicted_lowest_price": 0,
            "expected_dip_window": "No pricing data available",
            "estimated_savings": 0,
            "rationale": "No valid prices were found for this route. Try a different date or route.",
            "model_status": "python-heuristic-v1",
            "price_floor": 0,
            "price_ceiling": 0,
            "current_best_price": 0,
            "source_mode": "model",
        }

    recommendation = "WATCH CLOSELY"
    confidence = 0.62
    savings_pct = 0.05
    rationale = "Prices are neither extremely compressed nor clearly falling yet, so monitoring for a better entry point is reasonable."

    if days <= 10:
        recommendation = "BUY NOW"
        confidence = 0.84
        savings_pct = 0.01
        rationale = "Departure is close, so the downside of waiting is higher than the likely savings from a short-lived dip."
    elif volatility >= 0.18 and days >= 14:
        recommendation = "WAIT"
        confidence = 0.76
        savings_pct = 0.08
        rationale = "This route shows a wide fare spread and enough time before departure, which increases the odds of another softer pricing window."
    elif best <= avg * 0.92:
        recommendation = "BUY NOW"
        confidence = 0.72
        savings_pct = 0.02
        rationale = "The current best fare is already meaningfully below the route average, so it looks like a strong available deal."
    elif days <= 21:
        recommendation = "WATCH CLOSELY"
        confidence = 0.69
        savings_pct = 0.04
        rationale = "There may still be modest movement, but the departure date is approaching quickly enough that waiting should be limited."

    estimated_savings = max(0, round(min(spread * 0.45, avg * savings_pct)))
    predicted_lowest = max(0, round(best - estimated_savings))

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "predicted_lowest_price": predicted_lowest or best,
        "expected_dip_window": "Current fare is already attractive" if recommendation == "BUY NOW" else f"{days - 5} to {days} days out",
        "estimated_savings": estimated_savings,
        "rationale": rationale,
        "model_status": "python-heuristic-v1",
        "price_floor": best,
        "price_ceiling": best + spread,
        "current_best_price": best,
        "source_mode": "model",
    }


def format_flight_data(flight_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format flight data from Amadeus API for response"""
    if not flight_data:
        return []
    
    formatted = []
    for flight in flight_data:
        formatted_flight = {
            "id": flight.get('id'),
            "price": flight.get('price', {}),
            "itineraries": flight.get('itineraries', []),
            "airlines": flight.get('validatingAirlineCodes', []),
            "bookable_seats": flight.get('numberOfBookableSeats'),
            "source": "amadeus"
        }
        formatted.append(formatted_flight)
    
    return formatted

def get_mock_flights(origin: str, destination: str, departure_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """mock flight data for dev"""
    if not departure_date:
        from datetime import datetime
        departure_date = datetime.now().strftime("%Y-%m-%d")
    
    return [
        {
            "id": "mock-1",
            "airline": "American Airlines",
            "flight_number": "AA1234",
            "departure": f"{departure_date}T08:00:00",
            "arrival": f"{departure_date}T11:00:00",
            "duration": "3h",
            "price": {
                "total": "299.99",
                "currency": "USD"
            },
            "stops": 0,
            "source": "mock"
        },
        {
            "id": "mock-2",
            "airline": "Delta",
            "flight_number": "DL5678",
            "departure": f"{departure_date}T14:00:00",
            "arrival": f"{departure_date}T17:00:00",
            "duration": "3h",
            "price": {
                "total": "349.99",
                "currency": "USD"
            },
            "stops": 0,
            "source": "mock"
        }
    ]

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 70)
    print("flightwatch api - gcs version")
    print("=" * 70)
    print(f"python: {sys.version.split()[0]}")
    print(f"project: flightwatch-486618")
    print(f"gcs configured: {check_gcs_configured()}")
    print(f"amadeus configured: {check_amadeus_configured()}")
    
    if not check_gcs_configured() and not check_amadeus_configured():
        print("\nno real data sources configured")
        print("add to .env:")
        print("  GCS_BUCKET=your-bucket-name")
        print("  GCS_FILE_PATH=path/to/flight_data.csv")
        print("  GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json")
        print("\nusing mock data")
    
    print("\napi docs: http://localhost:8000/docs")
    print("health: http://localhost:8000/health")
    print("gcs info: http://localhost:8000/api/gcs-info")
    print("=" * 70)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
