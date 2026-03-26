import pytest
from fastapi.testclient import TestClient
from app_simple_gcs import app


@pytest.fixture
def client():
    return TestClient(app)
