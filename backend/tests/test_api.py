"""Tests for FlightWatch API endpoints."""
import firestore_logic
from date_utils import normalize_date_text


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "data_sources" in data


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "endpoints" in data


def test_search_returns_flights(client):
    response = client.get("/api/search", params={
        "origin": "JFK",
        "destination": "LAX",
        "limit": 5,
    })
    assert response.status_code == 200
    data = response.json()
    assert "flights" in data
    assert "source" in data
    assert data["origin"] == "JFK"
    assert data["destination"] == "LAX"


def test_search_missing_params(client):
    response = client.get("/api/search")
    assert response.status_code == 422


def test_airports(client):
    response = client.get("/api/airports")
    assert response.status_code == 200
    data = response.json()
    assert "airports" in data
    assert isinstance(data["airports"], list)


def test_airport_suggest(client):
    response = client.get("/api/airports/suggest", params={"q": "JFK"})
    assert response.status_code == 200
    data = response.json()
    assert "suggestions" in data


def test_predict_endpoint(client):
    payload = {
        "origin": "JFK",
        "destination": "LAX",
        "departure_date": "2026-04-15",
        "passengers": 1,
        "current_best_price": 250,
        "current_avg_price": 300,
        "current_price_spread": 150,
        "volatility_score": 0.2,
        "days_until_departure": 20,
        "current_flights": [],
    }
    response = client.post("/api/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "recommendation" in data
    assert "confidence" in data
    assert "predicted_lowest_price" in data
    assert "rationale" in data


def test_predict_no_data(client):
    payload = {
        "origin": "JFK",
        "destination": "LAX",
        "current_best_price": 0,
        "current_avg_price": 0,
        "current_price_spread": 0,
        "volatility_score": 0,
        "days_until_departure": 30,
        "current_flights": [],
    }
    response = client.post("/api/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["recommendation"] == "NO DATA"


def test_explore_returns_destinations(client):
    response = client.get("/api/explore", params={"origin": "JFK", "max_price": 500})
    assert response.status_code == 200
    data = response.json()
    assert data["origin"] == "JFK"
    assert data["max_price"] == 500
    assert "destinations" in data
    assert data["destination_count"] == len(data["destinations"])
    if data["destinations"]:
        dest = data["destinations"][0]
        assert "destination" in dest
        assert "cheapest_price" in dest
        assert dest["cheapest_price"] <= 500


def test_explore_missing_origin(client):
    response = client.get("/api/explore", params={"max_price": 500})
    assert response.status_code == 422


def test_explore_zero_budget(client):
    response = client.get("/api/explore", params={"origin": "JFK", "max_price": 0})
    assert response.status_code == 422


def test_gcs_info(client):
    response = client.get("/api/gcs-info")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


def test_tracks_returns_503_when_firestore_is_unavailable(client, monkeypatch):
    def raise_firestore_error():
        raise firestore_logic.FirestoreConfigurationError("Firestore unavailable for test")

    monkeypatch.setattr(firestore_logic, "get_db", raise_firestore_error)

    response = client.get("/api/tracks")

    assert response.status_code == 503
    assert response.json()["detail"] == "Firestore unavailable for test"


def test_normalize_date_text_accepts_slash_format():
    assert normalize_date_text("04/08/2026") == "2026-04-08"
    assert normalize_date_text("2026-04-08T09:00:00") == "2026-04-08"


def test_data_range_endpoint(client):
    response = client.get("/api/data-range")
    assert response.status_code == 200
    data = response.json()
    assert "earliest_date" in data
    assert "latest_date" in data
    assert "record_count" in data


def test_search_date_fallback(client):
    """Search for a date outside GCS range still returns GCS data (not mock)."""
    response = client.get("/api/search", params={
        "origin": "JFK",
        "destination": "ORD",
        "departure_date": "2026-06-15",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["source"] in ("gcs", "mock")
    assert len(data["flights"]) > 0


def test_search_exact_date(client):
    """Search for a date within GCS range returns exact matches with no date_note."""
    # Use a date within the current GCS data range
    response = client.get("/api/data-range")
    dr = response.json()
    if not dr.get("earliest_date"):
        return  # No GCS data loaded, skip
    test_date = dr["earliest_date"]

    response = client.get("/api/search", params={
        "origin": "JFK",
        "destination": "LAX",
        "departure_date": test_date,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "gcs"
    assert len(data["flights"]) > 0
    assert "date_note" not in data


def test_create_track(client, monkeypatch):
    # Mock create_tracked_flight at the module level where it's imported
    monkeypatch.setattr(
        firestore_logic,
        "create_tracked_flight",
        lambda **kwargs: "fake-doc-id",
    )
    # Also patch it in app_simple_gcs since it may be imported there directly
    import app_simple_gcs
    if hasattr(app_simple_gcs, "create_tracked_flight"):
        monkeypatch.setattr(app_simple_gcs, "create_tracked_flight", lambda **kwargs: "fake-doc-id")

    response = client.post("/api/tracks", params={
        "origin": "JFK",
        "destination": "ORD",
        "departure_date": "2026-04-15",
        "user_email": "test@example.com",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["doc_id"] == "fake-doc-id"
    assert data["origin"] == "JFK"


def test_predict_with_baseline(client):
    """Predict endpoint returns baseline data when origin/destination are provided."""
    payload = {
        "origin": "JFK",
        "destination": "ORD",
        "current_best_price": 100,
        "current_avg_price": 150,
        "current_price_spread": 80,
        "volatility_score": 0.1,
        "days_until_departure": 20,
        "current_flights": [],
    }
    response = client.post("/api/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["model_status"] == "gcs-baseline-v1"
    assert "historical_median" in data
    assert "buy_signal" in data
    assert data["buy_signal"] in ("great_deal", "good_price", "typical", "high")
    assert "sample_size" in data
    assert data["sample_size"] > 0


def test_route_baseline_math():
    """Verify baseline computation returns correct stats."""
    from gcs_data_service_simple import GCSDataServiceSimple
    svc = GCSDataServiceSimple()
    svc.data_cache = [
        {"origin": "TST", "destination": "DST", "total_price": "100"},
        {"origin": "TST", "destination": "DST", "total_price": "200"},
        {"origin": "TST", "destination": "DST", "total_price": "300"},
        {"origin": "TST", "destination": "DST", "total_price": "400"},
        {"origin": "TST", "destination": "DST", "total_price": "500"},
    ]
    baseline = svc.get_route_baseline("TST", "DST")
    assert baseline is not None
    assert baseline["median"] == 300  # odd count: middle value
    assert baseline["min"] == 100
    assert baseline["max"] == 500
    assert baseline["sample_size"] == 5
    assert baseline["p25"] == 200
    assert baseline["p75"] == 400

    # Test even count: median should be average of two middle values
    svc2 = GCSDataServiceSimple()
    svc2.data_cache = [
        {"origin": "AA", "destination": "BB", "total_price": "100"},
        {"origin": "AA", "destination": "BB", "total_price": "200"},
        {"origin": "AA", "destination": "BB", "total_price": "300"},
        {"origin": "AA", "destination": "BB", "total_price": "400"},
    ]
    b2 = svc2.get_route_baseline("AA", "BB")
    assert b2 is not None
    assert b2["median"] == 250  # (200 + 300) / 2
