-- DentalFlow Database Schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Patients ──────────────────────────────────────────────────────────────

CREATE TABLE patients (
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

-- ── Claims ────────────────────────────────────────────────────────────────

CREATE TABLE claims (
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

CREATE INDEX idx_claims_status ON claims(status);
CREATE INDEX idx_claims_patient_id ON claims(patient_id);
CREATE INDEX idx_claims_idempotency_key ON claims(idempotency_key);

-- ── Eligibility Checks (audit trail) ─────────────────────────────────────

CREATE TABLE eligibility_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id),
    insurance_provider VARCHAR(100) NOT NULL,
    cdt_code VARCHAR(10) NOT NULL,
    coverage_percent INT,
    eligible BOOLEAN NOT NULL,
    reason TEXT,
    cache_hit BOOLEAN NOT NULL DEFAULT false,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Seed Data ─────────────────────────────────────────────────────────────

INSERT INTO patients (name, date_of_birth, insurance_provider, insurance_id, plan_type, annual_maximum_cents, annual_used_cents) VALUES
    ('Maria Garcia',      '1985-03-15', 'Delta Dental', 'DD-29481037',  'PPO',  200000,  45000),
    ('James Chen',        '1972-11-22', 'MetLife',      'ML-58302741',  'PPO',  150000, 142000),
    ('Aisha Johnson',     '1990-07-08', 'Cigna',        'CG-73019284',  'HMO',  100000,  20000),
    ('Robert Williams',   '1968-01-30', 'Aetna',        'AE-41927365',  'PPO',  175000,  89000),
    ('Sarah Kim',         '1995-12-04', 'Guardian',     'GD-62840193',  'DHMO', 120000, 118500);
