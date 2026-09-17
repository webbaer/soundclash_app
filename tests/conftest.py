import fakeredis
import pytest
from fastapi.testclient import TestClient

from app import redis_store
from app.main import app


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Ersetzt den echten Redis-Client durch einen In-Memory-Fake."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_store, "r", fake)
    return fake


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def game_code(client):
    resp = client.post("/games/", json={"max_rounds": 2})
    assert resp.status_code == 200
    return resp.json()["code"]
