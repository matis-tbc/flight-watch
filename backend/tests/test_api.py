"""Tests for FlightWatch API endpoints."""
import app_simple_gcs
import firestore_logic
from date_utils import normalize_date_text
from unsubscribe_tokens import build_unsubscribe_token


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


def test_search_scales_mock_prices_by_passengers(client, monkeypatch):
    monkeypatch.setattr(app_simple_gcs, "check_gcs_configured", lambda: False)
    monkeypatch.setattr(app_simple_gcs, "check_amadeus_configured", lambda: False)
    monkeypatch.setattr(
        app_simple_gcs,
        "get_mock_flights",
        lambda origin, destination, departure_date=None: [
            {
                "id": "mock-1",
                "price": {"total": "100.00", "currency": "USD"},
                "source": "mock",
            }
        ],
    )

    response = client.get("/api/search", params={
        "origin": "JFK",
        "destination": "LAX",
        "passengers": 3,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["passengers"] == 3
    assert data["pricing_basis"] == "scaled_from_single_passenger_mock_data"
    assert data["flights"][0]["price"]["total"] == "300.00"


def test_mock_jfk_lax_duration_is_not_hardcoded_to_three_hours():
    flights = app_simple_gcs.get_mock_flights("JFK", "LAX", "2026-05-01")

    assert len(flights) >= 1
    assert flights[0]["duration"] == "6h 20m"
    assert flights[0]["arrival"].startswith("2026-05-01T14:20:00")


def test_search_uses_amadeus_when_gcs_only_has_closest_date(client, monkeypatch):
    monkeypatch.setattr(app_simple_gcs, "check_gcs_configured", lambda: True)
    monkeypatch.setattr(app_simple_gcs, "check_amadeus_configured", lambda: True)
    monkeypatch.setattr(
        app_simple_gcs.gcs_data_service_simple,
        "search_flights",
        lambda **kwargs: [{"departure_date": "2026-04-20", "total_price": "180.00"}],
    )
    monkeypatch.setattr(
        app_simple_gcs,
        "format_flight_data",
        lambda flights: [{"id": "amadeus-1", "price": {"total": "250.00", "currency": "USD"}}],
    )

    class FakeAmadeusClient:
        pass

    monkeypatch.setattr(app_simple_gcs, "_flight_matches_departure_date", lambda flight, departure_date: False)

    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "flight_fetcher":
            class FakeModule:
                @staticmethod
                def authenticate_amadeus():
                    return FakeAmadeusClient()

                @staticmethod
                def search_flights(amadeus_client, origin, destination, departure_date, return_date, passengers):
                    assert departure_date == "2026-04-21"
                    return [{"id": "raw-amadeus"}]

            return FakeModule()
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    response = client.get("/api/search", params={
        "origin": "JFK",
        "destination": "LAX",
        "departure_date": "2026-04-21",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "amadeus"
    assert data["departure_date"] == "2026-04-21"


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


def test_tracks_public_view_hides_emails(client, monkeypatch):
    class FakeDoc:
        def __init__(self, doc_id, payload):
            self.id = doc_id
            self._payload = payload

        def to_dict(self):
            return dict(self._payload)

    fake_docs = [
        FakeDoc("abc123", {
            "origin": "JFK",
            "destination": "LAX",
            "departure_date": "2026-05-01",
            "user_email": "hidden@example.com",
        })
    ]

    monkeypatch.setattr(firestore_logic, "get_tracked_flights", lambda: fake_docs)
    monkeypatch.setattr(app_simple_gcs, "get_tracked_flights", lambda: fake_docs)

    response = client.get("/api/tracks")
    assert response.status_code == 200
    data = response.json()
    assert data["admin_view"] is False
    assert data["count"] == 1
    assert data["route_count"] == 1
    assert "user_email" not in data["tracks"][0]
    assert "id" not in data["tracks"][0]
    assert data["tracks"][0]["origin"] == "JFK"
    assert data["tracks"][0]["subscriber_count"] == 1


def test_tracks_admin_view_returns_manageable_records(client, monkeypatch):
    class FakeDoc:
        def __init__(self, doc_id, payload):
            self.id = doc_id
            self._payload = payload

        def to_dict(self):
            return dict(self._payload)

    fake_docs = [
        FakeDoc("abc123", {
            "origin": "JFK",
            "destination": "LAX",
            "departure_date": "2026-05-01",
            "user_email": "hidden@example.com",
        })
    ]

    monkeypatch.setenv("ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(firestore_logic, "get_tracked_flights", lambda: fake_docs)
    monkeypatch.setattr(app_simple_gcs, "get_tracked_flights", lambda: fake_docs)

    response = client.get("/api/tracks", headers={"X-Admin-Token": "secret-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["admin_view"] is True
    assert data["tracks"][0]["subscriber_count"] == 1
    assert data["tracks"][0]["track_ids"] == ["abc123"]
    assert data["tracks"][0]["subscribers"][0]["user_email"] == "hidden@example.com"


def test_tracks_admin_details_returns_emails(client, monkeypatch):
    class FakeDoc:
        def __init__(self, doc_id, payload):
            self.id = doc_id
            self._payload = payload

        def to_dict(self):
            return dict(self._payload)

    fake_docs = [
        FakeDoc("abc123", {
            "origin": "JFK",
            "destination": "LAX",
            "departure_date": "2026-05-01",
            "user_email": "one@example.com",
            "adults": 2,
        }),
        FakeDoc("def456", {
            "origin": "JFK",
            "destination": "LAX",
            "departure_date": "2026-05-01",
            "user_email": "two@example.com",
            "adults": 1,
        }),
    ]

    monkeypatch.setenv("ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(firestore_logic, "get_tracked_flights", lambda: fake_docs)
    monkeypatch.setattr(app_simple_gcs, "get_tracked_flights", lambda: fake_docs)

    response = client.get(
        "/api/tracks/details",
        params={"origin": "JFK", "destination": "LAX", "departure_date": "2026-05-01"},
        headers={"X-Admin-Token": "secret-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert {track["user_email"] for track in data["tracks"]} == {"one@example.com", "two@example.com"}


def test_delete_track_requires_admin_token(client):
    response = client.delete("/api/tracks/some-id")
    assert response.status_code == 401


def test_tracks_admin_rejects_wrong_token(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "real-token")
    response = client.get("/api/tracks/details",
                          params={"origin": "JFK", "destination": "LAX", "departure_date": "2026-05-01"},
                          headers={"X-Admin-Token": "wrong-token"})
    assert response.status_code == 401


def test_create_track_rate_limit_returns_429(client, monkeypatch):
    from app_simple_gcs import limiter
    limiter.reset()

    monkeypatch.setattr(firestore_logic, "create_tracked_flight", lambda **kwargs: "doc")
    if hasattr(app_simple_gcs, "create_tracked_flight"):
        monkeypatch.setattr(app_simple_gcs, "create_tracked_flight", lambda **kwargs: "doc")
    monkeypatch.setattr(app_simple_gcs, "check_gcs_configured", lambda: False)

    params = {"origin": "JFK", "destination": "ORD",
              "departure_date": "2026-04-15", "user_email": "rl@example.com"}
    for i in range(10):
        r = client.post("/api/tracks", params=params)
        assert r.status_code == 200, f"request {i+1} unexpectedly failed: {r.status_code}"
    r = client.post("/api/tracks", params=params)
    assert r.status_code == 429
    limiter.reset()


def test_normalize_date_text_accepts_slash_format():
    assert normalize_date_text("04/08/2026") == "2026-04-08"
    assert normalize_date_text("2026-04-08T09:00:00") == "2026-04-08"


def test_unsubscribe_requires_valid_token(client):
    import os
    os.environ["SCHEDULER_TOKEN"] = "test-secret"
    response = client.get("/unsubscribe", params={"email": "user@example.com", "token": "bad-token"})
    assert response.status_code == 400
    assert "Invalid unsubscribe link" in response.text


def test_unsubscribe_disables_notifications(client, monkeypatch):
    from unsubscribe_tokens import build_unsubscribe_token

    called = {}

    def fake_disable_notifications(email):
        called["email"] = email
        return 2

    monkeypatch.setenv("SCHEDULER_TOKEN", "test-secret")
    monkeypatch.setattr("app_simple_gcs.disable_notifications_for_email", fake_disable_notifications)

    email = "user@example.com"
    token = build_unsubscribe_token(email)

    response = client.get("/unsubscribe", params={"email": email, "token": token})
    assert response.status_code == 200
    assert called["email"] == email
    assert "unsubscribed" in response.text.lower() or "no longer" in response.text.lower()


def test_create_track(client, monkeypatch):
    captured = {}

    def fake_create_tracked_flight(**kwargs):
        captured.update(kwargs)
        return "fake-doc-id"

    monkeypatch.setattr(firestore_logic, "create_tracked_flight", fake_create_tracked_flight)
    if hasattr(app_simple_gcs, "create_tracked_flight"):
        monkeypatch.setattr(app_simple_gcs, "create_tracked_flight", fake_create_tracked_flight)

    response = client.post("/api/tracks", params={
        "origin": "JFK",
        "destination": "ORD",
        "departure_date": "2026-04-15",
        "user_email": "test@example.com",
        "passengers": 2,
    })
    assert response.status_code == 200
    data = response.json()
    assert data["doc_id"] == "fake-doc-id"
    assert data["origin"] == "JFK"
    assert data["passengers"] == 2
    assert captured["adults"] == 2


def test_create_track_without_gcs_still_succeeds(client, monkeypatch):
    captured = {}

    def fake_create_tracked_flight(**kwargs):
        captured.update(kwargs)
        return "fake-doc-id"

    monkeypatch.setattr(app_simple_gcs, "check_gcs_configured", lambda: False)
    monkeypatch.setattr(firestore_logic, "create_tracked_flight", fake_create_tracked_flight)
    if hasattr(app_simple_gcs, "create_tracked_flight"):
        monkeypatch.setattr(app_simple_gcs, "create_tracked_flight", fake_create_tracked_flight)

    response = client.post("/api/tracks", params={
        "origin": "JFK",
        "destination": "ORD",
        "departure_date": "2026-04-15",
        "user_email": "test@example.com",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["doc_id"] == "fake-doc-id"
    assert data["baseline_price"] is None
    assert captured["latest_price"] is None


def test_predict_with_baseline(client, monkeypatch):
    """Predict endpoint returns baseline data when origin/destination are provided."""
    monkeypatch.setattr(
        app_simple_gcs.gcs_data_service_simple,
        "get_route_baseline",
        lambda origin, destination: {
            "median": 150,
            "mean": 155,
            "p25": 120,
            "p75": 180,
            "min": 100,
            "max": 220,
            "sample_size": 8,
        },
    )

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
