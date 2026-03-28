# DentalFlow

Async dental claims processing pipeline with ML-based denial prediction.

## Problem

Dental practices lose 15-30% of revenue to preventable claim denials — missing X-rays, wrong CDT codes, exceeded annual maximums. Small independent practices (1-3 staff) can't afford enterprise RCM software. DentalFlow scores denial risk before submission using an ML model trained on synthetic dental claims data. The model explains exactly which factors drive each prediction — missing X-rays, plan type, annual max exhaustion — so the billing coordinator knows what to fix.

## Live Demo

**[dentalflow-dashboard.onrender.com](https://dentalflow-dashboard.onrender.com)**

Free tier — first load takes ~30 seconds as services wake up. Click **"Run Demo"** to submit three claims and watch them flow through the pipeline in real time.

## Architecture

![Architecture](docs/architecture.svg)

A claim enters through the API gateway, which routes it to the claims service for CDT code validation and idempotent persistence. The claims service publishes the claim to a Redis Stream, and the denial prediction worker picks it up via XREADGROUP with consumer groups. The worker looks up the patient's insurance plan and annual usage from PostgreSQL, runs the claim through a trained GradientBoosting model with SHAP explanations, writes the results back to the database, then publishes a notification via Redis pub/sub. The gateway's SSE endpoint pushes that notification to the dashboard in real time. The key architectural decision is the sync/async boundary: the front desk gets instant confirmation that the claim was received (synchronous), while ML scoring happens in the background (asynchronous).

## What It Demonstrates

| Concept | Implementation | Location |
|---------|---------------|----------|
| Microservices | 6 containerized services | `docker-compose.yml` |
| API Gateway | Request routing, rate limiting (sliding window), correlation IDs | `gateway/main.py` |
| Cache-aside | Redis eligibility cache, 15-min TTL, key = `elig:{patient_id}:{provider}:{cdt}` | `patient_service/main.py` |
| Message queue | Redis Streams with consumer groups, XREADGROUP/XACK | `denial_worker/main.py` |
| Idempotency | DB UNIQUE constraint on client-generated keys, returns 200 for duplicates | `claims_service/main.py` |
| At-least-once delivery | Worker persists to DB before XACK | `denial_worker/main.py` |
| Stuck message recovery | Background job republishes stale claims (checks both `created_at` and `updated_at`) | `claims_service/main.py` |
| Real-time updates | SSE via Redis pub/sub | `gateway/main.py` |
| ML inference pipeline | GradientBoosting model with SHAP explanations, loaded at startup | `denial_worker/main.py` |
| Graceful degradation | Rate limiter fails open when Redis is down | `gateway/main.py` |
| State machine | Claim status transitions enforced by CHECK constraint | `claims_service/main.py` |
| Money as integers | All amounts stored as cents (no floating point) | throughout |

## Demo Scenarios

Clicking "Run Demo" submits three claims designed to produce different risk levels:

- **Sarah Kim** (DHMO plan, 99% of annual maximum used) -- D6010 implant, no documentation. The combination of a restrictive plan, near-exhausted benefits, and missing radiographs/narrative produces a **high risk** score (~95%).
- **James Chen** (PPO plan, 95% of annual maximum used) -- D2750 crown without X-ray. Missing radiograph on an expensive restorative procedure with nearly exhausted benefits produces a **medium risk** score (~65%).
- **Maria Garcia** (PPO plan, 22% of annual maximum used) -- D1110 adult prophylaxis with X-ray. Routine cleaning on a PPO plan with plenty of remaining benefits is **low risk** (~5%).

Results appear in the claims table in real time via SSE as the denial worker scores each claim. Click any row to expand and see the SHAP-based risk factors with per-prediction impact percentages.

## ML Model

The denial prediction model is a GradientBoostingClassifier trained on 20,000 synthetic claims. The synthetic data includes 8 non-linear interaction effects that a simple rule-based model cannot capture:

- Missing X-ray penalty scales with procedure cost (a missing X-ray on a $3,000 crown is worse than on a $200 filling)
- Annual benefit exhaustion compounds with procedure cost
- HMO/DHMO plans deny implants and prosthodontics at higher rates than PPO
- Multiple missing documents compound non-linearly
- Charge anomaly follows a sigmoid curve, not a step function
- PPO preventive procedures have near-zero denial rates regardless of other factors

The trained model beats the rule-based baseline on all five metrics:

| Metric | Trained Model | Rule-Based |
|--------|--------------|------------|
| Accuracy | 0.720 | 0.698 |
| Precision | 0.650 | 0.628 |
| Recall | 0.471 | 0.387 |
| F1 | 0.546 | 0.479 |
| AUC | 0.750 | 0.729 |

Risk factors use SHAP TreeExplainer for per-prediction explanations rather than global feature importance. Instead of "missing X-ray is generally important," the model tells you "Missing radiograph increases denial risk (+28% impact) for this specific claim." That distinction matters for a billing coordinator deciding what to fix.

The model is trained on synthetic data, not real claims -- this is a prototype demonstrating the ML pipeline pattern (training, serialization, inference, explanation), not a production model. If the trained model file is missing, the worker falls back to a rule-based scorer so the system always works.

## Tech Stack

- **Backend**: Python 3.12, FastAPI, asyncpg, redis.asyncio
- **ML**: scikit-learn GradientBoostingClassifier, SHAP
- **Database**: PostgreSQL 16
- **Cache/Queue**: Redis 7 (cache-aside, Streams with consumer groups, pub/sub)
- **Frontend**: React 18, TypeScript, Tailwind CSS, SSE
- **Infrastructure**: Docker Compose, nginx reverse proxy
- **Deployment**: Render (free tier)

## Design Decisions

**Redis Streams over Kafka** -- Same consumer group semantics (XREADGROUP, XACK, pending entry list) at the right scale. Kafka's partition-level parallelism and multi-datacenter replication are built for millions of events per second across dozens of consumers. A single-practice dental tool doesn't need that.

**Sync/async split** -- The front desk gets instant confirmation that the claim was persisted. ML scoring happens asynchronously via Redis Streams. The patient doesn't wait at the desk while the model runs. This also means the claims service has no dependency on the ML model -- if the worker is down, claims still get created and scored when it comes back up.

**Money as integer cents** -- `150000` = $1,500.00. Eliminates floating-point rounding in claim amounts. Every billing system does this. The frontend converts to dollars for display.

**SSE over WebSockets** -- The dashboard only needs server-to-client push for claim status updates. SSE is simpler, auto-reconnects natively, and works through HTTP proxies without upgrade negotiation. The gateway sends heartbeats every second to keep the connection alive on Render's free tier.

**Database-level idempotency** -- UNIQUE constraint on `idempotency_key`. The client generates a UUID before submission. If the same key is sent twice (network retry, double-click), the database catches it and the service returns the existing record with a 200 instead of 201. No distributed locks, no Redis-based dedup. The database is the source of truth.

**At-least-once with DB-first** -- The worker writes scoring results to PostgreSQL before calling XACK. If it crashes between the DB write and the ACK, the message gets redelivered and the worker re-processes it. The DB write is idempotent (UPDATE by primary key), so reprocessing is safe.

**Fail-open rate limiting** -- The gateway's rate limiter uses Redis sliding window counters. If Redis is unreachable, requests pass through instead of being rejected. For a dental practice tool, availability matters more than strict rate enforcement.

**SHAP over feature importance** -- Global feature importance tells you what matters on average across all predictions. SHAP values tell you why *this specific claim* was flagged and by how much. "Missing radiograph increases denial risk (+28% impact)" is actionable. "has_xray has importance 0.07" is not.

## Quick Start

```bash
git clone https://github.com/RRobin711/dentalflow.git
cd dentalflow
make train        # Train the ML model
make build        # Build and start all 6 containers
make health       # Verify everything is running
# Open http://localhost:3000
make demo         # CLI demo
make test         # 28 tests
```

## Tests

28 tests (13 unit + 15 integration) covering health checks, patient CRUD, eligibility with cache hit/miss verification, claim creation with CDT code validation, idempotency (duplicate key returns same record), denial scoring at three risk levels (low/medium/high), rate limiting (101st request gets 429), and trained model unit tests verifying interaction effects and SHAP explanations.

```bash
make build        # Services must be running
make test         # pytest tests/ -v
```

## Production Considerations

This is a working demo, not production software. Here's what I'd change for a real deployment:

**Authentication & Authorization** -- The gateway has a placeholder auth middleware that accepts demo traffic. Production would use JWT tokens issued by an identity provider (Auth0, Cognito), validated at the gateway, with per-service role scopes (front desk can submit claims, only managers can override denial recommendations). HIPAA compliance would require audit logging of every access.

**Database per Service** -- All services currently share one PostgreSQL instance. This couples them at the data layer, which defeats independent deployability. Production would give each service its own database (or at minimum its own schema), with cross-service communication happening through APIs or events, not shared tables. The patient service would own the `patients` table exclusively, and the claims service would maintain its own denormalized patient reference.

**Schema Migrations** -- Tables are created via inline `CREATE TABLE IF NOT EXISTS` in service startup. Production would use Alembic (or a similar migration tool) with versioned migration files, so schema changes are trackable, reversible, and coordinated across deployments.

**Rate Limiter** -- Uses a sliding window log (sorted sets) for accurate rate limiting without the boundary problem of fixed window counters. For multi-gateway deployments, I'd add configurable per-route limits and token bucket algorithms for burst handling.

**Transactional Outbox** -- The claims service does INSERT then XADD as two separate operations. If XADD fails, a recovery loop polls for stuck claims every 30 seconds. This works at demo scale but polling doesn't scale. Production would use the transactional outbox pattern: write the event to an `outbox` table in the same transaction as the claim INSERT, then a separate process tails the outbox and publishes to the stream. Guarantees exactly-once publishing without polling.

**Observability** -- Services log with correlation IDs, but production would add structured JSON logging, distributed tracing (OpenTelemetry), metrics (Prometheus), and alerting on error rates, queue depth, and scoring latency.

**ML Model Management** -- The model is a static `.joblib` file baked into the Docker image. Production would use a model registry (MLflow, SageMaker), versioned deployments, A/B testing between model versions, and monitoring for data drift and prediction quality degradation.

## Project Context

Built as a portfolio project demonstrating distributed systems patterns and as a prototype for a dental RCM startup targeting small independent practices. The ML model is trained on synthetic data -- a production version would use real claims data with proper HIPAA compliance and would replace the simulated eligibility checks with actual insurance API integrations.
