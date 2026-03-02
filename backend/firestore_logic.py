#!/usr/bin/env python3
"""
firestore_logic.py  — Firestore read/write layer
Consumed by: scheduler.py (/check-prices and /internal/ingest)

Firestore collections used:
  tracked_flights/   – user-saved route watches (origin, destination,
                       departure_date, user_email, latest_price)
  routes/            – per-route snapshots + history sub-collection
                       written by the ingest flow in scheduler.py
"""
import os
from datetime import datetime
from dotenv import load_dotenv

try:
    from google.cloud import firestore
except ImportError:
    try:
        from google.cloud import firestore_v1 as firestore
    except ImportError as fallback_error:
        raise ImportError(
            "Missing Firestore dependency. Activate the backend virtual environment "
            "and install requirements: pip install -r backend/requirements.txt"
        ) from fallback_error

BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ── Credentials (normalised absolute path) ────────────────────────────────────
credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if credentials_path:
    normalized = credentials_path.strip()
    if not os.path.isabs(normalized):
        normalized = os.path.join(BASE_DIR, normalized)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(normalized)

# ── Firestore client ──────────────────────────────────────────────────────────
project_id = os.getenv("GCP_PROJECT_ID", "flightwatch-486618")
db = firestore.Client(project=project_id)


# ══════════════════════════════════════════════════════════════════════════════
# tracked_flights — user-saved route watches
# Called by scheduler.py: get_tracked_flights(), update_price()
# ══════════════════════════════════════════════════════════════════════════════

def get_tracked_flights():
    """
    Return a stream of all documents in the tracked_flights collection.
    Each doc represents one user's saved route watch.

    Expected doc fields:
        origin          str   e.g. "JFK"
        destination     str   e.g. "CDG"
        departure_date  str   e.g. "2024-12-25"
        user_email      str   e.g. "alice@example.com"
        latest_price    float the last known price (updated by update_price)
    """
    return db.collection("tracked_flights").stream()


def update_price(doc_ref, new_price: float) -> None:
    """
    Shift latest_price -> previous_price, then write new_price as latest.
    Called by scheduler.py after each successful price fetch.

    Args:
        doc_ref:   Firestore DocumentReference for the tracked_flights doc
        new_price: the freshly fetched lowest price (float)
    """
    current = doc_ref.get().to_dict() or {}
    doc_ref.update({
        "previous_price": current.get("latest_price"),   # preserve old value
        "latest_price":   new_price,
        "last_checked":   firestore.SERVER_TIMESTAMP,
    })


# ══════════════════════════════════════════════════════════════════════════════
# tracked_flights — add / remove helpers
# Called by app_simple_gcs.py POST /api/tracks (to persist tracks in Firestore)
# ══════════════════════════════════════════════════════════════════════════════

def create_tracked_flight(
    origin: str,
    destination: str,
    departure_date: str,
    user_email: str = None,
    return_date: str = None,
    max_price: float = None,
    adults: int = 1,
    travel_class: str = "ECONOMY",
) -> str:
    """
    Adds a new route watch to tracked_flights.
    Returns the auto-generated Firestore document ID.
    """
    _, doc_ref = db.collection("tracked_flights").add({
        "origin":         origin.upper(),
        "destination":    destination.upper(),
        "departure_date": departure_date,
        "return_date":    return_date,
        "user_email":     user_email,
        "max_price":      max_price,
        "adults":         adults,
        "travel_class":   travel_class.upper() if travel_class else "ECONOMY",
        "latest_price":   None,
        "previous_price": None,
        "last_checked":   None,
        "created_at":     firestore.SERVER_TIMESTAMP,
        "status":         "active",
    })
    return doc_ref.id


def delete_tracked_flight(doc_id: str) -> None:
    """Soft-deletes a tracked_flights document (sets status = 'deleted')."""
    db.collection("tracked_flights").document(doc_id).update({
        "status": "deleted"
    })


def list_tracked_flights_for_email(user_email: str) -> list:
    """Return all active tracks for a given email address."""
    docs = (
        db.collection("tracked_flights")
        .where("user_email", "==", user_email)
        .where("status", "==", "active")
        .stream()
    )
    results = []
    for doc in docs:
        data = doc.to_dict() or {}
        data["doc_id"] = doc.id
        results.append(data)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# notification_log — deduplication (24 h cooldown per track)
# Called by scheduler.py before sending an email
# ══════════════════════════════════════════════════════════════════════════════

def was_notified_recently(doc_id: str, within_hours: int = 24) -> bool:
    """
    Returns True if an alert email was already sent for this tracked_flights
    doc within the last `within_hours` hours.
    Used by scheduler.py to prevent spam (see docs/scheduler-notifications.md).
    """
    from datetime import timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)

    docs = (
        db.collection("notification_log")
        .where("track_doc_id", "==", doc_id)
        .where("sent_at", ">=", cutoff)
        .limit(1)
        .stream()
    )
    return any(True for _ in docs)


def log_notification_sent(
    doc_id: str,
    user_email: str,
    route: str,
    old_price: float,
    new_price: float,
) -> None:
    """
    Records that a price-drop email was sent for this track.
    Prevents duplicate emails within 24 h (was_notified_recently uses this).
    """
    from datetime import timezone
    db.collection("notification_log").add({
        "track_doc_id": doc_id,
        "user_email":   user_email,
        "route":        route,
        "old_price":    old_price,
        "new_price":    new_price,
        "sent_at":      datetime.now(timezone.utc),
    })
