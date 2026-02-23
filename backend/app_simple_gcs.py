#!/usr/bin/env python3
"""flightwatch api - gcs support, no pandas, python 3.13"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import sys
from typing import Optional, List, Dict, Any
from datetime import datetime

load_dotenv()
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tracks_db = []
track_id_counter = 1

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
    return_date: Optional[str] = None,
    max_price: Optional[float] = None,
    notification_email: Optional[str] = None
):
    """Create a new flight price tracking"""
    global track_id_counter
    
    track = {
        "id": track_id_counter,
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "max_price": max_price,
        "notification_email": notification_email,
        "created_at": datetime.now().isoformat(),
        "status": "active",
        "price_history": []
    }
    
    tracks_db.append(track)
    track_id_counter += 1
    
    return {
        "message": "Track created successfully",
        "track": track,
        "track_id": track["id"]
    }

@app.get("/api/tracks")
async def list_tracks():
    """List all flight tracks"""
    return {
        "count": len(tracks_db),
        "tracks": tracks_db
    }

@app.get("/api/tracks/{track_id}")
async def get_track(track_id: int):
    """Get a specific track by ID"""
    for track in tracks_db:
        if track["id"] == track_id:
            return track
    
    raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

@app.delete("/api/tracks/{track_id}")
async def delete_track(track_id: int):
    """Delete a track (soft delete)"""
    for i, track in enumerate(tracks_db):
        if track["id"] == track_id:
            tracks_db[i]["status"] = "deleted"
            return {"message": f"Track {track_id} deleted"}
    
    raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

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