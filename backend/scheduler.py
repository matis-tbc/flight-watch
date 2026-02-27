import json
import os
import time
import uuid
from datetime import datetime, timezone

from amadeus import Client, ResponseError
from flask import Flask, jsonify, request
from google.cloud import firestore, storage
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
load_dotenv(os.path.join(BASE_DIR, ".env"))

from gcs_data_service_simple import gcs_data_service_simple 
from firestore_logic import db, get_tracked_flights, update_price
from sendgrid_logic import send_price_drop_email

credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if credentials_path:
    normalized_credentials_path = credentials_path.strip()
    if not os.path.isabs(normalized_credentials_path):
        normalized_credentials_path = os.path.join(BASE_DIR, normalized_credentials_path)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(normalized_credentials_path)

app = Flask(__name__)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _safe_int(raw_value, default):
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def _get_amadeus_client():
    client_id = os.getenv("AMADEUS_CLIENT_ID", "").strip()
    client_secret = os.getenv("AMADEUS_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("missing_amadeus_credentials")
    return Client(client_id=client_id, client_secret=client_secret)


def _get_storage_bucket():
    bucket_name = (
        os.getenv("INGEST_RAW_BUCKET", "").strip()
        or os.getenv("GCS_BUCKET", "").strip()
    )
    if not bucket_name:
        raise ValueError("missing_ingest_raw_bucket")
    project_id = os.getenv("GCP_PROJECT_ID", "").strip() or None
    storage_client = storage.Client(project=project_id)
    return bucket_name, storage_client.bucket(bucket_name)


def _to_document_id(raw_value):
    text = str(raw_value).strip()
    if not text:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    allowed = []
    for char in text:
        if char.isalnum() or char in ("-", "_", ".", ":"):
            allowed.append(char)
        else:
            allowed.append("_")
    return "".join(allowed).strip("_") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def extract_price(flight_record):
    """Extract numeric price from supported flight record formats."""
    raw_price = flight_record.get("price")

    # Amadeus/mock style: {"price": {"total": "299.99", "currency": "USD"}}
    if isinstance(raw_price, dict):
        raw_price = raw_price.get("total")

    # Legacy flat field fallback
    if raw_price is None:
        raw_price = flight_record.get("flight_price")

    if raw_price is None:
        return None

    try:
        return float(str(raw_price).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _is_authorized_scheduler_request():
    """Allow unauthenticated requests only when no scheduler token is configured."""
    required_token = os.getenv("SCHEDULER_TOKEN", "").strip()
    if not required_token:
        return True

    provided_token = request.headers.get("X-Scheduler-Token", "").strip()
    return provided_token == required_token


def _normalize_departure_date(raw_value):
    if raw_value is None:
        return None

    if hasattr(raw_value, "date"):
        return raw_value.date().isoformat()

    date_text = str(raw_value).strip()
    if not date_text:
        return None
    return date_text.split("T", 1)[0]


def _normalize_target(target):
    origin = str(target.get("origin", "")).strip().upper()
    destination = str(target.get("destination", "")).strip().upper()
    departure_date = _normalize_departure_date(target.get("departure_date"))
    return_date = _normalize_departure_date(target.get("return_date"))
    adults = _safe_int(target.get("adults", 1), 1)
    if adults < 1:
        adults = 1
    travel_class = str(target.get("travel_class", "")).strip().upper() or "ECONOMY"
    route_key = f"{origin}-{destination}-{departure_date}-{travel_class}-{adults}"
    if return_date:
        route_key = f"{route_key}-{return_date}"
    return {
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date,
        "return_date": return_date,
        "adults": adults,
        "travel_class": travel_class,
        "route_key": route_key,
    }


def _get_targets_from_firestore():
    targets = {}
    for doc in get_tracked_flights():
        data = doc.to_dict() or {}
        normalized = _normalize_target(data)
        if not normalized["origin"] or not normalized["destination"] or not normalized["departure_date"]:
            continue
        targets[normalized["route_key"]] = normalized
    return list(targets.values())


def _get_targets_from_request():
    payload = request.get_json(silent=True) or {}
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        return None
    normalized_targets = []
    for target in raw_targets:
        if not isinstance(target, dict):
            continue
        normalized = _normalize_target(target)
        if normalized["origin"] and normalized["destination"] and normalized["departure_date"]:
            normalized_targets.append(normalized)
    return normalized_targets


def _fetch_flight_offers_with_retry(amadeus_client, target):
    max_retries = _safe_int(os.getenv("INGEST_MAX_RETRIES", "3"), 3)
    max_retries = max(0, max_retries)
    max_offers = _safe_int(os.getenv("INGEST_MAX_OFFERS", "20"), 20)
    max_offers = min(max(max_offers, 1), 250)
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            params = {
                "originLocationCode": target["origin"],
                "destinationLocationCode": target["destination"],
                "departureDate": target["departure_date"],
                "adults": target["adults"],
                "travelClass": target["travel_class"],
                "currencyCode": "USD",
                "max": max_offers,
            }
            if target["return_date"]:
                params["returnDate"] = target["return_date"]
            response = amadeus_client.shopping.flight_offers_search.get(**params)
            return response.data
        except ResponseError as error:
            last_error = error
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            status_code = _safe_int(status_code, 500)
            is_transient = status_code == 429 or status_code >= 500
            if attempt >= max_retries or not is_transient:
                raise
            time.sleep(min(2 ** attempt, 10))
        except Exception as error:
            last_error = error
            if attempt >= max_retries:
                raise
            time.sleep(min(2 ** attempt, 10))
    if last_error:
        raise last_error
    return []


def _extract_price(offer):
    if not isinstance(offer, dict):
        return None
    price = offer.get("price") or {}
    total = price.get("total")
    if total is None:
        return None
    try:
        return float(str(total).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _build_snapshot(target, offers, fetched_at, ingest_run_id, raw_gs_uri):
    prices = [price for price in (_extract_price(offer) for offer in offers) if price is not None]
    lowest_price = min(prices) if prices else None
    sample_currency = "USD"
    if offers and isinstance(offers[0], dict):
        sample_currency = ((offers[0].get("price") or {}).get("currency")) or "USD"
    return {
        "route_key": target["route_key"],
        "origin": target["origin"],
        "destination": target["destination"],
        "departure_date": target["departure_date"],
        "return_date": target["return_date"],
        "travel_class": target["travel_class"],
        "adults": target["adults"],
        "offer_count": len(offers),
        "lowest_price": lowest_price,
        "currency": sample_currency,
        "fetched_at": fetched_at,
        "ingest_run_id": ingest_run_id,
        "raw_gs_uri": raw_gs_uri,
    }


def _write_ingestion_results(route_key, snapshot, history_doc_id):
    route_ref = db.collection("routes").document(route_key)
    route_ref.set(
        {
            "route_key": route_key,
            "origin": snapshot["origin"],
            "destination": snapshot["destination"],
            "departure_date": snapshot["departure_date"],
            "return_date": snapshot["return_date"],
            "travel_class": snapshot["travel_class"],
            "adults": snapshot["adults"],
            "latest": snapshot,
            "last_ingested_at": snapshot["fetched_at"],
            "last_ingest_run_id": snapshot["ingest_run_id"],
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    route_ref.collection("history").document(history_doc_id).set(
        {
            **snapshot,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


def _upload_raw_payload(bucket, route_key, ingest_run_id, fetched_at, payload):
    ingest_raw_prefix = os.getenv("INGEST_RAW_PREFIX", "raw").strip().strip("/")
    day_partition = fetched_at.split("T", 1)[0].replace("-", "/")
    object_name = f"{ingest_raw_prefix}/{day_partition}/{ingest_run_id}/{route_key}.json"
    blob = bucket.blob(object_name)
    blob.upload_from_string(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
        content_type="application/json",
    )
    return object_name


@app.route("/check-prices", methods=["POST"])
def check_prices():
    if not _is_authorized_scheduler_request():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    summary = {
        "ok": True,
        "processed_tracks": 0,
        "updated_tracks": 0,
        "drops_detected": 0,
        "emails_sent": 0,
        "skipped_incomplete_track": 0,
        "skipped_no_flights": 0,
        "skipped_invalid_price": 0,
        "track_errors": 0,
        "email_errors": 0,
    }

    try:
        tracked_docs = get_tracked_flights()

        for doc in tracked_docs:
            summary["processed_tracks"] += 1
            try:
                data = doc.to_dict() or {}

                origin = data.get("origin")
                destination = data.get("destination")
                departure_date = _normalize_departure_date(data.get("departure_date"))
                user_email = data.get("user_email")
                previous_price = extract_price({"price": data.get("latest_price")})

                if not origin or not destination or not departure_date:
                    summary["skipped_incomplete_track"] += 1
                    continue

                flights = gcs_data_service_simple.search_flights(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    limit=1
                )

                if not flights:
                    summary["skipped_no_flights"] += 1
                    continue

                latest_price = extract_price(flights[0])
                if latest_price is None:
                    summary["skipped_invalid_price"] += 1
                    continue

                # PRICE DROP DETECTED
                if previous_price is not None and latest_price < previous_price:
                    summary["drops_detected"] += 1
                    if user_email:
                        flight_info = f"{origin} -> {destination} on {departure_date}"
                        try:
                            send_price_drop_email(
                                user_email,
                                flight_info,
                                previous_price,
                                latest_price
                            )
                            summary["emails_sent"] += 1
                        except Exception as email_error:
                            summary["email_errors"] += 1
                            print(f"EMAIL_ERROR for {user_email}: {email_error}")

                update_price(doc.reference, latest_price)
                summary["updated_tracks"] += 1
            except Exception as track_error:
                summary["track_errors"] += 1
                print(f"TRACK_ERROR doc={doc.id}: {track_error}")

        print(f"SCHEDULER_RUN_SUMMARY: {summary}")
        return jsonify(summary), 200

    except Exception as e:
        print("SCHEDULER_FATAL_ERROR:", e)
        return jsonify({"ok": False, "error": "internal_server_error"}), 500


@app.route("/internal/ingest", methods=["POST"])
def ingest_flights():
    if not _is_authorized_scheduler_request():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        amadeus_client = _get_amadeus_client()
        bucket_name, bucket = _get_storage_bucket()
    except ValueError as config_error:
        return jsonify({"ok": False, "error": str(config_error)}), 500
    except Exception as client_error:
        print(f"INGEST_CLIENT_INIT_ERROR: {client_error}")
        return jsonify({"ok": False, "error": "ingest_client_init_failed"}), 500

    request_targets = _get_targets_from_request()
    targets = request_targets if request_targets is not None else _get_targets_from_firestore()
    if not targets:
        return jsonify({"ok": True, "message": "no_targets_to_ingest", "processed_routes": 0}), 200

    requested_run_id = (request.get_json(silent=True) or {}).get("ingest_run_id")
    schedule_time_header = request.headers.get("X-CloudScheduler-ScheduleTime", "").strip()
    ingest_run_id = _to_document_id(
        requested_run_id
        or schedule_time_header
        or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    )

    summary = {
        "ok": True,
        "ingest_run_id": ingest_run_id,
        "processed_routes": 0,
        "raw_saved": 0,
        "routes_upserted": 0,
        "errors": 0,
        "error_details": [],
    }

    for target in targets:
        summary["processed_routes"] += 1
        route_key = target["route_key"]
        fetched_at = _utc_now_iso()

        try:
            offers = _fetch_flight_offers_with_retry(amadeus_client, target)

            raw_payload = {
                "ingest_run_id": ingest_run_id,
                "fetched_at": fetched_at,
                "route": target,
                "offer_count": len(offers),
                "offers": offers,
            }
            raw_object_name = _upload_raw_payload(
                bucket=bucket,
                route_key=route_key,
                ingest_run_id=ingest_run_id,
                fetched_at=fetched_at,
                payload=raw_payload,
            )
            summary["raw_saved"] += 1
            raw_gs_uri = f"gs://{bucket_name}/{raw_object_name}"

            snapshot = _build_snapshot(
                target=target,
                offers=offers,
                fetched_at=fetched_at,
                ingest_run_id=ingest_run_id,
                raw_gs_uri=raw_gs_uri,
            )
            _write_ingestion_results(
                route_key=route_key,
                snapshot=snapshot,
                history_doc_id=ingest_run_id,
            )
            summary["routes_upserted"] += 1
            print(
                f"INGEST_ROUTE_OK route={route_key} offers={len(offers)} "
                f"lowest_price={snapshot['lowest_price']} raw={raw_gs_uri}"
            )
        except Exception as route_error:
            summary["ok"] = False
            summary["errors"] += 1
            summary["error_details"].append({"route_key": route_key, "error": str(route_error)})
            print(f"INGEST_ROUTE_ERROR route={route_key} error={route_error}")

    status_code = 200 if summary["ok"] else 500
    print(f"INGEST_RUN_SUMMARY: {summary}")
    return jsonify(summary), status_code


@app.route("/", methods=["GET"])
def health():
    return "Flight Price Tracker Running", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
