"""Claims Service — CDT validation, idempotent persistence, Redis Streams."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("claims-service")

from shared.models import ClaimCreate, ClaimResponse, HealthResponse

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

STREAM_NAME = "claims:pending"
CONSUMER_GROUP = "denial_workers"

# ── CDT Code Registry (~30 real codes) ─────────────────────────────────────

CDT_CODES: dict[str, str] = {
    # Diagnostic
    "D0120": "Periodic oral evaluation",
    "D0140": "Limited oral evaluation - problem focused",
    "D0150": "Comprehensive oral evaluation - new or established patient",
    "D0210": "Intraoral complete series of radiographic images",
    "D0220": "Intraoral periapical first radiographic image",
    "D0274": "Bitewings - four radiographic images",
    "D0330": "Panoramic radiographic image",
    # Preventive
    "D1110": "Prophylaxis - adult",
    "D1120": "Prophylaxis - child",
    "D1206": "Topical application of fluoride varnish",
    "D1351": "Sealant - per tooth",
    # Restorative
    "D2140": "Amalgam - one surface, primary or permanent",
    "D2150": "Amalgam - two surfaces, primary or permanent",
    "D2330": "Resin-based composite - one surface, anterior",
    "D2391": "Resin-based composite - one surface, posterior",
    "D2740": "Crown - porcelain/ceramic substrate",
    "D2750": "Crown - porcelain fused to high noble metal",
    # Endodontics
    "D3310": "Endodontic therapy, anterior tooth",
    "D3320": "Endodontic therapy, premolar tooth",
    "D3330": "Endodontic therapy, molar tooth",
    # Periodontics
    "D4341": "Periodontal scaling and root planing - four or more teeth per quadrant",
    "D4342": "Periodontal scaling and root planing - one to three teeth per quadrant",
    "D4910": "Periodontal maintenance",
    # Prosthodontics
    "D5110": "Complete denture - maxillary",
    "D5120": "Complete denture - mandibular",
    "D5213": "Maxillary partial denture - cast metal framework",
    # Implant
    "D6010": "Surgical placement of implant body - endosteal implant",
    "D6065": "Implant supported porcelain/ceramic crown",
    # Oral surgery
    "D7140": "Extraction, erupted tooth or exposed root",
    "D7210": "Extraction, erupted tooth requiring removal of bone and/or sectioning",
    "D7240": "Extraction, impacted tooth - completely bony",
    # Orthodontics
    "D8090": "Comprehensive orthodontic treatment - adult dentition",
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
            CREATE TABLE IF NOT EXISTS claims (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                idempotency_key VARCHAR(255) UNIQUE NOT NULL,
                patient_id UUID NOT NULL REFERENCES patients(id),
                cdt_code VARCHAR(10) NOT NULL,
                cdt_description VARCHAR(200),
                procedure_date DATE NOT NULL,
                tooth_number INT,
                charged_amount_cents INT NOT NULL,
                has_xray BOOLEAN NOT NULL DEFAULT false,
                has_narrative BOOLEAN NOT NULL DEFAULT false,
                has_perio_chart BOOLEAN NOT NULL DEFAULT false,
                status VARCHAR(30) NOT NULL DEFAULT 'created'
                    CHECK (status IN ('created','queued','scoring','scored','submitted','accepted','denied','error')),
                denial_risk_score FLOAT,
                denial_risk_factors JSONB,
                scored_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
            CREATE INDEX IF NOT EXISTS idx_claims_patient_id ON claims(patient_id);
            CREATE INDEX IF NOT EXISTS idx_claims_idempotency_key ON claims(idempotency_key);
        """)

    # Create consumer group (ignore if already exists)
    try:
        await app.state.redis.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    # Start stuck claims recovery job
    recovery_task = asyncio.create_task(_recovery_loop(app))

    yield

    recovery_task.cancel()
    try:
        await recovery_task
    except asyncio.CancelledError:
        pass
    await app.state.pool.close()
    await app.state.redis.aclose()


async def _recovery_loop(app: FastAPI):
    """Recover claims stuck in 'created' status due to failed XADD."""
    while True:
        try:
            rows = await app.state.pool.fetch(
                "SELECT * FROM claims WHERE status = 'created' AND created_at < NOW() - INTERVAL '2 minutes' AND updated_at < NOW() - INTERVAL '2 minutes'"
            )
            for row in rows:
                claim_id = str(row["id"])
                try:
                    await app.state.redis.xadd(
                        STREAM_NAME,
                        {
                            "claim_id": claim_id,
                            "patient_id": str(row["patient_id"]),
                            "cdt_code": row["cdt_code"],
                            "charged_amount_cents": str(row["charged_amount_cents"]),
                            "has_xray": str(row["has_xray"]),
                            "has_narrative": str(row["has_narrative"]),
                            "has_perio_chart": str(row["has_perio_chart"]),
                        },
                    )
                    await app.state.pool.execute(
                        "UPDATE claims SET status = 'queued', updated_at = now() WHERE id = $1",
                        row["id"],
                    )
                    logger.info(f"Recovered stuck claim {claim_id} — republished to stream")
                except Exception as e:
                    logger.error(f"Failed to recover claim {claim_id}: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Recovery loop error: {e}")
        await asyncio.sleep(30)


app = FastAPI(title="Claims Service", lifespan=lifespan)


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return HealthResponse(status="ok", service="claims-service")


@app.get("/claims", response_model=list[ClaimResponse])
async def list_claims():
    rows = await app.state.pool.fetch("SELECT * FROM claims ORDER BY created_at DESC")
    return [_row_to_claim(r) for r in rows]


@app.get("/claims/{claim_id}", response_model=ClaimResponse)
async def get_claim(claim_id: UUID):
    row = await app.state.pool.fetchrow("SELECT * FROM claims WHERE id = $1", claim_id)
    if not row:
        raise HTTPException(404, "Claim not found")
    return _row_to_claim(row)


@app.post("/claims", response_model=ClaimResponse, status_code=201)
async def create_claim(claim: ClaimCreate):
    # Validate CDT code
    cdt_code = claim.cdt_code.upper()
    if cdt_code not in CDT_CODES:
        raise HTTPException(422, f"Invalid CDT code: {claim.cdt_code}. Must be a valid ADA CDT code.")
    cdt_desc = CDT_CODES[cdt_code]

    # Validate patient exists
    patient = await app.state.pool.fetchrow("SELECT id FROM patients WHERE id = $1", claim.patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")

    # Idempotent insert
    try:
        row = await app.state.pool.fetchrow(
            """INSERT INTO claims
               (idempotency_key, patient_id, cdt_code, cdt_description,
                procedure_date, tooth_number, charged_amount_cents,
                has_xray, has_narrative, has_perio_chart, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'created')
               RETURNING *""",
            claim.idempotency_key,
            claim.patient_id,
            cdt_code,
            cdt_desc,
            claim.procedure_date,
            claim.tooth_number,
            claim.charged_amount_cents,
            claim.has_xray,
            claim.has_narrative,
            claim.has_perio_chart,
        )
    except asyncpg.UniqueViolationError:
        # Idempotency: return existing claim with 200 (not 201 — nothing was created)
        row = await app.state.pool.fetchrow(
            "SELECT * FROM claims WHERE idempotency_key = $1", claim.idempotency_key
        )
        return JSONResponse(
            status_code=200,
            content=ClaimResponse.model_validate(_row_to_claim(row)).model_dump(mode="json"),
        )

    # Publish to Redis Streams
    claim_id = str(row["id"])
    try:
        await app.state.redis.xadd(
            STREAM_NAME,
            {
                "claim_id": claim_id,
                "patient_id": str(claim.patient_id),
                "cdt_code": cdt_code,
                "charged_amount_cents": str(row["charged_amount_cents"]),
                "has_xray": str(row["has_xray"]),
                "has_narrative": str(row["has_narrative"]),
                "has_perio_chart": str(row["has_perio_chart"]),
            },
        )
        # Update status to queued
        await app.state.pool.execute(
            "UPDATE claims SET status = 'queued', updated_at = now() WHERE id = $1",
            row["id"],
        )
        row = await app.state.pool.fetchrow("SELECT * FROM claims WHERE id = $1", row["id"])
    except Exception:
        # Graceful degradation: claim exists in PG with status='created'
        pass

    return _row_to_claim(row)


def _row_to_claim(row) -> dict:
    d = dict(row)
    # asyncpg may return JSONB as a string if it was stored via a text parameter
    if isinstance(d.get("denial_risk_factors"), str):
        d["denial_risk_factors"] = json.loads(d["denial_risk_factors"])
    return d
