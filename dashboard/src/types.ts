export type ClaimStatus = 'created' | 'queued' | 'scoring' | 'scored' | 'submitted' | 'accepted' | 'denied' | 'error';
export type PlanType = 'PPO' | 'HMO' | 'DHMO';

export interface Patient {
  id: string;
  name: string;
  date_of_birth: string;
  insurance_provider: string;
  insurance_id: string;
  plan_type: PlanType;
  annual_maximum_cents: number;
  annual_used_cents: number;
}

export interface Claim {
  id: string;
  idempotency_key: string;
  patient_id: string;
  cdt_code: string;
  cdt_description: string | null;
  procedure_date: string;
  tooth_number: number | null;
  charged_amount_cents: number;
  has_xray: boolean;
  has_narrative: boolean;
  has_perio_chart: boolean;
  status: ClaimStatus;
  denial_risk_score: number | null;
  denial_risk_factors: string[] | null;
  scored_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ClaimCreateRequest {
  idempotency_key: string;
  patient_id: string;
  cdt_code: string;
  procedure_date: string;
  tooth_number?: number;
  charged_amount_cents: number;
  has_xray: boolean;
  has_narrative: boolean;
  has_perio_chart: boolean;
}

export interface EligibilityRequest {
  patient_id: string;
  cdt_code: string;
}

export interface EligibilityResponse {
  patient_id: string;
  patient_name: string;
  insurance_provider: string;
  plan_type: PlanType;
  cdt_code: string;
  cdt_category: string;
  coverage_percent: number;
  estimated_patient_cost_cents: number;
  estimated_insurance_pays_cents: number;
  annual_maximum_cents: number;
  annual_used_cents: number;
  annual_remaining_cents: number;
  eligible: boolean;
  reason: string | null;
  cache_hit: boolean;
}

export interface HealthResponse {
  status: string;
  service: string;
  dependencies: Record<string, string> | null;
}

export interface ClaimUpdateEvent {
  claim_id: string;
  denial_risk_score: number;
  denial_risk_factors: string[];
  recommendation: string;
  processing_time_ms: number;
}
