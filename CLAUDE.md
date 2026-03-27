# DentalFlow

## What this project is

DentalFlow is a microservices-based dental claims processing pipeline. It serves two purposes simultaneously:

1. **Portfolio piece** — demonstrates distributed systems competence (microservices, API gateways, Redis caching, message queues, idempotency, graceful degradation, real-time updates). Every feature maps to specific feedback from a senior engineer on what skills to demonstrate.

2. **Startup prototype** — a working demo for Dr. Nipa, a DDS and former clinical director who's exploring a dental RCM startup. She's targeting small independent dental practices (1-3 staff) that can't afford enterprise software but need automation for eligibility verification, claims submission, and denial management.

The demo must be accessible as a **live URL anyone can visit** + a strong GitHub repo. Not a local screen share.

## Architecture

6 Docker containers orchestrated via Docker Compose:

- **Dashboard** (React + nginx, :3000) — real-time claims pipeline view with SSE, eligibility checker, system health
- **API Gateway** (FastAPI, :8000) — routing, rate limiting (Redis, fail-open), correlation IDs, SSE stream
- **Patient Service** (FastAPI, :8001) — patient CRUD, eligibility verification with Redis cache-aside (15-min TTL)
- **Claims Service** (FastAPI, :8002) — CDT code validation, PostgreSQL persistence, idempotency keys (UNIQUE constraint), publishes to Redis Streams
- **Denial Prediction Worker** — async consumer, reads Redis Streams via XREADGROUP with consumer groups, trained ML model (GradientBoosting) with rule-based fallback, writes results to PostgreSQL, publishes to Redis pub/sub for SSE
- **Infrastructure** — PostgreSQL 16 + Redis 7

Key boundary: Claims Service is synchronous (returns immediately). Denial scoring is asynchronous (via Redis Streams). This is deliberate — the front desk gets instant confirmation, ML happens in the background.

The ML model is a GradientBoostingClassifier trained on 12,000 synthetic claims (`ml/train_model.py`). The trained model (`ml/model.joblib`) is loaded by the denial worker at startup. If the model file is missing, the worker falls back to rule-based scoring.

## Conventions

- **Python 3.12**, FastAPI, asyncpg for database, redis.asyncio for Redis
- **Money is always integer cents** — never floats. `150000` = $1,500.00
- **Idempotency** via database UNIQUE constraint on `idempotency_key`. Catch `UniqueViolationError`, return existing record. Not an error.
- **State machine** for claims: `created → queued → scoring → scored → submitted → accepted → denied → error`. Single-column atomic UPDATEs only.
- **At-least-once delivery**: XREADGROUP → process → DB write → XACK. Never ACK before persisting.
- **Fail open**: If Redis is down, rate limiting allows requests through. Availability > strict enforcement.
- **Docker build context** is project root (`.`) for backend services, so `shared/` is accessible. Dashboard build context is `./dashboard`.
- Use `asyncpg` connection pools (min=2, max=10). Never create connections per-request.
- CDT codes (Current Dental Terminology) are the dental equivalent of CPT codes. Format: D followed by 4 digits. D0xxx=diagnostic, D1xxx=preventive, D2xxx=restorative, etc.
- All services log with correlation ID when available.
- All 8 code quality fixes from the code quality prompt have been applied.

## Domain context (dental RCM)

The dental revenue cycle: Patient intake → Insurance eligibility verification → Treatment → Coding (CDT codes) → Claims submission → Adjudication → Payment posting → Denial management → Patient billing → Collections.

Key dental insurance quirks this system models:
- Annual maximums ($1000-$2000/year typical) — once exhausted, nothing is covered
- Tiered coverage: preventive 100%, basic restorative 80%, major 50%, implants often excluded
- CDT codes not CPT codes — separate billing ecosystem
- Denials often caused by: missing X-rays, missing narratives, wrong codes, frequency limitations
- Small practices do this all manually — that's the pain point

## Commands

```bash
make help         # Show all available commands

# Key commands:
make build        # Rebuild and start all 6 containers
make health       # Check system health
make test         # Run all tests (services must be running)
make demo         # Run the CLI demo script
make train        # Train the ML denial prediction model
make logs         # Tail logs from all services
make clean        # Stop services and delete all data
```

Dashboard is served on **port 3000** via nginx.

## Files that matter

- `docker-compose.yml` — the system topology (6 services)
- `scripts/init_db.sql` — PostgreSQL schema + seed data
- `shared/models.py` — Pydantic contracts shared across services
- `gateway/main.py` — routing, rate limiting, SSE
- `patient_service/main.py` — eligibility with cache-aside
- `claims_service/main.py` — idempotency, CDT validation, stream publishing
- `denial_worker/main.py` — consumer loop, ML model (trained + rule-based fallback), pub/sub notification
- `ml/train_model.py` — synthetic data generation and model training
- `ml/model.joblib` — trained GradientBoosting model
- `dashboard/` — React + TypeScript dashboard with SSE real-time updates
- `dashboard/nginx.conf` — nginx config proxying /api/* to gateway
- `docs/architecture.svg` — system architecture diagram
- `scripts/demo.py` — end-to-end pipeline demonstration
- `Makefile` — all project commands (`make help` for reference)
- `tests/` — integration + unit tests
