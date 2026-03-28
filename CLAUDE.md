# How I Built DentalFlow

## Starting Point

A senior engineer reviewed my background and gave me handwritten feedback on what I needed to demonstrate: microservices, API gateways, Redis caching, message queues, multistep data persistence, idempotency, and real-time server updates. Separately, this exists as my pitch to a clinical director exploring a dental RCM startup.

I decided to build one project that addressed both: a distributed dental claims pipeline that hits every concept from the senior's notes while serving as a tangible prototype for the startup.

## How Claude Code Was Used

I built DentalFlow in 3 days using [Claude Code](https://docs.anthropic.com/en/docs/build-with-claude/claude-code) as an AI development partner. Here's what that actually looked like:

**My contributions (the thinking):**
- Architecture decisions: which services to split, where to draw sync/async boundaries, Redis Streams over Kafka, SSE over WebSockets, cache-aside over write-through
- Domain modeling: CDT code categories, coverage tier structures, dental insurance rules (annual maximums, tiered coverage, documentation requirements)
- ML design: feature engineering with non-linear interaction effects that justify a trained model over rules, SHAP for per-prediction explanations
- Failure mode analysis: what happens when Redis is down, when XADD fails after INSERT, when the worker crashes between DB write and ACK
- Tradeoff decisions: shared database (faster to build, would split for production), fail-open rate limiting (availability > strictness for a dental tool), recovery loop polling (works at demo scale, would use transactional outbox at production scale)

**Claude Code's contributions (the scaffolding):**
- Translating architectural decisions into working FastAPI services, Docker configurations, and React components
- Boilerplate: Dockerfiles, nginx config, Pydantic models, test fixtures
- The CDT code registry (I specified which categories, Claude Code populated the individual codes)
- CSS/Tailwind styling for the dashboard

**What I had to correct or iterate on:**
- The initial denial model was purely rule-based with flat additive scoring — I redesigned the synthetic data generation with interaction effects (missing X-ray x procedure cost, HMO x implant, annual max exhaustion x charge amount) so the trained model has a measurable edge
- Demo button patient assignments needed reordering so the dashboard shows three distinct risk levels (Low/Medium/High) instead of clustering
- Render deployment required converting the worker from a background service to a web service with a health endpoint (free tier limitation)
- Rate limiter originally used non-atomic INCR + EXPIRE — replaced with atomic Lua script to fix the race condition

## Mapping to Senior Engineer's Feedback

| Feedback Note | Implementation | File |
|---|---|---|
| Microservices (3, all have its own services) | 4 containerized services + infrastructure | `docker-compose.yml` |
| Application Gateway (Routing layer) | Request routing, rate limiting, correlation IDs | `gateway/main.py` |
| Redis (Caching Classes) — Session | Cache-aside eligibility with 15-min TTL | `patient_service/main.py` |
| Multistep data persistence / Avoid Residual Data | Idempotency keys + ordered status transitions + recovery loop | `claims_service/main.py` |
| Queues / Redis / SQS | Redis Streams with consumer groups, XREADGROUP/XACK | `denial_worker/main.py` |
| Streaming / Live update from Server | SSE via Redis pub/sub | `gateway/main.py`, `dashboard/src/hooks/useSSE.ts` |
| Item Potency (Idempotency) | UNIQUE constraint on `idempotency_key`, duplicate detection returns existing record | `claims_service/main.py` |

## Technical Conventions

- **Python 3.12**, FastAPI, asyncpg, redis.asyncio
- **Money is always integer cents** — `150000` = $1,500.00
- **State machine** for claims: `created -> queued -> scoring -> scored -> submitted -> accepted -> denied -> error`
- **At-least-once delivery**: XREADGROUP -> process -> DB write -> XACK. Never ACK before persisting.
- **Fail open**: If Redis is down, rate limiting allows requests through.
- **Docker build context** is project root for backend services so `shared/` is accessible.

## Commands

```bash
make help         # Show all available commands
make build        # Rebuild and start all 6 containers
make test         # Run all tests (services must be running)
make test-unit    # Run unit tests only (no Docker needed)
make demo         # Run the CLI demo script
make train        # Train the ML denial prediction model
make health       # Check system health
make clean        # Stop services and delete all data
```

## Domain Context (Dental RCM)

The dental revenue cycle: Patient intake -> Insurance eligibility verification -> Treatment -> Coding (CDT codes) -> Claims submission -> Adjudication -> Payment posting -> Denial management -> Patient billing -> Collections.

Key dental insurance quirks this system models:
- Annual maximums ($1000-$2000/year typical) — once exhausted, nothing is covered
- Tiered coverage: preventive 100%, basic restorative 80%, major 50%, implants often excluded
- CDT codes not CPT codes — separate billing ecosystem
- Denials often caused by: missing X-rays, missing narratives, wrong codes, frequency limitations
- Small practices do this all manually — that's the pain point
