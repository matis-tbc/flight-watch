import os
from datetime import datetime, timedelta, timezone
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

credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if credentials_path:
    normalized_credentials_path = credentials_path.strip()
    if not os.path.isabs(normalized_credentials_path):
        normalized_credentials_path = os.path.join(BASE_DIR, normalized_credentials_path)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(normalized_credentials_path)

db = firestore.Client()


def get_tracked_flights():
    """Stream all docs from tracked_flights collection.
    Called by scheduler.py /check-prices to find which users to email.
    """
    return db.collection("tracked_flights").stream()


def create_tracked_flight(
    user_email: str,
    origin: str,
    destination: str,
    departure_date: str,
    latest_price: float,
    return_date: str = None,
):
    """
    Save a new tracked flight to Firestore.
    Called by app_simple_gcs.py POST /api/tracks when a user tracks a flight.

    This is what feeds the scheduler — without docs here,
    no price checks or emails will ever run.

    Args:
        user_email:     the user who wants to be alerted
        origin:         e.g. JFK
        destination:    e.g. CDG
        departure_date: e.g. 2026-04-01
        latest_price:   the price at the time of tracking — used as baseline
                        for future price drop comparisons
        return_date:    optional, e.g. 2026-04-10
    """
    doc_data = {
        "user_email": user_email,
        "origin": origin.strip().upper(),
        "destination": destination.strip().upper(),
        "departure_date": departure_date,
        "return_date": return_date,
        "latest_price": latest_price,
        "previous_price": None,
        "last_checked": None,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    # Auto-generate doc ID
    _, doc_ref = db.collection("tracked_flights").add(doc_data)
    return doc_ref.id


def delete_tracked_flight(doc_id: str):
    """
    Remove a tracked flight from Firestore.
    Called by app_simple_gcs.py DELETE /api/tracks/{id}
    """
    db.collection("tracked_flights").document(doc_id).delete()


def get_tracked_flights_by_email(user_email: str):
    """
    Get all flights tracked by a specific user.
    Useful for showing a user their own tracked flights in the frontend.
    """
    return (
        db.collection("tracked_flights")
        .where("user_email", "==", user_email)
        .stream()
    )


def update_price(doc_ref, new_price, current_price=None):
    """
    Update price on a tracked flight doc after scheduler checks it.

    Args:
        doc_ref:       Firestore DocumentReference
        new_price:     latest price from GCS
        current_price: existing latest_price already in memory from scheduler.py
                       (optional -- if omitted, previous_price is not updated)
    """
    update_data = {
        "latest_price": new_price,
        "last_checked": firestore.SERVER_TIMESTAMP,
    }
    if current_price is not None:
        update_data["previous_price"] = current_price
    doc_ref.update(update_data)


def was_notified_recently(doc_id, within_hours=24):
    """
    Check if we already sent a notification for this tracked flight recently.
    Prevents spamming the same user about the same route.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    docs = (
        db.collection("notification_log")
        .where("doc_id", "==", doc_id)
        .where("sent_at", ">=", cutoff)
        .limit(1)
        .stream()
    )
    return any(True for _ in docs)


def log_notification_sent(doc_id, user_email, route, old_price, new_price):
    """
    Record that a price-drop email was sent, so we can deduplicate.
    """
    db.collection("notification_log").add({
        "doc_id": doc_id,
        "user_email": user_email,
        "route": route,
        "old_price": old_price,
        "new_price": new_price,
        "sent_at": datetime.now(timezone.utc),
    })
