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

credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if credentials_path:
    normalized_credentials_path = credentials_path.strip()
    if not os.path.isabs(normalized_credentials_path):
        normalized_credentials_path = os.path.join(BASE_DIR, normalized_credentials_path)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(normalized_credentials_path)

db = firestore.Client()

def get_tracked_flights():
    return db.collection("tracked_flights").stream()

def update_price(doc_ref, new_price):
    doc_ref.update({
        "previous_price": doc_ref.get().to_dict().get("latest_price"),
        "latest_price": new_price,
        "last_checked": firestore.SERVER_TIMESTAMP
    })
