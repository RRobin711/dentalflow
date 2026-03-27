"""Patient Service — eligibility checks with cache-aside pattern."""

import json
import os
from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException

from shared.models import (
    EligibilityCheckRequest,
    EligibilityResponse,
    HealthResponse,
    PatientResponse,
)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = 900  # 15 minutes

# ── CDT code categories & coverage tiers ───────────────────────────────────

CDT_CATEGORIES = {
    "D0": "diagnostic",
    "D1": "preventive",
    "D2": "restorative",
    "D3": "endodontics",
    "D4": "periodontics",
    "D5": "prosthodontics",
    "D6": "implant",
    "D7": "oral_surgery",
    "D8": "orthodontics",
    "D9": "adjunctive",
}

# coverage_percent by (plan_type, tier)
COVERAGE_TIERS = {
    "PPO": {"preventive": 100, "diagnostic": 100, "basic": 80, "major": 50, "implant": 50, "orthodontics": 50},
    "HMO": {"preventive": 100, "diagnostic": 80, "basic": 60, "major": 40, "implant": 30, "orthodontics": 30},
    "DHMO": {"preventive": 80, "diagnostic": 70, "basic": 50, "major": 30, "implant": 20, "orthodontics": 20},
}

CATEGORY_TO_TIER = {
    "diagnostic": "diagnostic",
    "preventive": "preventive",
    "restorative": "basic",
    "endodontics": "basic",
    "periodontics": "basic",
    "prosthodontics": "major",
    "implant": "implant",
    "oral_surgery": "basic",
    "orthodontics": "orthodontics",
    "adjunctive": "basic",
}

# Typical procedure costs (cents) for estimating patient responsibility
TYPICAL_COSTS = {
    "D0": 8500, "D1": 12000, "D2": 95000, "D3": 80000,
    "D4": 25000, "D5": 150000, "D6": 300000, "D7": 25000,
    "D8": 500000, "D9": 15000,
}


def _get_cdt_category(cdt_code: str) -> str:
    prefix = cdt_code[:2].upper()
    return CDT_CATEGORIES.get(prefix, "adjunctive")


def _simulate_eligibility(
    patient: dict, cdt_code: str, charged_cents: int
) -> dict:
    """Simulate insurer eligibility response using realistic dental rules."""
    category = _get_cdt_category(cdt_code)
    tier = CATEGORY_TO_TIER.get(category, "basic")
    plan = patient["plan_type"]
    coverage_pct = COVERAGE_TIERS.get(plan, COVERAGE_TIERS["PPO"]).get(tier, 50)

    annual_max = patient["annual_maximum_cents"]
    annual_used = patient["annual_used_cents"]
    remaining = max(0, annual_max - annual_used)

    # Use typical cost if charged_cents not meaningful
    estimated_cost = charged_cents or TYPICAL_COSTS.get(cdt_code[:2].upper(), 10000)
    insurance_pays = min(int(estimated_cost * coverage_pct / 100), remaining)
    patient_pays = estimated_cost - insurance_pays

    eligible = remaining > 0 and coverage_pct > 0
    reason = None
    if remaining <= 0:
        eligible = False
        reason = "Annual maximum exhausted"
    elif coverage_pct == 0:
        eligible = False
        reason = f"Procedure category '{category}' not covered under {plan} plan"

    return {
        "patient_id": str(patient["id"]),
        "patient_name": patient["name"],
        "insurance_provider": patient["insurance_provider"],
        "plan_type": plan,
        "cdt_code": cdt_code,
        "cdt_category": category,
        "coverage_percent": coverage_pct,
        "estimated_patient_cost_cents": patient_pays,
        "estimated_insurance_pays_cents": insurance_pays,
        "annual_maximum_cents": annual_max,
        "annual_used_cents": annual_used,
        "annual_remaining_cents": remaining,
        "eligible": eligible,
        "reason": reason,
    }


# ── App lifecycle ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)

    # Ensure tables exist (for Render managed PG which doesn't run init_db.sql)
    async with app.state.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(200) NOT NULL,
                date_of_birth DATE NOT NULL,
                insurance_provider VARCHAR(100) NOT NULL,
                insurance_id VARCHAR(100) NOT NULL,
                plan_type VARCHAR(10) NOT NULL CHECK (plan_type IN ('PPO', 'HMO', 'DHMO')),
                annual_maximum_cents INT NOT NULL DEFAULT 150000,
                annual_used_cents INT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS eligibility_checks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                patient_id UUID NOT NULL REFERENCES patients(id),
                insurance_provider VARCHAR(100) NOT NULL,
                cdt_code VARCHAR(10) NOT NULL,
                coverage_percent INT,
                eligible BOOLEAN NOT NULL,
                reason TEXT,
                cache_hit BOOLEAN NOT NULL DEFAULT false,
                checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        count = await conn.fetchval("SELECT COUNT(*) FROM patients")
        if count == 0:
            await conn.execute("""
                INSERT INTO patients (name, date_of_birth, insurance_provider, insurance_id, plan_type, annual_maximum_cents, annual_used_cents) VALUES
                ('Maria Garcia',    '1985-03-15', 'Delta Dental', 'DD-29481037', 'PPO',  200000,  45000),
                ('James Chen',      '1972-11-22', 'MetLife',      'ML-58302741', 'PPO',  150000, 142000),
                ('Aisha Johnson',   '1990-07-08', 'Cigna',        'CG-73019284', 'HMO',  100000,  20000),
                ('Robert Williams', '1968-01-30', 'Aetna',        'AE-41927365', 'PPO',  175000,  89000),
                ('Sarah Kim',       '1995-12-04', 'Guardian',     'GD-62840193', 'DHMO', 120000, 118500)
            """)

    yield
    await app.state.pool.close()
    await app.state.redis.aclose()


app = FastAPI(title="Patient Service", lifespan=lifespan)


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return HealthResponse(status="ok", service="patient-service")


@app.get("/patients", response_model=list[PatientResponse])
async def list_patients():
    rows = await app.state.pool.fetch("SELECT * FROM patients ORDER BY name")
    return [dict(r) for r in rows]


@app.get("/patients/{patient_id}", response_model=PatientResponse)
async def get_patient(patient_id: UUID):
    row = await app.state.pool.fetchrow("SELECT * FROM patients WHERE id = $1", patient_id)
    if not row:
        raise HTTPException(404, "Patient not found")
    return dict(row)


@app.post("/eligibility", response_model=EligibilityResponse)
async def check_eligibility(req: EligibilityCheckRequest):
    # Fetch patient
    patient = await app.state.pool.fetchrow("SELECT * FROM patients WHERE id = $1", req.patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    patient = dict(patient)

    cache_key = f"elig:{req.patient_id}:{patient['insurance_provider']}:{req.cdt_code}"
    r: redis.Redis = app.state.redis

    # Cache-aside: check Redis first
    cached = await r.get(cache_key)
    if cached:
        result = json.loads(cached)
        result["cache_hit"] = True
        # Log audit
        await _log_eligibility(patient, req.cdt_code, result, cache_hit=True)
        return result

    # Cache miss — simulate insurer API
    estimated_cost = TYPICAL_COSTS.get(req.cdt_code[:2].upper(), 10000)
    result = _simulate_eligibility(patient, req.cdt_code, estimated_cost)
    result["cache_hit"] = False

    # Cache with TTL
    await r.setex(cache_key, CACHE_TTL, json.dumps(result, default=str))

    # Log audit
    await _log_eligibility(patient, req.cdt_code, result, cache_hit=False)

    return result


async def _log_eligibility(patient: dict, cdt_code: str, result: dict, cache_hit: bool):
    await app.state.pool.execute(
        """INSERT INTO eligibility_checks
           (patient_id, insurance_provider, cdt_code, coverage_percent, eligible, reason, cache_hit)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        patient["id"],
        patient["insurance_provider"],
        cdt_code,
        result.get("coverage_percent"),
        result.get("eligible", False),
        result.get("reason"),
        cache_hit,
    )
