#!/usr/bin/env python3
"""flightwatch api - gcs support, no pandas, python 3.13"""
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from html import escape
import copy
import os
import sys
from typing import Optional, List, Dict, Any
from datetime import datetime
from firestore_logic import (
    FirestoreConfigurationError,
    disable_notifications_for_email,
    delete_tracked_flight,
    get_tracked_flights,
    create_tracked_flight,
    db,
)
from gcp_auth import resolve_google_application_credentials
from date_utils import normalize_date_text
from unsubscribe_tokens import is_valid_unsubscribe_token
import uvicorn

BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))


resolve_google_application_credentials()


def _first_existing_path(*candidates: str) -> str:
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


FLIGHT_FETCH_DIR = _first_existing_path(
    os.path.abspath(os.path.join(BASE_DIR, "..", "scripts", "flight_fetch")),
    os.path.abspath(os.path.join(BASE_DIR, "scripts", "flight_fetch")),
)
if FLIGHT_FETCH_DIR not in sys.path:
    sys.path.append(FLIGHT_FETCH_DIR)

FRONTEND_DIR = _first_existing_path(
    os.path.abspath(os.path.join(BASE_DIR, "..", "frontend")),
    os.path.abspath(os.path.join(BASE_DIR, "frontend")),
)

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

app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


@app.exception_handler(FirestoreConfigurationError)
async def firestore_configuration_error_handler(_, exc: FirestoreConfigurationError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/unsubscribe", include_in_schema=False, response_class=HTMLResponse)
async def unsubscribe(email: str = "", token: str = ""):
    normalized_email = str(email or "").strip().lower()
    if not normalized_email or not token:
        return HTMLResponse(
            status_code=400,
            content="""
            <html><body style="font-family: Arial, sans-serif; padding: 32px;">
              <h2>Invalid unsubscribe link</h2>
              <p>This link is missing the information needed to process your request.</p>
            </body></html>
            """,
        )

    if not is_valid_unsubscribe_token(normalized_email, token):
        return HTMLResponse(
            status_code=400,
            content="""
            <html><body style="font-family: Arial, sans-serif; padding: 32px;">
              <h2>Invalid unsubscribe link</h2>
              <p>This unsubscribe link is not valid. Please use the latest email you received.</p>
            </body></html>
            """,
        )

    updated_count = disable_notifications_for_email(normalized_email)
    track_label = "flight alert" if updated_count == 1 else "flight alerts"
    safe_email = escape(normalized_email)
    return HTMLResponse(
        content=f"""
        <html><body style="font-family: Arial, sans-serif; padding: 32px;">
          <h2>Unsubscribed</h2>
          <p>Email alerts have been turned off for <strong>{safe_email}</strong>.</p>
          <p>Updated {updated_count} tracked {track_label}.</p>
        </body></html>
        """
    )

def check_amadeus_configured() -> bool:
    """check amadeus api config"""
    return (
        os.environ.get('AMADEUS_CLIENT_ID') is not None and
        os.environ.get('AMADEUS_CLIENT_SECRET') is not None
    )

def check_gcs_configured() -> bool:
    """check gcs config"""
    return GCS_AVAILABLE and gcs_data_service_simple.is_configured()


def _get_admin_token() -> str:
    return os.getenv("ADMIN_TOKEN", "").strip()


def _validate_admin_token(raw_token: Optional[str]) -> bool:
    expected = _get_admin_token()
    return bool(expected and raw_token and raw_token.strip() == expected)


def _require_admin_token(raw_token: Optional[str]) -> None:
    if not _validate_admin_token(raw_token):
        raise HTTPException(status_code=401, detail="Valid admin token required.")


def _group_tracks_by_route(track_docs, include_admin_fields: bool = False) -> List[Dict[str, Any]]:
    grouped: Dict[tuple, Dict[str, Any]] = {}

    for doc in track_docs:
        track_data = doc.to_dict() or {}
        key = (
            track_data.get("origin"),
            track_data.get("destination"),
            track_data.get("departure_date"),
        )
        if key not in grouped:
            grouped[key] = {
                "origin": track_data.get("origin"),
                "destination": track_data.get("destination"),
                "departure_date": track_data.get("departure_date"),
                "subscriber_count": 0,
            }
            if include_admin_fields:
                grouped[key]["track_ids"] = []
                grouped[key]["subscribers"] = []

        grouped[key]["subscriber_count"] += 1
        if include_admin_fields:
            grouped[key]["track_ids"].append(doc.id)
            grouped[key]["subscribers"].append({
                "id": doc.id,
                "user_email": track_data.get("user_email"),
                "latest_price": track_data.get("latest_price"),
                "adults": track_data.get("adults", 1),
            })

    grouped_routes = sorted(
        grouped.values(),
        key=lambda item: (
            item.get("departure_date") or "",
            item.get("origin") or "",
            item.get("destination") or "",
        ),
    )
    return grouped_routes


def _normalize_passenger_count(passengers: int) -> int:
    try:
        return max(int(passengers), 1)
    except (TypeError, ValueError):
        return 1


def _scale_price_value(raw_value: Any, passengers: int) -> Any:
    if raw_value is None:
        return None
    try:
        scaled = float(str(raw_value).replace(",", "").strip()) * passengers
    except (TypeError, ValueError):
        return raw_value
    return f"{scaled:.2f}"


def _scale_flight_prices(flights: List[Dict[str, Any]], passengers: int) -> List[Dict[str, Any]]:
    passenger_count = _normalize_passenger_count(passengers)
    if passenger_count == 1:
        return flights

    scaled_flights: List[Dict[str, Any]] = []
    for flight in flights:
        scaled = dict(flight)

        if isinstance(flight.get("price"), dict):
            scaled_price = dict(flight["price"])
            scaled_total = _scale_price_value(scaled_price.get("total"), passenger_count)
            if scaled_total is not None:
                scaled_price["total"] = scaled_total
            scaled["price"] = scaled_price

        for field_name in ("total_price", "flight_price"):
            if field_name in flight:
                scaled[field_name] = _scale_price_value(flight.get(field_name), passenger_count)

        scaled["passengers"] = passenger_count
        scaled_flights.append(scaled)

    return scaled_flights

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

@app.get("/api/data-range")
async def data_range():
    """Return the date range of available flight data."""
    if not check_gcs_configured():
        return {"error": "GCS not configured", "earliest_date": None, "latest_date": None, "record_count": 0}
    result = gcs_data_service_simple.get_date_range()
    if not result:
        return {"earliest_date": None, "latest_date": None, "record_count": 0}
    return result

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
    passengers = _normalize_passenger_count(passengers)
    actual_departure_date = normalize_date_text(departure_date)
    normalized_return_date = normalize_date_text(return_date)
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
                scaled_flights = _scale_flight_prices(flights, passengers)
                # Detect if date fallback was used (flights don't match requested date)
                date_note = None
                first_dt = gcs_data_service_simple._get_field(flights[0], 'departure_datetime', 'departure_date', 'date', 'departure')[:10] if flights else ""
                if first_dt and not first_dt.startswith(actual_departure_date):
                    dr = gcs_data_service_simple.get_date_range()
                    range_str = f"{dr['earliest_date']} to {dr['latest_date']}" if dr else "available dates"
                    date_note = f"Showing closest available flights (data covers {range_str})"

                result = {
                    "origin": origin,
                    "destination": destination,
                    "departure_date": actual_departure_date,
                    "return_date": normalized_return_date,
                    "passengers": passengers,
                    "flights": scaled_flights[:limit],
                    "source": "gcs",
                    "count": len(flights),
                    "status": "success: gcs flight data",
                    "note": f"found {len(flights)} flights from gcs"
                }
                if passengers > 1:
                    result["pricing_basis"] = "scaled_from_single_passenger_dataset"
                if date_note:
                    result["date_note"] = date_note
                return result
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
                normalized_return_date,
                passengers
            )
            
            flight_count = len(flight_data) if flight_data else 0
            
            return {
                "origin": origin,
                "destination": destination,
                "departure_date": actual_departure_date,
                "return_date": normalized_return_date,
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
        "return_date": normalized_return_date,
        "passengers": passengers,
        "flights": _scale_flight_prices(get_mock_flights(origin, destination, actual_departure_date), passengers)[:limit],
        "source": "mock",
        "status": "WARNING: Using mock data",
        "note": "⚠️ Configure GCS or Amadeus for real flight data",
        "pricing_basis": "scaled_from_single_passenger_mock_data" if passengers > 1 else "single_passenger_mock_data"
    }

@app.get("/api/explore")
async def explore_destinations(
    origin: str,
    max_price: float = Query(..., gt=0),
    departure_date: Optional[str] = Query(None),
):
    """Budget Explorer: find all destinations reachable from an origin within a price."""
    origin = origin.strip().upper()
    normalized_departure_date = normalize_date_text(departure_date)

    if GCS_AVAILABLE and gcs_data_service_simple.is_configured():
        destinations = gcs_data_service_simple.explore_destinations(
            origin=origin,
            max_price=max_price,
            departure_date=normalized_departure_date,
        )
        return {
            "origin": origin,
            "max_price": max_price,
            "departure_date": normalized_departure_date,
            "destination_count": len(destinations),
            "destinations": destinations,
            "source": "gcs",
        }

    # Mock fallback
    return {
        "origin": origin,
        "max_price": max_price,
        "departure_date": normalized_departure_date,
        "destination_count": 3,
        "destinations": [
            {"destination": "LAX", "cheapest_price": 132.99, "currency": "USD", "airline": "B6", "flight_count": 8, "sample_flight": {}},
            {"destination": "MIA", "cheapest_price": 189.50, "currency": "USD", "airline": "AA", "flight_count": 5, "sample_flight": {}},
            {"destination": "ORD", "cheapest_price": 95.00, "currency": "USD", "airline": "UA", "flight_count": 12, "sample_flight": {}},
        ],
        "source": "mock",
    }


@app.post("/api/tracks")
async def create_track(
    origin: str,
    destination: str,
    departure_date: str,
    user_email: str,                      # required — scheduler needs this to send emails
    passengers: int = 1,
    return_date: Optional[str] = None,
    max_price: Optional[float] = None,
):
    """
    Track a flight — saves to Firestore so the scheduler can monitor it.
    The current price from GCS is fetched and stored as the baseline.
    When the scheduler runs and detects a lower price, it emails user_email.
    """
    if not user_email:
        raise HTTPException(status_code=400, detail="user_email is required to receive price drop alerts.")

    normalized_departure_date = normalize_date_text(departure_date)
    normalized_return_date = normalize_date_text(return_date)
    if not normalized_departure_date:
        raise HTTPException(status_code=400, detail="departure_date is required.")
    passengers = _normalize_passenger_count(passengers)

    # Best-effort baseline lookup; tracking should still work even if pricing data is unavailable.
    flights = []
    if check_gcs_configured():
        try:
            flights = gcs_data_service_simple.search_flights(
                origin=origin,
                destination=destination,
                departure_date=normalized_departure_date,
                limit=1,
            )
        except Exception as exc:
            print(f"track baseline lookup error: {exc}")

    latest_price = None
    if flights:
        raw = flights[0].get("price")
        if isinstance(raw, dict):
            raw = raw.get("total")
        if raw is None:
            raw = flights[0].get("total_price") or flights[0].get("flight_price")
        try:
            latest_price = float(str(raw).replace(",", "").strip()) * passengers if raw else None
        except (TypeError, ValueError):
            latest_price = None

    doc_id = create_tracked_flight(
        user_email=user_email,
        origin=origin,
        destination=destination,
        departure_date=normalized_departure_date,
        latest_price=latest_price,
        adults=passengers,
        return_date=normalized_return_date,
    )

    return {
        "message": "Flight is now being tracked. You'll be emailed if the price drops.",
        "doc_id": doc_id,
        "user_email": user_email,
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": normalized_departure_date,
        "return_date": normalized_return_date,
        "passengers": passengers,
        "baseline_price": latest_price,
    }

@app.get("/api/tracks")
async def list_tracks(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    """List tracked routes, with admin controls only when a valid admin token is supplied."""
    is_admin = False
    if x_admin_token is not None:
        _require_admin_token(x_admin_token)
        is_admin = True

    track_docs = list(get_tracked_flights())
    tracks = _group_tracks_by_route(track_docs, include_admin_fields=is_admin)

    return {
        "count": len(track_docs),
        "route_count": len(tracks),
        "tracks": tracks,
        "admin_view": is_admin,
    }


@app.get("/api/tracks/details")
async def track_details(
    origin: str,
    destination: str,
    departure_date: str,
    track_ids: Optional[str] = Query(None),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """Return per-subscriber tracked-flight records for a specific route."""
    _require_admin_token(x_admin_token)
    normalized_departure_date = normalize_date_text(departure_date) or departure_date
    requested_track_ids = {
        part.strip() for part in str(track_ids or "").split(",")
        if part and part.strip()
    }

    details = []
    for doc in get_tracked_flights():
        track_data = doc.to_dict() or {}
        stored_departure_date = normalize_date_text(track_data.get("departure_date")) or (track_data.get("departure_date") or "")
        matches_route = (
            (track_data.get("origin") or "").strip().upper() == origin.strip().upper()
            and (track_data.get("destination") or "").strip().upper() == destination.strip().upper()
            and stored_departure_date == normalized_departure_date
        )
        matches_track_id = bool(requested_track_ids) and doc.id in requested_track_ids

        if matches_track_id or matches_route:
            details.append({
                "id": doc.id,
                "user_email": track_data.get("user_email"),
                "origin": track_data.get("origin"),
                "destination": track_data.get("destination"),
                "departure_date": track_data.get("departure_date"),
                "latest_price": track_data.get("latest_price"),
                "adults": track_data.get("adults", 1),
            })

    return {
        "count": len(details),
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": normalized_departure_date,
        "tracks": details,
    }

@app.get("/api/tracks/{track_id}")
async def get_track(track_id: str, x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    """Get a specific track by Firestore doc ID"""
    _require_admin_token(x_admin_token)
    doc = db.collection("tracked_flights").document(track_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")
    track_data = doc.to_dict()
    track_data["id"] = doc.id
    return track_data

@app.delete("/api/tracks/{track_id}")
async def delete_track(track_id: str, x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")):
    """Delete a track from Firestore"""
    _require_admin_token(x_admin_token)
    doc = db.collection("tracked_flights").document(track_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")
    delete_tracked_flight(track_id)
    return {"message": f"Track {track_id} deleted"}

@app.post("/api/predict")
async def predict_price(payload: dict):
    """
    Purchase guidance using GCS route baselines when available,
    falling back to a time-based heuristic.
    """
    best = float(payload.get("current_best_price") or 0)
    avg = float(payload.get("current_avg_price") or best)
    spread = float(payload.get("current_price_spread") or 0)
    volatility = float(payload.get("volatility_score") or 0)
    days = int(payload.get("days_until_departure") or 0)
    origin = (payload.get("origin") or "").upper()
    destination = (payload.get("destination") or "").upper()

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

    # Try to get route baseline from GCS data
    baseline = None
    buy_signal = None
    pct_vs_baseline = None
    if origin and destination:
        baseline = gcs_data_service_simple.get_route_baseline(origin, destination)

    if baseline:
        median = baseline["median"]
        pct_vs_baseline = round(((best - median) / median) * 100, 1) if median > 0 else 0

        if pct_vs_baseline < -15:
            buy_signal = "great_deal"
        elif pct_vs_baseline < -5:
            buy_signal = "good_price"
        elif pct_vs_baseline <= 10:
            buy_signal = "typical"
        else:
            buy_signal = "high"

    # Time-based recommendation (enhanced with baseline when available)
    recommendation = "WATCH CLOSELY"
    confidence = 0.62
    savings_pct = 0.05
    rationale = "Prices are neither extremely compressed nor clearly falling yet, so monitoring for a better entry point is reasonable."

    if days <= 10:
        recommendation = "BUY NOW"
        confidence = 0.84
        savings_pct = 0.01
        rationale = "Departure is close, so the downside of waiting is higher than the likely savings from a short-lived dip."
    elif buy_signal == "great_deal":
        recommendation = "BUY NOW"
        confidence = 0.88
        savings_pct = 0.01
        rationale = f"This fare is {abs(pct_vs_baseline):.0f}% below the historical median for this route. This is a great deal."
    elif buy_signal == "good_price":
        recommendation = "BUY NOW"
        confidence = 0.74
        savings_pct = 0.02
        rationale = f"This fare is {abs(pct_vs_baseline):.0f}% below the historical median. A solid price worth locking in."
    elif buy_signal == "high" and days >= 14:
        recommendation = "WAIT"
        confidence = 0.72
        savings_pct = 0.10
        rationale = f"This fare is {pct_vs_baseline:.0f}% above the historical median with time before departure. Prices on this route often come down."
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

    model_status = "gcs-baseline-v1" if baseline else "python-heuristic-v1"

    result = {
        "recommendation": recommendation,
        "confidence": confidence,
        "predicted_lowest_price": predicted_lowest or best,
        "expected_dip_window": "Current fare is already attractive" if recommendation == "BUY NOW" else f"{days - 5} to {days} days out",
        "estimated_savings": estimated_savings,
        "rationale": rationale,
        "model_status": model_status,
        "price_floor": baseline["p25"] if baseline else best,
        "price_ceiling": baseline["p75"] if baseline else (best + spread),
        "current_best_price": best,
        "source_mode": "model",
    }

    if baseline:
        result["historical_median"] = baseline["median"]
        result["pct_vs_baseline"] = pct_vs_baseline
        result["buy_signal"] = buy_signal
        result["price_p25"] = baseline["p25"]
        result["price_p75"] = baseline["p75"]
        result["sample_size"] = baseline["sample_size"]

    return result


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
    print("=" * 70)
    print("flightwatch api - gcs version")
    print("=" * 70)
    print(f"python: {sys.version.split()[0]}")
    print("project: flightwatch-486618")
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
