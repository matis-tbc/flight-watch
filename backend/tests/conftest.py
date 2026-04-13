import pytest
from fastapi.testclient import TestClient
from flightwatch_backend.api import app


@pytest.fixture
def client():
    return TestClient(app)
