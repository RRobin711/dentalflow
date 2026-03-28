"""Unit tests for service business logic — no Docker required."""

import importlib.util
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Stub heavy dependencies so we can import service modules
for mod in (
    "asyncpg", "redis", "redis.asyncio", "uvicorn",
    "sse_starlette", "sse_starlette.sse", "httpx",
    "fastapi", "fastapi.responses", "fastapi.middleware", "fastapi.middleware.cors",
    "pydantic",
):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
os.environ.setdefault("DATABASE_URL", "postgresql://stub:stub@localhost/stub")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _import_service(service_dir: str, module_alias: str):
    """Import a service's main.py without colliding with other main modules."""
    spec = importlib.util.spec_from_file_location(
        module_alias,
        os.path.join(_ROOT, service_dir, "main.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    # Ensure shared/ is importable
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    spec.loader.exec_module(mod)
    return mod


# Load service modules once at module level
_claims_mod = _import_service("claims_service", "claims_main")
_patient_mod = _import_service("patient_service", "patient_main")


# ── CDT Validation (Claims Service) ────────────────────────────────────

class TestCDTValidation:
    """Test CDT code validation logic without a running database."""

    def test_valid_codes_are_recognized(self):
        """All seeded CDT codes should be in the registry."""
        for code in ("D0120", "D1110", "D2740", "D3330", "D6010", "D7140"):
            assert code in _claims_mod.CDT_CODES, f"{code} should be a valid CDT code"

    def test_invalid_code_not_in_registry(self):
        assert "X9999" not in _claims_mod.CDT_CODES
        assert "D0000" not in _claims_mod.CDT_CODES

    def test_code_descriptions_are_nonempty(self):
        for code, desc in _claims_mod.CDT_CODES.items():
            assert len(desc) > 0, f"CDT code {code} has empty description"

    def test_codes_follow_ada_format(self):
        """CDT codes should be D followed by 4 digits."""
        import re
        for code in _claims_mod.CDT_CODES:
            assert re.match(r"^D\d{4}$", code), f"Code {code} doesn't match CDT format D####"


# ── Eligibility Calculation (Patient Service) ──────────────────────────

class TestEligibilityCalculation:
    """Test eligibility simulation logic without Redis or PostgreSQL."""

    def _make_patient(self, plan_type="PPO", annual_max=200000, annual_used=0):
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "Test Patient",
            "insurance_provider": "Delta Dental",
            "plan_type": plan_type,
            "annual_maximum_cents": annual_max,
            "annual_used_cents": annual_used,
        }

    def test_preventive_ppo_full_coverage(self):
        """PPO plan should cover preventive procedures at 100%."""
        result = _patient_mod._simulate_eligibility(self._make_patient("PPO"), "D1110", 12000)
        assert result["coverage_percent"] == 100
        assert result["eligible"] is True

    def test_annual_max_exhausted(self):
        """Patient with exhausted annual max should be ineligible."""
        patient = self._make_patient("PPO", annual_max=100000, annual_used=100000)
        result = _patient_mod._simulate_eligibility(patient, "D2740", 95000)
        assert result["eligible"] is False
        assert "exhausted" in result["reason"].lower()

    def test_insurance_pays_capped_at_remaining(self):
        """Insurance payment should not exceed remaining annual benefit."""
        patient = self._make_patient("PPO", annual_max=100000, annual_used=90000)
        result = _patient_mod._simulate_eligibility(patient, "D1110", 12000)
        # Only 10000 cents remaining, even at 100% coverage
        assert result["estimated_insurance_pays_cents"] <= 10000

    def test_hmo_lower_coverage_than_ppo(self):
        """HMO plans should generally have lower coverage percentages."""
        ppo_result = _patient_mod._simulate_eligibility(self._make_patient("PPO"), "D2740", 95000)
        hmo_result = _patient_mod._simulate_eligibility(self._make_patient("HMO"), "D2740", 95000)
        assert ppo_result["coverage_percent"] >= hmo_result["coverage_percent"]

    def test_implant_coverage_varies_by_plan(self):
        """Implant coverage should differ across plan types."""
        ppo = _patient_mod._simulate_eligibility(self._make_patient("PPO"), "D6010", 300000)
        dhmo = _patient_mod._simulate_eligibility(self._make_patient("DHMO"), "D6010", 300000)
        assert ppo["coverage_percent"] > dhmo["coverage_percent"]


# ── Coverage Tier Mapping ──────────────────────────────────────────────

class TestCoverageTiers:
    """Verify coverage tier configuration is consistent."""

    def test_all_plan_types_defined(self):
        for plan in ("PPO", "HMO", "DHMO"):
            assert plan in _patient_mod.COVERAGE_TIERS

    def test_ppo_preventive_is_100(self):
        assert _patient_mod.COVERAGE_TIERS["PPO"]["preventive"] == 100

    def test_coverage_values_are_valid_percentages(self):
        for plan, tiers in _patient_mod.COVERAGE_TIERS.items():
            for tier, pct in tiers.items():
                assert 0 <= pct <= 100, f"{plan}/{tier} has invalid coverage {pct}"
