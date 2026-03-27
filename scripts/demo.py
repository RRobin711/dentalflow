#!/usr/bin/env python3
"""DentalFlow Demo Script — exercises the full pipeline with colored output."""

import sys
import time
import uuid

import httpx

BASE = "http://localhost:8000"

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def green(s): return f"{GREEN}{s}{RESET}"
def yellow(s): return f"{YELLOW}{s}{RESET}"
def red(s): return f"{RED}{s}{RESET}"
def cyan(s): return f"{CYAN}{s}{RESET}"
def bold(s): return f"{BOLD}{s}{RESET}"
def step(n, title): print(f"\n{CYAN}{'='*60}\n  Step {n}: {title}\n{'='*60}{RESET}")


def main():
    client = httpx.Client(base_url=BASE, timeout=15.0)

    print(f"\n  {bold('Dashboard')}: {cyan('http://localhost:3000')}")
    print(f"  Open the dashboard in a browser to see claims update in real time.\n")

    # ── Step 1: Health Check ──────────────────────────────────────────────
    step(1, "Health Check")
    try:
        r = client.get("/health")
        data = r.json()
        print(f"  Gateway: {green('OK') if data['status'] in ('ok','degraded') else red('FAIL')}")
        for svc, status in (data.get("dependencies") or {}).items():
            print(f"    {svc}: {green(status) if status == 'ok' else red(status)}")
    except Exception as e:
        print(red(f"  FAILED: {e}"))
        print(red("  Make sure services are running: docker compose up --build"))
        sys.exit(1)

    # ── Step 2: List Patients ─────────────────────────────────────────────
    step(2, "List Patients (seeded data)")
    r = client.get("/api/patients")
    patients = r.json()
    print(f"  Found {green(str(len(patients)))} patients:\n")
    for p in patients:
        remaining = (p["annual_maximum_cents"] - p["annual_used_cents"]) / 100
        used_pct = p["annual_used_cents"] / p["annual_maximum_cents"] * 100
        color = red if used_pct > 90 else yellow if used_pct > 60 else green
        print(f"  {bold(p['name']):40s}  {p['insurance_provider']:15s}  {p['plan_type']:5s}  "
              f"Remaining: {color(f'${remaining:,.0f}')}  ({used_pct:.0f}% used)")

    patient_id = patients[0]["id"]  # Maria Garcia (Delta Dental, PPO)
    patient2_id = patients[1]["id"]  # James Chen (MetLife, near max)

    # ── Step 3: Eligibility Checks ────────────────────────────────────────
    step(3, "Eligibility Checks (cache-aside pattern)")

    print(f"\n  {bold('3a')}: First call — cache MISS")
    r = client.post("/api/eligibility", json={"patient_id": patient_id, "cdt_code": "D2740"})
    elig = r.json()
    print(f"    Patient: {elig['patient_name']}")
    print(f"    CDT D2740 ({elig['cdt_category']}): {elig['coverage_percent']}% coverage")
    print(f"    Insurance pays: ${elig['estimated_insurance_pays_cents']/100:,.0f}")
    print(f"    Patient pays:   ${elig['estimated_patient_cost_cents']/100:,.0f}")
    print(f"    Cache hit: {red('NO') if not elig['cache_hit'] else green('YES')}")

    print(f"\n  {bold('3b')}: Second call (same params) — cache HIT")
    r = client.post("/api/eligibility", json={"patient_id": patient_id, "cdt_code": "D2740"})
    elig2 = r.json()
    print(f"    Cache hit: {green('YES') if elig2['cache_hit'] else red('NO')}")

    print(f"\n  {bold('3c')}: Different procedure — cache MISS (different key)")
    r = client.post("/api/eligibility", json={"patient_id": patient_id, "cdt_code": "D1110"})
    elig3 = r.json()
    print(f"    CDT D1110 ({elig3['cdt_category']}): {elig3['coverage_percent']}% coverage")
    print(f"    Cache hit: {red('NO') if not elig3['cache_hit'] else green('YES')}")

    # ── Step 4: Submit Claims ─────────────────────────────────────────────
    step(4, "Submit Claims (varying risk levels)")
    today = "2026-03-27"

    claims_to_submit = [
        {
            "label": "Routine cleaning (LOW risk)",
            "data": {
                "idempotency_key": f"demo-cleaning-{uuid.uuid4().hex[:8]}",
                "patient_id": patient_id,
                "cdt_code": "D1110",
                "procedure_date": today,
                "charged_amount_cents": 12500,
                "has_xray": True,
                "has_narrative": True,
                "has_perio_chart": False,
            },
        },
        {
            "label": "Crown WITHOUT X-ray (HIGH risk)",
            "data": {
                "idempotency_key": f"demo-crown-{uuid.uuid4().hex[:8]}",
                "patient_id": patient_id,
                "cdt_code": "D2740",
                "procedure_date": today,
                "tooth_number": 14,
                "charged_amount_cents": 120000,
                "has_xray": False,
                "has_narrative": True,
                "has_perio_chart": False,
            },
        },
        {
            "label": "Implant with NO docs (VERY HIGH risk)",
            "data": {
                "idempotency_key": f"demo-implant-{uuid.uuid4().hex[:8]}",
                "patient_id": patient2_id,
                "cdt_code": "D6010",
                "procedure_date": today,
                "tooth_number": 19,
                "charged_amount_cents": 350000,
                "has_xray": False,
                "has_narrative": False,
                "has_perio_chart": False,
            },
        },
        {
            "label": "Perio scaling WITHOUT perio chart (MEDIUM risk)",
            "data": {
                "idempotency_key": f"demo-perio-{uuid.uuid4().hex[:8]}",
                "patient_id": patient_id,
                "cdt_code": "D4341",
                "procedure_date": today,
                "charged_amount_cents": 28000,
                "has_xray": True,
                "has_narrative": True,
                "has_perio_chart": False,
            },
        },
    ]

    claim_ids = []
    first_idemp_key = None
    for i, claim_info in enumerate(claims_to_submit):
        print(f"\n  {bold(f'4{chr(97+i)}')}: {claim_info['label']}")
        r = client.post("/api/claims", json=claim_info["data"])
        c = r.json()
        claim_ids.append(c["id"])
        if i == 0:
            first_idemp_key = claim_info["data"]["idempotency_key"]
        status_color = green if c["status"] in ("created", "queued") else yellow
        print(f"    Claim ID: {c['id'][:8]}...")
        print(f"    Status:   {status_color(c['status'])}")
        print(f"    CDT:      {c['cdt_code']} — {c.get('cdt_description', 'N/A')}")
        print(f"    Amount:   ${c['charged_amount_cents']/100:,.0f}")

    # ── Step 5: Idempotency Demo ──────────────────────────────────────────
    step(5, "Idempotency Demo")
    print(f"  Resubmitting first claim with same idempotency key...")
    r = client.post("/api/claims", json=claims_to_submit[0]["data"])
    c2 = r.json()
    same = c2["id"] == claim_ids[0]
    print(f"  Original claim ID: {claim_ids[0][:8]}...")
    print(f"  Resubmit claim ID: {c2['id'][:8]}...")
    print(f"  Same claim returned: {green('YES') if same else red('NO')}")
    print(f"  {green('Idempotency working correctly!') if same else red('IDEMPOTENCY FAILURE!')}")

    # ── Step 6: Wait for scoring & fetch results ──────────────────────────
    step(6, "Async Scoring Results")
    print(f"  Waiting 4 seconds for denial-worker to score claims...")
    time.sleep(4)

    print(f"\n  {bold('Scored Claims')}:\n")
    r = client.get("/api/claims")
    all_claims = r.json()
    for c in all_claims:
        score = c.get("denial_risk_score")
        if score is not None:
            if score >= 0.7:
                score_color = red
                label = "HIGH"
            elif score >= 0.4:
                score_color = yellow
                label = "MEDIUM"
            else:
                score_color = green
                label = "LOW"
            print(f"  {c['cdt_code']} ({c.get('cdt_description','')[:35]:35s})  "
                  f"Score: {score_color(f'{score:.3f} [{label}]')}")
            factors = c.get("denial_risk_factors") or []
            for f in factors:
                print(f"      → {yellow(f)}")
        else:
            print(f"  {c['cdt_code']} ({c.get('cdt_description','')[:35]:35s})  "
                  f"Score: {yellow('pending...')}  Status: {c['status']}")

    # ── Step 7: Invalid CDT code ──────────────────────────────────────────
    step(7, "Invalid CDT Code Rejection")
    r = client.post("/api/claims", json={
        "idempotency_key": f"demo-invalid-{uuid.uuid4().hex[:8]}",
        "patient_id": patient_id,
        "cdt_code": "X9999",
        "procedure_date": today,
        "charged_amount_cents": 5000,
    })
    print(f"  Status code: {red(str(r.status_code)) if r.status_code == 422 else green(str(r.status_code))}")
    print(f"  Response: {r.json().get('detail', r.text)}")
    print(f"  {green('Invalid code correctly rejected!') if r.status_code == 422 else red('SHOULD HAVE BEEN 422!')}")

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{CYAN}{'='*60}")
    print(f"  DentalFlow Demo Complete!")
    print(f"{'='*60}{RESET}")
    print(f"""
  {bold('Systems Concepts Demonstrated')}:
  {green('✓')} Microservices architecture with API gateway
  {green('✓')} Cache-aside pattern (Redis TTL=15min)
  {green('✓')} Idempotent claim submission (unique constraint)
  {green('✓')} Async processing via Redis Streams
  {green('✓')} Consumer groups with at-least-once delivery
  {green('✓')} ML-based denial risk scoring
  {green('✓')} Real-time updates via pub/sub → SSE
  {green('✓')} CDT code validation
  {green('✓')} Correlation ID distributed tracing
  {green('✓')} Rate limiting (sliding window)
  {green('✓')} Health checks with dependency status
  {green('✓')} Graceful degradation patterns

  All claims submitted. Check the dashboard to see denial risk scores and recommendations.

  {bold('Try these next')}:
  • Dashboard:   {cyan('http://localhost:3000')}
  • SSE stream:  curl -N http://localhost:8000/api/claims/stream
  • Stop worker: docker compose stop denial-worker
  • Submit claim via curl, restart worker → claim gets scored
""")


if __name__ == "__main__":
    main()
