import scheduler


class _FakeReference:
    pass


class _FakeDoc:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = _FakeReference()

    def to_dict(self):
        return dict(self._data)


def test_check_prices_route_respects_cooldown(monkeypatch):
    client = scheduler.app.test_client()
    doc = _FakeDoc(
        "track-1",
        {
            "origin": "JFK",
            "destination": "LAX",
            "departure_date": "2026-04-20",
            "user_email": "user@example.com",
            "latest_price": 200,
            "notifications_enabled": True,
            "status": "active",
        },
    )
    update_calls = []
    email_calls = []
    log_calls = []

    monkeypatch.setenv("SCHEDULER_TOKEN", "scheduler-secret")
    monkeypatch.setattr(scheduler, "get_tracked_flights", lambda: [doc])
    monkeypatch.setattr(
        scheduler.gcs_data_service_simple,
        "search_flights",
        lambda **kwargs: [{"price": {"total": "150"}}],
    )
    monkeypatch.setattr(scheduler, "was_notified_recently", lambda doc_id, within_hours=24: True)
    monkeypatch.setattr(scheduler, "update_price", lambda doc_ref, new_price, current_price=None: update_calls.append((doc_ref, new_price, current_price)))
    monkeypatch.setattr(scheduler, "send_price_drop_email", lambda **kwargs: email_calls.append(kwargs) or True)
    monkeypatch.setattr(scheduler, "log_notification_sent", lambda **kwargs: log_calls.append(kwargs))

    response = client.post("/check-prices", headers={"X-Scheduler-Token": "scheduler-secret"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["skipped_cooldown"] == 1
    assert data["emails_sent"] == 0
    assert len(update_calls) == 1
    assert email_calls == []
    assert log_calls == []


def test_check_prices_only_logs_successful_email_sends(monkeypatch):
    client = scheduler.app.test_client()
    doc = _FakeDoc(
        "track-2",
        {
            "origin": "DEN",
            "destination": "SFO",
            "departure_date": "2026-04-21",
            "user_email": "user@example.com",
            "latest_price": 250,
            "notifications_enabled": True,
            "status": "active",
        },
    )
    log_calls = []

    monkeypatch.setenv("SCHEDULER_TOKEN", "scheduler-secret")
    monkeypatch.setattr(scheduler, "get_tracked_flights", lambda: [doc])
    monkeypatch.setattr(
        scheduler.gcs_data_service_simple,
        "search_flights",
        lambda **kwargs: [{"price": {"total": "200"}}],
    )
    monkeypatch.setattr(scheduler, "was_notified_recently", lambda doc_id, within_hours=24: False)
    monkeypatch.setattr(scheduler, "update_price", lambda doc_ref, new_price, current_price=None: None)
    monkeypatch.setattr(scheduler, "send_price_drop_email", lambda **kwargs: False)
    monkeypatch.setattr(scheduler, "log_notification_sent", lambda **kwargs: log_calls.append(kwargs))

    response = client.post("/check-prices", headers={"X-Scheduler-Token": "scheduler-secret"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["drops_detected"] == 1
    assert data["emails_sent"] == 0
    assert log_calls == []
