"""Integration tests — run against live Docker containers."""

import time
import uuid

import httpx


def _unique_key(prefix="test"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _wait_for_scoring(client: httpx.Client, claim_id: str, timeout: int = 10):
    """Poll until claim is scored or timeout."""
    for _ in range(timeout):
        resp = client.get(f"/api/claims/{claim_id}")
        data = resp.json()
        if data["status"] == "scored":
            return data
        time.sleep(1)
    return client.get(f"/api/claims/{claim_id}").json()


# ── Health ─────────────────────────────────────────────────────────────────


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    for dep in ("redis", "patient-service", "claims-service"):
        assert data["dependencies"][dep] == "ok"


# ── Patients ───────────────────────────────────────────────────────────────


def test_list_patients(client):
    resp = client.get("/api/patients")
    assert resp.status_code == 200
    assert len(resp.json()) == 5


def test_get_patient(client, patient_id):
    resp = client.get(f"/api/patients/{patient_id}")
    assert resp.status_code == 200
    data = resp.json()
    for field in ("name", "insurance_provider", "plan_type", "annual_maximum_cents"):
        assert field in data


def test_get_patient_not_found(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/patients/{fake_id}")
    assert resp.status_code == 404


# ── Eligibility ────────────────────────────────────────────────────────────


def test_eligibility_cache_miss_then_hit(client, patient_id):
    """First call is a cache miss, second call with same params is a hit."""
    # Use a less common CDT code to avoid collisions with prior runs
    cdt = "D1351"
    # Flush this specific cache key first
    import redis as sync_redis
    r = sync_redis.from_url("redis://localhost:6379", decode_responses=True)
    for key in r.keys(f"elig:{patient_id}:*:{cdt}"):
        r.delete(key)
    r.close()

    resp1 = client.post("/api/eligibility", json={
        "patient_id": patient_id, "cdt_code": cdt
    })
    assert resp1.status_code == 200
    assert resp1.json()["cache_hit"] is False
    assert resp1.json()["coverage_percent"] > 0

    # Second call — cache hit
    resp2 = client.post("/api/eligibility", json={
        "patient_id": patient_id, "cdt_code": cdt
    })
    assert resp2.status_code == 200
    assert resp2.json()["cache_hit"] is True


def test_eligibility_different_procedure_is_separate_cache_key(client, patient_id):
    import redis as sync_redis
    r = sync_redis.from_url("redis://localhost:6379", decode_responses=True)
    # Flush cache keys for both codes
    for cdt in ("D5110", "D5120"):
        for key in r.keys(f"elig:{patient_id}:*:{cdt}"):
            r.delete(key)
    r.close()

    # First call with D5110
    client.post("/api/eligibility", json={"patient_id": patient_id, "cdt_code": "D5110"})
    # Different code — should be a cache miss
    resp = client.post("/api/eligibility", json={"patient_id": patient_id, "cdt_code": "D5120"})
    assert resp.status_code == 200
    assert resp.json()["cache_hit"] is False


# ── Claims ─────────────────────────────────────────────────────────────────


def test_create_claim(client, patient_id):
    resp = client.post("/api/claims", json={
        "idempotency_key": _unique_key("create"),
        "patient_id": patient_id,
        "cdt_code": "D1110",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 12500,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] in ("created", "queued")
    assert data["cdt_description"] is not None


def test_create_claim_invalid_cdt(client, patient_id):
    resp = client.post("/api/claims", json={
        "idempotency_key": _unique_key("invalid"),
        "patient_id": patient_id,
        "cdt_code": "X9999",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 5000,
    })
    assert resp.status_code == 422


def test_create_claim_missing_fields(client):
    resp = client.post("/api/claims", json={})
    assert resp.status_code == 422


# ── Idempotency ────────────────────────────────────────────────────────────


def test_idempotency(client, patient_id):
    key = _unique_key("idemp")
    payload = {
        "idempotency_key": key,
        "patient_id": patient_id,
        "cdt_code": "D1110",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 12500,
    }
    resp1 = client.post("/api/claims", json=payload)
    resp2 = client.post("/api/claims", json=payload)
    assert resp1.status_code == 201
    assert resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]


# ── Denial scoring ─────────────────────────────────────────────────────────


def test_claim_gets_scored(client, patient_id):
    resp = client.post("/api/claims", json={
        "idempotency_key": _unique_key("scored"),
        "patient_id": patient_id,
        "cdt_code": "D2740",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 95000,
        "has_xray": True,
    })
    claim_id = resp.json()["id"]
    data = _wait_for_scoring(client, claim_id)
    assert data["status"] == "scored"
    assert data["denial_risk_score"] is not None
    assert 0.0 <= data["denial_risk_score"] <= 1.0


def test_low_risk_claim(client, patient_id):
    resp = client.post("/api/claims", json={
        "idempotency_key": _unique_key("low"),
        "patient_id": patient_id,
        "cdt_code": "D1110",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 12500,
        "has_xray": True,
        "has_narrative": True,
    })
    data = _wait_for_scoring(client, resp.json()["id"])
    assert data["denial_risk_score"] < 0.2


def test_high_risk_claim(client, patient_id):
    resp = client.post("/api/claims", json={
        "idempotency_key": _unique_key("high"),
        "patient_id": patient_id,
        "cdt_code": "D2740",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 120000,
        "has_xray": False,
    })
    data = _wait_for_scoring(client, resp.json()["id"])
    assert data["denial_risk_score"] >= 0.3


def test_very_high_risk_claim(client, patient_id):
    resp = client.post("/api/claims", json={
        "idempotency_key": _unique_key("vhigh"),
        "patient_id": patient_id,
        "cdt_code": "D6010",
        "procedure_date": "2026-03-27",
        "charged_amount_cents": 350000,
        "has_xray": False,
        "has_narrative": False,
    })
    data = _wait_for_scoring(client, resp.json()["id"])
    # PPO patient with low annual usage gets some protection from ML model,
    # but implant with no docs should still be at least medium risk
    assert data["denial_risk_score"] >= 0.35


# ── Rate limiting ──────────────────────────────────────────────────────────


def test_rate_limit(client):
    got_429 = False
    for _ in range(101):
        resp = client.get("/api/patients")
        if resp.status_code == 429:
            got_429 = True
            break
    # Clean up rate limit key so subsequent test runs aren't affected
    import redis as sync_redis
    r = sync_redis.from_url("redis://localhost:6379", decode_responses=True)
    for key in r.keys("ratelimit:*"):
        r.delete(key)
    r.close()
    assert got_429, "Expected at least one 429 response after 101 requests"
