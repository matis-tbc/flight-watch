from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.auth.exceptions import DefaultCredentialsError

from .gcp_auth import google_credentials_help, resolve_google_application_credentials
from .paths import ENV_FILE

try:
    from google.cloud import firestore
except ImportError:
    try:
        from google.cloud import firestore_v1 as firestore
    except ImportError as fallback_error:
        raise ImportError(
            "Missing Firestore dependency. Activate the backend virtual environment "
            'and install dependencies: python -m pip install -e ".[backend]"'
        ) from fallback_error

load_dotenv(ENV_FILE)
resolve_google_application_credentials()


class FirestoreConfigurationError(RuntimeError):
    """Raised when Firestore cannot be initialized in the current environment."""


_db = None


def get_db():
    global _db
    if _db is not None:
        return _db

    resolve_google_application_credentials()

    try:
        _db = firestore.Client()
    except DefaultCredentialsError as error:
        raise FirestoreConfigurationError(
            google_credentials_help("Firestore")
        ) from error

    return _db


class _LazyFirestoreClient:
    def __getattr__(self, attr_name):
        return getattr(get_db(), attr_name)


db = _LazyFirestoreClient()


def get_tracked_flights():
    return get_db().collection("tracked_flights").stream()


def create_tracked_flight(
    user_email: str,
    origin: str,
    destination: str,
    departure_date: str,
    latest_price: float,
    return_date: str = None,
):
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
    _, doc_ref = get_db().collection("tracked_flights").add(doc_data)
    return doc_ref.id


def delete_tracked_flight(doc_id: str):
    get_db().collection("tracked_flights").document(doc_id).delete()


def get_tracked_flights_by_email(user_email: str):
    return (
        get_db().collection("tracked_flights")
        .where("user_email", "==", user_email)
        .stream()
    )


def update_price(doc_ref, new_price, current_price=None):
    update_data = {
        "latest_price": new_price,
        "last_checked": firestore.SERVER_TIMESTAMP,
    }
    if current_price is not None:
        update_data["previous_price"] = current_price
    doc_ref.update(update_data)


def was_notified_recently(doc_id, within_hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    docs = (
        get_db().collection("notification_log")
        .where("doc_id", "==", doc_id)
        .where("sent_at", ">=", cutoff)
        .limit(1)
        .stream()
    )
    return any(True for _ in docs)


def log_notification_sent(doc_id, user_email, route, old_price, new_price):
    get_db().collection("notification_log").add({
        "doc_id": doc_id,
        "user_email": user_email,
        "route": route,
        "old_price": old_price,
        "new_price": new_price,
        "sent_at": datetime.now(timezone.utc),
    })
