"""Denial Prediction Worker — Redis Streams consumer with ML scoring."""

import asyncio
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from uuid import UUID

import asyncpg
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("denial-worker")

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

STREAM_NAME = "claims:pending"
CONSUMER_GROUP = "denial_workers"
CONSUMER_NAME = f"worker-{os.getpid()}"
PUBSUB_CHANNEL = "claim_updates"


# ── Health endpoint (so Render treats this as a healthy web service) ───────

health_app = FastAPI()

@health_app.get("/health")
async def health():
    return {"status": "healthy", "service": "denial-worker"}

def _run_health_server():
    port = int(os.environ.get("PORT", "8003"))
    uvicorn.run(health_app, host="0.0.0.0", port=port, log_level="warning")


# ── Denial Risk Model ─────────────────────────────────────────────────────

# CDT prefix → category name (must match training script)
PREFIX_TO_CATEGORY = {
    "D0": "preventive", "D1": "preventive", "D2": "restorative", "D3": "endo",
    "D4": "perio", "D5": "prosth", "D6": "implant", "D7": "oral_surgery",
    "D8": "ortho", "D9": "preventive",
}

CATEGORIES = ["preventive", "restorative", "endo", "perio", "prosth", "oral_surgery", "implant", "ortho"]
PLAN_TYPES = ["PPO", "HMO", "DHMO"]

TYPICAL_COSTS = {
    "D0": 8500, "D1": 12000, "D2": 95000, "D3": 80000,
    "D4": 25000, "D5": 150000, "D6": 300000, "D7": 25000,
    "D8": 500000, "D9": 15000,
}


def _recommendation(score: float) -> str:
    if score >= 0.7:
        return "HIGH RISK — Manual review required before submission"
    elif score >= 0.4:
        return "MEDIUM RISK — Consider adding supporting documentation"
    elif score >= 0.2:
        return "LOW-MEDIUM RISK — Review flagged factors"
    else:
        return "LOW RISK — Likely to be accepted"


class DenialRiskModel:
    """Rule-based denial risk scorer — fallback when trained model is unavailable."""

    BASE_RATES = {
        "D0": 0.05, "D1": 0.08, "D2": 0.15, "D3": 0.20,
        "D4": 0.22, "D5": 0.30, "D6": 0.40, "D7": 0.18, "D8": 0.35, "D9": 0.12,
    }

    NEEDS_XRAY = {"D2", "D3", "D7"}
    NEEDS_NARRATIVE = {"D4", "D5", "D6"}
    NEEDS_PERIO_CHART = {"D4"}

    def predict(self, cdt_code: str, charged_cents: int,
                has_xray: bool, has_narrative: bool, has_perio_chart: bool,
                plan_type: str = "PPO", annual_max_cents: int = 200000,
                annual_used_cents: int = 0) -> tuple:
        prefix = cdt_code[:2].upper()
        score = self.BASE_RATES.get(prefix, 0.15)
        factors = []

        if prefix in self.NEEDS_XRAY and not has_xray:
            score += 0.25
            factors.append("Missing X-ray for restorative/endo/surgical procedure")
        if prefix in self.NEEDS_NARRATIVE and not has_narrative:
            score += 0.20
            factors.append("Missing narrative for perio/prosth/implant procedure")
        if prefix in self.NEEDS_PERIO_CHART and not has_perio_chart:
            score += 0.15
            factors.append("Missing periodontal charting for perio procedure")

        typical = TYPICAL_COSTS.get(prefix, 10000)
        if charged_cents > typical * 1.5:
            score += 0.15
            factors.append(f"Charged amount (${charged_cents/100:.0f}) exceeds typical (${typical/100:.0f}) by >50%")
        if prefix == "D6":
            factors.append("Implant procedures have high baseline denial rate")
        if prefix == "D8":
            factors.append("Orthodontic procedures often require pre-authorization")

        # Annual max near exhaustion
        if annual_max_cents > 0:
            usage_ratio = annual_used_cents / annual_max_cents
            if usage_ratio > 0.85:
                score += 0.10
                factors.append(f"Patient at {usage_ratio:.0%} of annual maximum")

        score = min(1.0, max(0.0, score))
        return score, factors, _recommendation(score)


class TrainedModel:
    """Wrapper around the sklearn trained model with SHAP explanations."""

    def __init__(self, model_data: dict):
        self.clf = model_data["model"]
        self.feature_names = model_data["feature_names"]
        try:
            import shap
            self.explainer = shap.TreeExplainer(self.clf)
            logger.info("SHAP TreeExplainer initialized")
        except Exception as e:
            logger.warning(f"SHAP unavailable, using global importance fallback: {e}")
            self.explainer = None

    def predict(self, cdt_code: str, charged_cents: int,
                has_xray: bool, has_narrative: bool, has_perio_chart: bool,
                plan_type: str = "PPO", annual_max_cents: int = 200000,
                annual_used_cents: int = 0) -> tuple:
        import numpy as np

        prefix = cdt_code[:2].upper()
        category = PREFIX_TO_CATEGORY.get(prefix, "preventive")

        typical = TYPICAL_COSTS.get(prefix, 10000)
        charge_anomaly_ratio = charged_cents / typical if typical > 0 else 1.0

        annual_usage_ratio = annual_used_cents / annual_max_cents if annual_max_cents > 0 else 0.0

        # Build feature vector matching training order
        cat_onehot = [1.0 if c == category else 0.0 for c in CATEGORIES]
        plan_onehot = [1.0 if p == plan_type else 0.0 for p in PLAN_TYPES]

        features = (
            cat_onehot +
            [float(has_xray), float(has_narrative), float(has_perio_chart)] +
            [charge_anomaly_ratio] +
            plan_onehot +
            [annual_usage_ratio]
        )

        X = np.array([features])
        score = float(self.clf.predict_proba(X)[0][1])

        # Per-prediction explanation via SHAP
        factors = []
        if self.explainer is not None:
            try:
                factors = self._shap_factors(X, features)
            except Exception as e:
                logger.warning(f"SHAP explanation failed, skipping: {e}")

        if not factors and score > 0.3:
            factors.append(f"Elevated baseline denial rate for {category} procedures")

        return score, factors, _recommendation(score)

    def _shap_factors(self, X, features: list) -> list[str]:
        """Generate per-prediction risk factors using SHAP values."""
        shap_values = self.explainer.shap_values(X)
        # For binary classification, shap_values may be a list of two arrays
        if isinstance(shap_values, list):
            sv = shap_values[1][0]  # class 1 (denial), first sample
        else:
            sv = shap_values[0]

        factors = []
        feature_contributions = list(zip(self.feature_names, sv, features))
        feature_contributions.sort(key=lambda x: x[1], reverse=True)

        for fname, shap_val, fval in feature_contributions:
            if shap_val < 0.01:
                break
            msg = self._explain_feature(fname, fval, shap_val)
            if msg:
                factors.append(msg)

        return factors

    def _explain_feature(self, fname: str, fval: float, shap_val: float) -> str | None:
        """Convert a feature's SHAP contribution into an actionable message."""
        if fname == "has_xray" and fval == 0.0:
            return f"Missing radiograph increases denial risk (+{shap_val:.0%} impact)"
        if fname == "has_narrative" and fval == 0.0:
            return f"Missing clinical narrative increases denial risk (+{shap_val:.0%} impact)"
        if fname == "has_perio_chart" and fval == 0.0:
            return f"Missing periodontal charting increases denial risk (+{shap_val:.0%} impact)"
        if fname == "charge_anomaly_ratio" and fval > 1.2:
            return f"Charge amount {fval:.0%} of typical cost (+{shap_val:.0%} impact)"
        if fname == "annual_usage_ratio" and fval > 0.7:
            return f"Patient at {fval:.0%} of annual maximum (+{shap_val:.0%} impact)"
        if fname.startswith("cat_") and fval == 1.0 and shap_val > 0.02:
            category = fname.replace("cat_", "")
            return f"{category.replace('_', ' ').title()} procedure category (+{shap_val:.0%} impact)"
        if fname.startswith("plan_") and fval == 1.0 and shap_val > 0.02:
            plan = fname.replace("plan_", "")
            return f"{plan} plan type increases denial risk (+{shap_val:.0%} impact)"
        return None


# Load model
def _load_model():
    model_path = Path("/app/ml/model.joblib")
    if not model_path.exists():
        # Try relative path for local development
        model_path = Path(__file__).parent.parent / "ml" / "model.joblib"
    if model_path.exists():
        import joblib
        data = joblib.load(model_path)
        logger.info(f"Loaded trained ML model from {model_path}")
        return TrainedModel(data)
    else:
        logger.info("No trained model found, using rule-based fallback")
        return DenialRiskModel()


model = _load_model()


# ── Worker ─────────────────────────────────────────────────────────────────

class Worker:
    def __init__(self):
        self.running = True
        self.pool: asyncpg.Pool | None = None
        self.redis: aioredis.Redis | None = None

    async def start(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        self.redis = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)

        # Ensure consumer group exists
        try:
            await self.redis.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        logger.info("Worker started. Recovering pending messages...")
        await self._process_pending()

        logger.info("Processing new messages...")
        await self._process_new()

    async def _process_pending(self):
        """Recover unacknowledged messages from previous runs."""
        while self.running:
            messages = await self.redis.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: "0"}, count=10
            )
            if not messages or not messages[0][1]:
                break
            for stream_name, entries in messages:
                for msg_id, data in entries:
                    await self._handle_message(msg_id, data)

    async def _process_new(self):
        """Main loop: read new messages with blocking."""
        while self.running:
            try:
                messages = await self.redis.xreadgroup(
                    CONSUMER_GROUP, CONSUMER_NAME, {STREAM_NAME: ">"}, count=5, block=2000
                )
                if not messages:
                    continue
                for stream_name, entries in messages:
                    for msg_id, data in entries:
                        if not self.running:
                            return
                        await self._handle_message(msg_id, data)
            except aioredis.ConnectionError:
                logger.warning("Redis connection lost, retrying in 2s...")
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error in consumer loop: {e}")
                await asyncio.sleep(1)

    async def _handle_message(self, msg_id: str, data: dict):
        claim_id = data.get("claim_id")
        if not claim_id:
            logger.warning(f"Message {msg_id} missing claim_id, acking")
            await self.redis.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            return

        start = time.monotonic()
        try:
            # Transition: queued → scoring
            await self.pool.execute(
                "UPDATE claims SET status = 'scoring', updated_at = now() WHERE id = $1 AND status IN ('created', 'queued')",
                UUID(claim_id),
            )

            # Look up patient data for plan type and annual usage
            plan_type = "PPO"
            annual_max_cents = 200000
            annual_used_cents = 0
            patient_id_str = data.get("patient_id")
            if patient_id_str:
                try:
                    patient = await self.pool.fetchrow(
                        "SELECT plan_type, annual_maximum_cents, annual_used_cents FROM patients WHERE id = $1",
                        UUID(patient_id_str),
                    )
                    if patient:
                        plan_type = patient["plan_type"]
                        annual_max_cents = patient["annual_maximum_cents"]
                        annual_used_cents = patient["annual_used_cents"]
                except Exception as e:
                    logger.warning(f"Patient lookup failed for claim {claim_id}: {e}")

            # Score
            score, factors, recommendation = model.predict(
                cdt_code=data.get("cdt_code", "D0000"),
                charged_cents=int(data.get("charged_amount_cents", 0)),
                has_xray=data.get("has_xray", "False") == "True",
                has_narrative=data.get("has_narrative", "False") == "True",
                has_perio_chart=data.get("has_perio_chart", "False") == "True",
                plan_type=plan_type,
                annual_max_cents=annual_max_cents,
                annual_used_cents=annual_used_cents,
            )

            # Write results to PG
            await self.pool.execute(
                """UPDATE claims
                   SET denial_risk_score = $2,
                       denial_risk_factors = $3::jsonb,
                       status = 'scored',
                       scored_at = now(),
                       updated_at = now()
                   WHERE id = $1""",
                UUID(claim_id),
                score,
                json.dumps(factors),
            )

            elapsed_ms = (time.monotonic() - start) * 1000

            # Publish to pub/sub for SSE
            notification = json.dumps({
                "claim_id": claim_id,
                "denial_risk_score": round(score, 3),
                "denial_risk_factors": factors,
                "recommendation": recommendation,
                "processing_time_ms": round(elapsed_ms, 1),
            })
            await self.redis.publish(PUBSUB_CHANNEL, notification)

            # ACK — at-least-once delivery complete
            await self.redis.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)
            logger.info(f"Scored claim {claim_id}: {score:.3f} ({recommendation}) in {elapsed_ms:.1f}ms")

        except Exception as e:
            logger.error(f"Error processing claim {claim_id}: {e}")
            try:
                await self.pool.execute(
                    "UPDATE claims SET status = 'error', updated_at = now() WHERE id = $1",
                    UUID(claim_id),
                )
            except Exception:
                pass

    async def shutdown(self):
        logger.info("Shutting down gracefully...")
        self.running = False
        if self.pool:
            try:
                await self.pool.close()
            except Exception:
                pass
        if self.redis:
            try:
                await self.redis.aclose()
            except Exception:
                pass


# ── Entrypoint ─────────────────────────────────────────────────────────────

async def main():
    health_thread = threading.Thread(target=_run_health_server, daemon=True)
    health_thread.start()

    worker = Worker()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: setattr(worker, 'running', False))

    try:
        await worker.start()
    except asyncio.CancelledError:
        pass
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
