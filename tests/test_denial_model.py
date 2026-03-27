"""Unit tests for DenialRiskModel and TrainedModel — no Docker needed."""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Stub out heavy dependencies and env vars so we can import just the model classes
for mod in ("asyncpg", "redis", "redis.asyncio"):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
os.environ.setdefault("DATABASE_URL", "postgresql://stub:stub@localhost/stub")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "denial_worker"))
from main import DenialRiskModel, TrainedModel

model = DenialRiskModel()


def test_preventive_low_risk():
    score, factors, _ = model.predict("D1110", 12000, has_xray=True, has_narrative=True, has_perio_chart=True)
    assert score < 0.15


def test_restorative_missing_xray():
    score, factors, _ = model.predict("D2740", 95000, has_xray=False, has_narrative=True, has_perio_chart=False)
    assert score >= 0.3
    assert any("Missing X-ray" in f for f in factors)


def test_implant_no_docs():
    score, factors, _ = model.predict("D6010", 300000, has_xray=False, has_narrative=False, has_perio_chart=False)
    assert score >= 0.5
    assert len(factors) >= 2


def test_perio_missing_chart():
    score, factors, _ = model.predict("D4341", 25000, has_xray=True, has_narrative=True, has_perio_chart=False)
    assert any("periodontal charting" in f.lower() for f in factors)


def test_charge_anomaly():
    score, factors, _ = model.predict("D1110", 500000, has_xray=True, has_narrative=True, has_perio_chart=True)
    assert any("exceeds typical" in f for f in factors)


def test_score_clamped():
    score, _, _ = model.predict("D6010", 5000000, has_xray=False, has_narrative=False, has_perio_chart=False)
    assert score <= 1.0


def test_ortho_flagged():
    score, factors, recommendation = model.predict("D8090", 500000, has_xray=True, has_narrative=True, has_perio_chart=True)
    assert any("pre-authorization" in f.lower() or "orthodontic" in f.lower() for f in factors)


def test_rule_based_annual_max_exhaustion():
    """Rule-based model should flag patients near annual max."""
    score, factors, _ = model.predict(
        "D2750", 120000, has_xray=True, has_narrative=False, has_perio_chart=False,
        plan_type="PPO", annual_max_cents=150000, annual_used_cents=140000
    )
    assert any("annual maximum" in f.lower() for f in factors)


# ── Trained Model Tests ──────────────────────────────────────────────────

MODEL_PATH = Path(__file__).parent.parent / "ml" / "model.joblib"


@pytest.mark.skipif(not MODEL_PATH.exists(), reason="Trained model not found")
class TestTrainedModel:
    @pytest.fixture(autouse=True)
    def load_model(self):
        import joblib
        data = joblib.load(MODEL_PATH)
        self.model = TrainedModel(data)

    def test_low_risk_prophylaxis(self):
        """Adult cleaning with X-ray, PPO plan, low usage — should be low risk."""
        score, factors, rec = self.model.predict(
            "D1110", 12500, has_xray=True, has_narrative=False, has_perio_chart=False,
            plan_type="PPO", annual_max_cents=200000, annual_used_cents=20000
        )
        assert score < 0.3, f"Prophylaxis with docs should be low risk, got {score:.2f}"
        assert "LOW" in rec

    def test_high_risk_implant_no_docs(self):
        """Implant with no documentation, HMO plan — should be high risk."""
        score, factors, rec = self.model.predict(
            "D6010", 350000, has_xray=False, has_narrative=False, has_perio_chart=False,
            plan_type="HMO", annual_max_cents=100000, annual_used_cents=80000
        )
        assert score > 0.5, f"Implant without docs on HMO should be high risk, got {score:.2f}"
        assert len(factors) > 0, "Should have risk factors"

    def test_interaction_xray_cost(self):
        """Missing X-ray on expensive crown should be riskier than on cheap filling."""
        score_expensive, _, _ = self.model.predict(
            "D2750", 200000, has_xray=False, has_narrative=False, has_perio_chart=False,
            plan_type="PPO", annual_max_cents=200000, annual_used_cents=0
        )
        score_cheap, _, _ = self.model.predict(
            "D2140", 15000, has_xray=False, has_narrative=False, has_perio_chart=False,
            plan_type="PPO", annual_max_cents=200000, annual_used_cents=0
        )
        assert score_expensive > score_cheap, \
            f"Expensive crown ({score_expensive:.2f}) should be riskier than cheap filling ({score_cheap:.2f})"

    def test_annual_max_exhaustion(self):
        """Near-exhausted annual max should increase risk for expensive procedures."""
        score_high_usage, _, _ = self.model.predict(
            "D6010", 300000, has_xray=False, has_narrative=False, has_perio_chart=False,
            plan_type="HMO", annual_max_cents=150000, annual_used_cents=140000
        )
        score_low_usage, _, _ = self.model.predict(
            "D6010", 300000, has_xray=False, has_narrative=False, has_perio_chart=False,
            plan_type="HMO", annual_max_cents=150000, annual_used_cents=10000
        )
        assert score_high_usage > score_low_usage, \
            f"High usage ({score_high_usage:.2f}) should be riskier than low ({score_low_usage:.2f})"

    def test_shap_factors_present(self):
        """Risk factors should be specific to the prediction, not empty."""
        score, factors, _ = self.model.predict(
            "D6010", 350000, has_xray=False, has_narrative=False, has_perio_chart=False,
            plan_type="HMO", annual_max_cents=100000, annual_used_cents=90000
        )
        assert len(factors) >= 2, f"High-risk claim should have multiple factors, got {factors}"
        assert any("impact" in f for f in factors), "Factors should include SHAP impact percentages"
