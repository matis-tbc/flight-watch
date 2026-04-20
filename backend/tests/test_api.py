"""Tests for FlightWatch API endpoints."""
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


def test_search_scales_mock_prices_for_multiple_passengers(client, monkeypatch):
    monkeypatch.setattr("app_simple_gcs.check_gcs_configured", lambda: False)
    monkeypatch.setattr("app_simple_gcs.check_amadeus_configured", lambda: False)

    response = client.get("/api/search", params={
        "origin": "JFK",
        "destination": "LAX",
        "departure_date": "2026-04-20",
        "passengers": 3,
        "limit": 1,
    })

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "mock"
    assert data["passengers"] == 3
    assert data["flights"][0]["price"]["total"] == "899.97"
    assert data["flights"][0]["passengers_priced"] == 3
    assert data["flights"][0]["price_basis"] == "total_for_all_passengers"


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


def test_unsubscribe_requires_valid_token(client):
    import os
    os.environ["SCHEDULER_TOKEN"] = "test-secret"
    response = client.get("/unsubscribe", params={"email": "user@example.com", "token": "bad-token"})
    assert response.status_code == 400
    assert "Invalid unsubscribe link" in response.text


def test_unsubscribe_disables_notifications(client, monkeypatch):
    called = {}

    def fake_disable_notifications(email):
        called["email"] = email
        return 2

    monkeypatch.setenv("SCHEDULER_TOKEN", "test-secret")
    monkeypatch.setattr("app_simple_gcs.disable_notifications_for_email", fake_disable_notifications)

    response = client.get(
        "/unsubscribe",
        params={
            "email": "User@Example.com",
            "token": build_unsubscribe_token("user@example.com"),
        },
    )

    assert response.status_code == 200
    assert called["email"] == "user@example.com"
    assert "Updated 2 tracked flight alerts." in response.text
