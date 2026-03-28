"""API Gateway — routing, rate limiting, correlation IDs, SSE."""

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from shared.models import HealthResponse

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
PATIENT_SERVICE_URL = os.environ.get("PATIENT_SERVICE_URL", "http://localhost:8001")
CLAIMS_SERVICE_URL = os.environ.get("CLAIMS_SERVICE_URL", "http://localhost:8002")

RATE_LIMIT = 100  # requests per minute
FORWARD_HEADERS = {"content-type", "x-correlation-id"}
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

# Lua script for atomic rate limiting: INCR + EXPIRE in one round trip.
# Returns the current count. Sets TTL only on first increment (new key).
_RATE_LIMIT_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


# ── App lifecycle ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
    app.state.rate_limit_script = app.state.redis.register_script(_RATE_LIMIT_LUA)
    yield
    await app.state.http_client.aclose()
    await app.state.redis.aclose()


app = FastAPI(title="DentalFlow API Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware ─────────────────────────────────────────────────────────────

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = corr_id
    response: Response = await call_next(request)
    response.headers["X-Correlation-ID"] = corr_id
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate limiting for health checks and SSE
    if request.url.path in ("/health", "/api/claims/stream"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{client_ip}"

    try:
        current = await app.state.rate_limit_script(keys=[key], args=[60])
        if current > RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again in 60 seconds."},
            )
    except Exception:
        # Fail open — allow request if Redis is down
        pass

    return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Skip auth for health checks and SSE stream
    if request.url.path in ("/health", "/api/claims/stream"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # In production: validate JWT, extract user/roles, enforce scopes.
        # For this demo, any Bearer token is accepted.
        request.state.user = "authenticated"
    else:
        # Demo mode: allow unauthenticated access with a demo user context.
        # Production would return 401 here.
        request.state.user = "demo_user"

    response = await call_next(request)
    return response


# ── Health ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    deps = {}
    client: httpx.AsyncClient = app.state.http_client

    # Check Redis
    try:
        await app.state.redis.ping()
        deps["redis"] = "ok"
    except Exception:
        deps["redis"] = "error"

    # Check downstream services
    for name, url in [("patient-service", PATIENT_SERVICE_URL), ("claims-service", CLAIMS_SERVICE_URL)]:
        try:
            resp = await client.get(f"{url}/health")
            deps[name] = "ok" if resp.status_code == 200 else "error"
        except Exception:
            deps[name] = "error"

    overall = "ok" if all(v == "ok" for v in deps.values()) else "degraded"
    return HealthResponse(status=overall, service="gateway", dependencies=deps)


# ── SSE endpoint ───────────────────────────────────────────────────────────

@app.get("/api/claims/stream")
async def claim_stream(request: Request):
    async def event_generator():
        pubsub = app.state.redis.pubsub()
        await pubsub.subscribe("claim_updates")
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    yield {"event": "claim_update", "data": message["data"]}
                else:
                    yield {"event": "heartbeat", "data": ""}
        finally:
            await pubsub.unsubscribe("claim_updates")
            await pubsub.aclose()

    return EventSourceResponse(event_generator())


# ── Proxy helpers ──────────────────────────────────────────────────────────

def _proxy_headers(request: Request) -> dict:
    headers = {"X-Correlation-ID": getattr(request.state, "correlation_id", str(uuid.uuid4()))}
    ct = request.headers.get("content-type")
    if ct:
        headers["content-type"] = ct
    return headers


async def _proxy(method: str, url: str, request: Request):
    client: httpx.AsyncClient = app.state.http_client
    headers = _proxy_headers(request)
    body = await request.body() if method in ("POST", "PUT", "PATCH") else None
    try:
        resp = await client.request(method, url, content=body, headers=headers, params=dict(request.query_params))
        safe_headers = {k: v for k, v in resp.headers.items() if k.lower() in FORWARD_HEADERS}
        return Response(content=resp.content, status_code=resp.status_code, headers=safe_headers)
    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={"detail": f"Downstream service unavailable: {url.split('/')[2]}"},
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"detail": f"Downstream service timeout: {url.split('/')[2]}"},
        )
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Bad gateway: {str(e)}"},
        )


# ── Patient routes ─────────────────────────────────────────────────────────

@app.get("/api/patients")
async def proxy_list_patients(request: Request):
    return await _proxy("GET", f"{PATIENT_SERVICE_URL}/patients", request)


@app.get("/api/patients/{patient_id}")
async def proxy_get_patient(patient_id: UUID, request: Request):
    return await _proxy("GET", f"{PATIENT_SERVICE_URL}/patients/{patient_id}", request)


@app.post("/api/eligibility")
async def proxy_eligibility(request: Request):
    return await _proxy("POST", f"{PATIENT_SERVICE_URL}/eligibility", request)


# ── Claims routes ──────────────────────────────────────────────────────────

@app.get("/api/claims")
async def proxy_list_claims(request: Request):
    return await _proxy("GET", f"{CLAIMS_SERVICE_URL}/claims", request)


@app.get("/api/claims/{claim_id}")
async def proxy_get_claim(claim_id: UUID, request: Request):
    return await _proxy("GET", f"{CLAIMS_SERVICE_URL}/claims/{claim_id}", request)


@app.post("/api/claims")
async def proxy_create_claim(request: Request):
    return await _proxy("POST", f"{CLAIMS_SERVICE_URL}/claims", request)
