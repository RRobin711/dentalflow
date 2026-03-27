from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────

class ClaimStatus(str, enum.Enum):
    created = "created"
    queued = "queued"
    scoring = "scoring"
    scored = "scored"
    submitted = "submitted"
    accepted = "accepted"
    denied = "denied"
    error = "error"


class PlanType(str, enum.Enum):
    PPO = "PPO"
    HMO = "HMO"
    DHMO = "DHMO"


# ── Patient ────────────────────────────────────────────────────────────────

class PatientResponse(BaseModel):
    id: UUID
    name: str
    date_of_birth: date
    insurance_provider: str
    insurance_id: str
    plan_type: PlanType
    annual_maximum_cents: int
    annual_used_cents: int

    class Config:
        from_attributes = True


# ── Eligibility ────────────────────────────────────────────────────────────

class EligibilityCheckRequest(BaseModel):
    patient_id: UUID
    cdt_code: str
    procedure_date: Optional[date] = None


class EligibilityResponse(BaseModel):
    patient_id: UUID
    patient_name: str
    insurance_provider: str
    plan_type: PlanType
    cdt_code: str
    cdt_category: str
    coverage_percent: int
    estimated_patient_cost_cents: int
    estimated_insurance_pays_cents: int
    annual_maximum_cents: int
    annual_used_cents: int
    annual_remaining_cents: int
    eligible: bool
    reason: Optional[str] = None
    cache_hit: bool


# ── Claims ─────────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=255)
    patient_id: UUID
    cdt_code: str
    procedure_date: date
    tooth_number: Optional[int] = Field(None, ge=1, le=32)
    charged_amount_cents: int = Field(..., gt=0)
    has_xray: bool = False
    has_narrative: bool = False
    has_perio_chart: bool = False


class ClaimResponse(BaseModel):
    id: UUID
    idempotency_key: str
    patient_id: UUID
    cdt_code: str
    cdt_description: Optional[str] = None
    procedure_date: date
    tooth_number: Optional[int] = None
    charged_amount_cents: int
    has_xray: bool
    has_narrative: bool
    has_perio_chart: bool
    status: ClaimStatus
    denial_risk_score: Optional[float] = None
    denial_risk_factors: Optional[list] = None
    scored_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Denial Prediction ─────────────────────────────────────────────────────

class DenialPrediction(BaseModel):
    claim_id: UUID
    denial_risk_score: float
    denial_risk_factors: list[str]
    recommendation: str
    processing_time_ms: float


# ── Health ─────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str
    dependencies: Optional[dict] = None
