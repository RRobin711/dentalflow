import pytest
import httpx
import redis

BASE_URL = "http://localhost:8000"


@pytest.fixture(autouse=True, scope="session")
def _flush_rate_limits():
    """Clear rate limit keys before and after the test session."""
    r = redis.from_url("redis://localhost:6379", decode_responses=True)
    for key in r.keys("ratelimit:*"):
        r.delete(key)
    r.close()
    yield
    r = redis.from_url("redis://localhost:6379", decode_responses=True)
    for key in r.keys("ratelimit:*"):
        r.delete(key)
    r.close()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as c:
        yield c


@pytest.fixture
def patient_id(client):
    """Get the first patient ID from the seeded data."""
    resp = client.get("/api/patients")
    assert resp.status_code == 200
    patients = resp.json()
    assert len(patients) > 0
    return patients[0]["id"]
